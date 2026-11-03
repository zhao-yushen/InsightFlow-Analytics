"""Behaviour a real sales ledger demands, written down after running one through the platform."""

from __future__ import annotations

import importlib
from datetime import date

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from insightflow.backup import KEEP_BACKUPS, create_backup, list_backups, restore_backup
from insightflow.churn import score_customers, train_churn_model
from insightflow.decision_lab import ScenarioInputs, UncertaintyInputs, simulate_scenario
from insightflow.diagnostics import generate_diagnostics, monthly_anomalies
from insightflow.elasticity import (
    _margin_change,
    _poisson_slope,
    category_price_moves,
    estimate_elasticities,
)
from insightflow.etl import (
    NON_MERCHANDISE,
    clean_transactions,
    derive_categories,
    service_lines,
)
from insightflow.geography import (
    canonical_country,
    country_label,
    market_coordinates,
    market_region,
    region_label,
    shipping_multiplier,
)
from insightflow.metrics import (
    FilterSpec,
    customer_coverage,
    date_bounds,
    kpi_summary,
    leak_drivers,
    partial_month,
    previous_period,
    product_profitability,
    rejection_summary,
    target_status,
)
from insightflow.narrative import LEAK_LABELS, rejection_table
from insightflow.optimizer import search_plans
from insightflow.supply import inventory_policy
from insightflow.warehouse import build_warehouse, query_df


def _line(invoice: str, code: str = "85123A", quantity: int = 2, **overrides) -> dict:
    return {
        "invoice_no": invoice,
        "stock_code": code,
        "description": "WHITE HEART HOLDER",
        "quantity": quantity,
        "invoice_date": "2025-03-14 10:00:00",
        "unit_price": 3.0,
        "customer_id": f"C{invoice}",
        "country": "United Kingdom",
        **overrides,
    }


def _build(tmp_path, rows: list[dict]):
    db = tmp_path / "ledger.db"
    result = clean_transactions(pd.DataFrame(rows), transaction_status="Verified")
    build_warehouse(result, db)
    return db, result


def test_postage_fees_and_adjustments_are_not_sales_of_goods():
    codes = pd.Series(
        ["POST", "DOT", "M", "BANK CHARGES", "AMAZONFEE", "GIFT_0001_20", "85123A", "DCGS0076", "M"],
        dtype="string",
    )
    names = pd.Series(
        [
            "POSTAGE",
            "DOTCOM POSTAGE",
            "MANUAL",
            "BANK CHARGES",
            "AMAZON FEE",
            "TO PUSH ORDER THROUGH",
            "WHITE HEART HOLDER",
            "SUNJAR LED NIGHT LIGHT",
            "SIZE M SHIRT",
        ],
        dtype="string",
    )
    flagged = service_lines(codes, names).astype(bool).tolist()
    assert flagged == [True, True, True, True, True, True, False, False, False]


def test_non_merchandise_lines_leave_revenue_but_stay_auditable(tmp_path):
    db, result = _build(
        tmp_path,
        [
            _line("1"),
            _line("2", "POST", 1, description="POSTAGE", unit_price=18.0),
            _line("C3", "AMAZONFEE", -1, description="AMAZON FEE", unit_price=500.0),
        ],
    )
    kpi = kpi_summary(db, FilterSpec())
    assert kpi["revenue"] == pytest.approx(6.0)
    assert kpi["returns_value"] == 0
    held = rejection_summary(db).set_index("reason")
    assert held.loc[NON_MERCHANDISE, "rows"] == 2
    assert held.loc[NON_MERCHANDISE, "amount"] == pytest.approx(18.0 - 500.0)
    assert result.problem_rows == 0


def test_money_reconciles_to_the_file_to_the_penny(tmp_path):
    rows = [
        _line("1"),
        _line("2", quantity=5, unit_price=2.5),
        _line("C2", quantity=-5, unit_price=2.5),
        _line("3", "POST", 1, description="POSTAGE", unit_price=18.0),
        _line("4", unit_price=0.0, description="DAMAGED", quantity=-3),
    ]
    db, _ = _build(tmp_path, rows)
    source = sum(row["quantity"] * row["unit_price"] for row in rows)
    kept = kpi_summary(db, FilterSpec())["revenue"]
    set_aside = float(rejection_summary(db)["amount"].sum())
    assert kept + set_aside == pytest.approx(source)


def test_a_bad_row_is_set_aside_and_a_mostly_bad_file_is_refused():
    good = [_line(str(index)) for index in range(9)]
    few = clean_transactions(pd.DataFrame(good + [_line("9", unit_price=0.0)]), transaction_status="Verified")
    assert few.problem_rows == 1
    assert few.block_reasons() == []
    assert few.curated["data_valid"].sum() == 9
    assert few.rejected.iloc[0]["reject_reason"] == "unit_price/min_exclusive"
    many = clean_transactions(pd.DataFrame(good[:2] + [_line(str(i), unit_price=0.0) for i in range(20, 26)]), transaction_status="Verified")
    assert any("上限" in reason for reason in many.block_reasons())


def test_a_mistyped_future_date_cannot_stretch_the_reporting_window(tmp_path):
    db, _ = _build(tmp_path, [_line("1"), _line("2"), _line("3", invoice_date="2099-01-01")])
    assert date_bounds(db)[1] == "2025-03-14"
    assert rejection_summary(db).iloc[0]["reason"] == "invoice_date/not_future"


def test_short_codes_stay_products_unless_their_names_say_otherwise():
    codes = pd.Series(["C2", "DOT", "POST", "S"], dtype="string")
    names = pd.Series(["CANVAS TOTE", "POLKA NOTEBOOK", "SIGN POST", "SMALL MUG"], dtype="string")
    assert service_lines(codes, names).astype(bool).tolist() == [False] * 4


def test_missing_currency_rate_still_refuses_the_whole_file():
    result = clean_transactions(
        pd.DataFrame([_line("1", currency="USD")]), transaction_status="Verified", currency="GBP"
    )
    assert result.block_reasons()


def test_reasons_read_as_plain_words(tmp_path, monkeypatch):
    db, _ = _build(tmp_path, [_line("1"), _line("2", unit_price=-1.0)])
    monkeypatch.setitem(__import__("streamlit").session_state, "insightflow_language", "zh-CN")
    table = rejection_table(rejection_summary(db), "GBP")
    assert table.iloc[0, 0] == "单价为零或负数"


def test_a_clearance_discount_is_kept_as_sold(tmp_path):
    db, _ = _build(tmp_path, [_line("1", discount_rate=0.6)])
    assert kpi_summary(db, FilterSpec())["revenue"] == pytest.approx(6.0 * 0.4)


def test_concentration_counts_every_product_not_just_the_leaders():
    page = importlib.import_module("insightflow.pages.products")
    revenue = [1000.0, 1000.0] + [1.0] * 598
    count, share = page._head_share(pd.DataFrame({"revenue": revenue}))
    assert count == 120
    assert share == pytest.approx((2000 + 118) / (2000 + 598))


def test_warehouse_notes_never_become_product_names(tmp_path):
    rows = [_line(str(index), "23084", description="RABBIT NIGHT LIGHT") for index in range(5)]
    rows.append(_line("9", "23084", -7, description="WEBSITE FIXED", unit_price=0.0))
    rows.append(_line("10", "23084", 1, description="ZZZ OLD SPELLING"))
    db, _ = _build(tmp_path, rows)
    table = product_profitability(db, FilterSpec())
    assert table.iloc[0]["description"] == "RABBIT NIGHT LIGHT"


def test_stock_levels_and_suppliers_are_never_made_up(tmp_path):
    db, result = _build(tmp_path, [_line("1"), _line("2")])
    assert result.metadata["inventory_status"] == "Missing"
    assert result.curated["inventory_on_hand"].isna().all()
    assert set(result.curated["supplier"]) == {"Unknown"}
    snapshot = query_df(db, "SELECT inventory_on_hand, inventory_status FROM inventory_snapshot")
    assert snapshot.iloc[0]["inventory_on_hand"] is None
    assert snapshot.iloc[0]["inventory_status"] == "Unknown"
    issues, _ = generate_diagnostics(db, FilterSpec("2025-03-01", "2025-03-31"))
    assert "reorder_risk" not in {issue.code for issue in issues}
    assert inventory_policy(db)["recommended_order"].sum() == 0


def test_the_latest_stock_reading_wins_over_the_highest(tmp_path):
    rows = [
        _line("1", inventory_on_hand=500, invoice_date="2025-03-01"),
        _line("2", inventory_on_hand=20, invoice_date="2025-03-20"),
    ]
    db, _ = _build(tmp_path, rows)
    assert query_df(db, "SELECT inventory_on_hand FROM dim_product").iloc[0, 0] == 20


def test_an_order_placed_and_cancelled_creates_no_demand(tmp_path):
    rows = [
        _line("1", "23843", 80995, description="PAPER CRAFT", unit_price=2.08),
        _line("C1", "23843", -80995, description="PAPER CRAFT", unit_price=2.08),
        _line("2", "22197", 90, description="POPCORN HOLDER"),
    ]
    db, _ = _build(tmp_path, rows)
    policy = inventory_policy(db).set_index("stock_code")
    assert policy.loc["23843", "daily_demand"] == 0
    assert policy.loc["22197", "daily_demand"] == pytest.approx(1.0)
    assert query_df(db, "SELECT MAX(units_90d) FROM inventory_snapshot").iloc[0, 0] == 90


@pytest.mark.parametrize(
    ("raw", "canonical", "region"),
    [
        ("EIRE", "Ireland", "Europe"),
        ("RSA", "South Africa", "Africa"),
        ("USA", "United States", "North America"),
        ("Channel Islands", "Channel Islands", "Europe"),
        ("Czech Republic", "Czech Republic", "Europe"),
        ("Korea", "South Korea", "East Asia"),
        ("BR", "Brazil", "Latin America"),
        ("巴西", "Brazil", "Latin America"),
        ("Saudi Arabia", "Saudi Arabia", "Middle East"),
        ("Unspecified", "Unknown", "Other"),
    ],
)
def test_real_country_spellings_land_on_the_map(raw, canonical, region):
    assert canonical_country(raw) == canonical
    assert market_region(raw) == region
    assert (market_coordinates(raw) is not None) == (canonical != "Unknown")


def test_new_markets_have_labels_and_freight():
    assert country_label("Finland", "zh-CN") == "芬兰"
    assert region_label("Africa", "zh-CN") == "非洲"
    assert shipping_multiplier("Finland") == pytest.approx(1.45)
    assert shipping_multiplier("Atlantis") == pytest.approx(1.25)


def test_products_group_into_families_only_when_names_support_it():
    nouns = ["BAG", "BAGS", "HOLDER", "CARD", "BOX", "BOXES", "MUG", "SIGN"]
    names = pd.Series(
        [f"BRAND{index} RED {nouns[index % len(nouns)]}" for index in range(240)], dtype="string"
    )
    families = derive_categories(names)
    assert set(families) <= {"Bag", "Holder", "Card", "Box", "Mug", "Sign", "Other"}
    assert families.iloc[1] == "Bag"
    assert families.iloc[5] == "Box"
    assert derive_categories(pd.Series(["保温杯", "咖啡机"] * 80, dtype="string")) is None
    assert derive_categories(names.head(20)) is None


def test_a_ledger_without_categories_gets_labelled_families():
    nouns = ["BAG", "HOLDER", "CARD", "BOX", "MUG", "SIGN"]
    rows = [
        _line(str(index), f"SKU{index}", description=f"BRAND{index} {nouns[index % len(nouns)]}")
        for index in range(180)
    ]
    result = clean_transactions(pd.DataFrame(rows), transaction_status="Verified")
    assert result.metadata["category_source"] == "derived"
    assert "Uncategorized" not in set(result.curated["category"])
    supplied = clean_transactions(
        pd.DataFrame([{**row, "category": "Kitchen"} for row in rows]), transaction_status="Verified"
    )
    assert supplied.metadata["category_source"] == "source"
    assert set(supplied.curated["category"]) == {"Kitchen"}


def _two_price_lists() -> pd.DataFrame:
    """Each product sells on two fixed price lists; only the mix between them moves."""
    rows = []
    for product in range(4):
        for week in range(30):
            rows.append(("account", week, product, 20.0, 10.0))
            rows.append(("anonymous", week, product, 5.0 + 10 * ((week + product) % 3), 20.0))
    frame = pd.DataFrame(rows, columns=["stream", "week", "stock_code", "orders", "net_price"])
    return frame.astype({"week": str, "stock_code": str})


def test_separate_price_lists_do_not_pass_for_a_price_change():
    frame = _two_price_lists()
    assert _poisson_slope(frame) is None
    pooled = (
        frame.assign(paid=frame["orders"] * frame["net_price"])
        .groupby(["stock_code", "week"], as_index=False)[["orders", "paid"]]
        .sum()
    )
    pooled["net_price"] = pooled["paid"] / pooled["orders"]
    pooled["stream"] = "all"
    fitted = _poisson_slope(pooled)
    assert fitted is not None
    assert fitted[0] > 0.5


def test_a_single_product_still_reports_an_error():
    rows = []
    for week in range(40):
        rows.append(("web", str(week), "only", 30.0 - 2 * (week % 4) + (week % 5), 10.0 + week % 4))
        rows.append(("store", str(week), "only", 20.0 + (week % 3), 10.0))
    frame = pd.DataFrame(rows, columns=["stream", "week", "stock_code", "orders", "net_price"])
    fitted = _poisson_slope(frame)
    assert fitted is not None
    assert fitted[0] < 0
    assert fitted[1] > 0.01


def _quiet_promotions(seed: int) -> pd.DataFrame:
    """Sparse streams on different price lists, with promotions moving every stream at once."""
    rng = np.random.default_rng(seed)
    rows = []
    for product in range(24):
        for week in range(80):
            index = 0.8 if (week + product) % 6 == 0 else 1.0
            for stream, base, premium in (("web", 1.4, 1.0), ("store", 1.0, 1.15), ("phone", 0.7, 1.3)):
                orders = rng.poisson(base * index**-1.5)
                if orders:
                    rows.append((stream, str(week), str(product), float(orders), 10.0 * premium * index))
    return pd.DataFrame(rows, columns=["stream", "week", "stock_code", "orders", "net_price"])


@pytest.mark.parametrize("seed", [7, 11, 23])
def test_quiet_promotion_weeks_do_not_bend_the_estimate(seed):
    beta, error = _poisson_slope(_quiet_promotions(seed))
    assert beta == pytest.approx(-1.5, abs=0.3)
    assert abs(beta + 1.5) <= 1.96 * error + 0.05


def test_estimates_report_their_uncertainty(demo_warehouse):
    table = estimate_elasticities(demo_warehouse, FilterSpec())
    assert (table["posterior_sd"] > 0).all()
    assert (table["posterior_sd"] <= 0.5 + 1e-9).all()
    measured = table[table["basis"] == "data"]
    assert (measured["posterior_sd"] <= measured["standard_error"] + 1e-9).all()


def test_every_price_move_carries_its_profit_range(demo_warehouse, last_quarter):
    moves = category_price_moves(demo_warehouse, last_quarter)
    assert (moves["profit_change_low"] <= moves["expected_profit_change"] + 1e-6).all()
    assert (moves["profit_change_high"] >= moves["expected_profit_change"] - 1e-6).all()
    assert (moves["robust"] == (moves["profit_change_low"] > 0)).all()


def test_a_price_rise_loses_more_when_demand_is_more_elastic():
    calm = _margin_change(100.0, 10.0, 6.0, 0.10, -0.5)
    steep = _margin_change(100.0, 10.0, 6.0, 0.10, -6.0)
    assert calm > 0 > steep
    assert _margin_change(100.0, 10.0, 6.0, 0.0, -2.0) == pytest.approx(0.0)


def test_live_scores_use_the_newest_labels(demo_warehouse):
    model = train_churn_model(demo_warehouse)
    scores = score_customers(demo_warehouse)
    assert model is not None
    assert model.coefficients.shape[0] == 6
    assert scores["return_probability"].between(0, 1).all()


def test_a_month_in_progress_is_judged_on_the_days_elapsed(tmp_path):
    rows = []
    for month in range(1, 8):
        for day in (5, 15, 28):
            rows.append(
                _line(f"{month}{day}", invoice_date=f"2025-{month:02d}-{day:02d}", unit_price=100.0)
            )
    rows.append(_line("last", invoice_date="2025-08-15", unit_price=100.0))
    db, _ = _build(tmp_path, rows)
    assert partial_month(db) == "2025-08"
    target = target_status(db, "2025-08").set_index("metric_id")
    full_month = 600.0 * 1.05
    assert target.loc["net_revenue", "target_value"] == pytest.approx(full_month * 15 / 31)
    assert "2025-08" not in set(monthly_anomalies(db).get("month", pd.Series(dtype=str)))


def test_targets_follow_the_business_rather_than_fixed_numbers(tmp_path):
    rows = [
        _line(f"{month}{day}", invoice_date=f"2025-{month:02d}-{day:02d}")
        for month in range(1, 7)
        for day in (5, 15, 28)
    ]
    rows += [
        _line(f"C{month}", quantity=-1, invoice_date=f"2025-{month:02d}-20")
        for month in range(1, 7)
    ]
    db, _ = _build(tmp_path, rows)
    target = target_status(db, "2025-06").set_index("metric_id")
    assert target.loc["cancellation_rate", "target_value"] == pytest.approx(1 / 3 * 0.95)


def test_estimated_costs_do_not_raise_margin_alarms(tmp_path):
    rows = [
        _line(f"{day}", invoice_date=f"2025-03-{day:02d}", unit_price=3.0) for day in range(1, 29)
    ]
    rows += [
        _line(f"P{day}", invoice_date=f"2025-02-{day:02d}", unit_price=9.0) for day in range(1, 29)
    ]
    db, _ = _build(tmp_path, rows)
    issues, _ = generate_diagnostics(db, FilterSpec("2025-03-01", "2025-03-28"), language="en")
    by_code = {issue.code: issue for issue in issues}
    assert "margin_floor" not in by_code
    assert by_code["profit_pressure"].severity == "P2"
    assert "rule-based" in by_code["profit_pressure"].evidence


def test_a_period_can_be_read_against_last_year():
    filters = FilterSpec("2025-03-01", "2025-05-31", regions=("Europe",), compare="year")
    base = previous_period(filters)
    assert (base.start_date, base.end_date) == ("2024-03-01", "2024-05-31")
    assert base.regions == ("Europe",)
    assert base.compare == "year"
    plain = previous_period(FilterSpec("2025-03-01", "2025-03-31"))
    assert (plain.start_date, plain.end_date) == ("2025-01-29", "2025-02-28")


def test_year_over_year_reads_through_the_diagnosis(demo_warehouse, last_quarter):
    from dataclasses import replace

    issues, _ = generate_diagnostics(demo_warehouse, replace(last_quarter, compare="year"), language="en")
    moved = [issue for issue in issues if issue.code in {"revenue_drop", "revenue_growth"}]
    assert all("last year" in issue.finding for issue in moved)


def test_leak_drivers_explain_the_whole_outflow(demo_warehouse, last_quarter):
    kpi = kpi_summary(demo_warehouse, last_quarter)
    frame = leak_drivers(demo_warehouse, last_quarter, "marketing_cost", "category", limit=100)
    assert frame["amount"].sum() == pytest.approx(kpi["marketing_cost"], abs=1.0)
    assert frame["amount"].is_monotonic_decreasing
    assert frame["share"].sum() == pytest.approx(1.0, abs=1e-6)
    with pytest.raises(ValueError):
        leak_drivers(demo_warehouse, last_quarter, "drop table", "category")
    with pytest.raises(ValueError):
        leak_drivers(demo_warehouse, last_quarter, "cogs", "1=1; --")


def test_the_river_leaves_out_an_outflow_that_never_happened():
    from insightflow.narrative import river_payload

    current = {key: 10.0 for key, *_ in LEAK_LABELS}
    current.update(gross_revenue=1000.0, contribution_profit=500.0, contribution_margin=0.5, discount_amount=0.0)
    previous = dict(current, marketing_cost=0.0)
    current["marketing_cost"] = 0.0
    keys = [leak["key"] for leak in river_payload(current, previous, "GBP")["leaks"]]
    assert "discount_amount" not in keys and "marketing_cost" not in keys
    ended = river_payload(current, dict(previous, discount_amount=30.0), "GBP")["leaks"]
    assert "discount_amount" in [leak["key"] for leak in ended]


def test_customer_analysis_states_what_it_covers(tmp_path):
    db, _ = _build(tmp_path, [_line("1"), _line("2", customer_id=None), _line("3", customer_id=None)])
    assert customer_coverage(db, FilterSpec()) == pytest.approx(1 / 3)


def test_viewing_actions_again_writes_nothing(demo_warehouse, last_quarter, tmp_path):
    import shutil

    from insightflow.action_center import sync_action_register
    from insightflow.warehouse import database_version

    db = tmp_path / "actions.db"
    shutil.copy(demo_warehouse, db)
    first = sync_action_register(db, last_quarter, persist=True)
    version = database_version(db)
    again = sync_action_register(db, last_quarter, persist=True)
    assert database_version(db) == version
    assert list(again["issue_fingerprint"]) == list(first["issue_fingerprint"])


def test_replacing_the_demo_takes_its_samples_with_it(demo_warehouse, tmp_path):
    import shutil

    from insightflow.action_center import sync_action_register
    from insightflow.experiments import experiment_catalog, import_experiment

    db = tmp_path / "replace.db"
    shutil.copy(demo_warehouse, db)
    sync_action_register(db, FilterSpec("2025-10-03", "2025-12-31"), persist=True)
    real = pd.DataFrame(
        {
            "experiment_id": "EXP_REAL",
            "customer_id": [str(index) for index in range(40)],
            "assignment": ["Control", "Treatment"] * 20,
            "converted": 1,
            "net_revenue": 100.0,
            "contribution_profit": 20.0,
            "returned": 0,
        }
    )
    import_experiment(db, real, "Real test")
    assert len(experiment_catalog(db)) > 1
    build_warehouse(clean_transactions(pd.DataFrame([_line("1")]), transaction_status="Verified"), db)
    assert set(experiment_catalog(db)["experiment_id"]) == {"EXP_REAL"}
    assert query_df(db, "SELECT COUNT(*) FROM action_register").iloc[0, 0] == 0


def test_backups_rotate_and_restore(tmp_path):
    db, _ = _build(tmp_path, [_line("1")])
    first = create_backup(db)
    assert first is not None
    build_warehouse(
        clean_transactions(pd.DataFrame([_line("2"), _line("3")]), transaction_status="Verified"),
        db,
    )
    assert len(query_df(db, "SELECT * FROM v_ledger")) == 2
    restore_backup(first.name, db)
    assert len(query_df(db, "SELECT * FROM v_ledger")) == 1
    assert len(list_backups(db)) == 2
    for _ in range(KEEP_BACKUPS + 2):
        create_backup(db)
    assert len(list_backups(db)) == KEEP_BACKUPS


def test_restore_only_accepts_listed_backups(tmp_path):
    db, _ = _build(tmp_path, [_line("1")])
    create_backup(db)
    with pytest.raises(ValueError):
        restore_backup("../ledger.db", db)
    assert create_backup(tmp_path / "absent.db") is None


APP_SCRIPT = """
import streamlit as st
from insightflow.ui import apply_design_system, require_access, sidebar_filters
from insightflow.config import DEFAULT_DB_PATH
require_access()
filters = sidebar_filters(DEFAULT_DB_PATH)
st.write(str(filters.start_date), str(filters.end_date), filters.compare, filters.regions)
"""


def test_the_access_code_gate(monkeypatch, page_warehouse):
    monkeypatch.setenv("INSIGHTFLOW_ACCESS_CODE", "test-gate")
    app = AppTest.from_string(APP_SCRIPT, default_timeout=60).run()
    assert not app.exception
    assert len(app.markdown) == 0
    app.text_input[0].set_value("wrong")
    app.button[0].click().run()
    assert app.error
    app.text_input[0].set_value("test-gate")
    app.button[0].click().run()
    assert not app.exception
    assert any("previous" in item.value for item in app.markdown)


def test_no_code_means_no_gate(monkeypatch, page_warehouse):
    monkeypatch.delenv("INSIGHTFLOW_ACCESS_CODE", raising=False)
    app = AppTest.from_string(APP_SCRIPT, default_timeout=60).run()
    assert not app.exception
    assert not app.text_input


def test_a_shared_link_reopens_the_view(monkeypatch, page_warehouse):
    monkeypatch.delenv("INSIGHTFLOW_ACCESS_CODE", raising=False)
    app = AppTest.from_string(APP_SCRIPT, default_timeout=60)
    app.query_params["compare"] = "year"
    app.query_params["region"] = ["Europe", "Nowhere"]
    app.query_params["from"] = "2025-01-01"
    app.query_params["to"] = "2025-02-01"
    app.run()
    assert not app.exception
    shown = app.markdown[-1].value
    assert "2025-01-01" in shown and "2025-02-01" in shown
    assert "year" in shown
    assert "Europe" in shown and "Nowhere" not in shown


def test_a_half_picked_date_range_does_not_break_the_page(monkeypatch, page_warehouse):
    monkeypatch.delenv("INSIGHTFLOW_ACCESS_CODE", raising=False)
    app = AppTest.from_string(APP_SCRIPT, default_timeout=60).run()
    assert not app.exception
    app.date_input[0].set_value((date(2025, 3, 1),)).run()
    assert not app.exception
    assert "2025-03-01 2025-03-01" in app.markdown[-1].value.replace("  ", " ")


def test_a_bad_link_falls_back_to_defaults(monkeypatch, page_warehouse):
    monkeypatch.delenv("INSIGHTFLOW_ACCESS_CODE", raising=False)
    app = AppTest.from_string(APP_SCRIPT, default_timeout=60)
    app.query_params["from"] = "not-a-date"
    app.query_params["to"] = "1900-01-01"
    app.query_params["compare"] = "sometime"
    app.run()
    assert not app.exception
    assert "previous" in app.markdown[-1].value


@pytest.fixture(scope="module")
def bare_ledger(tmp_path_factory):
    """A ledger as it usually arrives: no costs, no stock, no categories, some anonymous orders."""
    nouns = ["BAG", "HOLDER", "CARD", "BOX", "MUG", "SIGN", "CANDLE", "PLATE"]
    rows = []
    for index in range(2600):
        day = pd.Timestamp("2024-01-03") + pd.Timedelta(days=index % 640)
        product = index % 160
        rows.append(
            _line(
                str(index),
                f"SKU{product}",
                1 + index % 4,
                description=f"BRAND{product} {nouns[product % len(nouns)]}",
                invoice_date=day.isoformat(),
                unit_price=4.0 + product % 9 + (index % 5) * 0.1,
                customer_id=None if index % 6 == 0 else f"C{index % 140}",
                country=("EIRE", "United Kingdom", "RSA", "USA")[index % 4],
            )
        )
    rows.append(_line("POST1", "POST", 1, description="POSTAGE", unit_price=18.0, invoice_date="2025-02-01"))
    rows.append(_line("BAD1", "SKU1", 1, unit_price=0.0, invoice_date="2025-02-01"))
    db = tmp_path_factory.mktemp("bare") / "bare.db"
    result = clean_transactions(pd.DataFrame(rows), source_profile="manual_import", transaction_status="Verified")
    assert result.metadata["category_source"] == "derived"
    build_warehouse(result, db)
    return db


def test_a_ledger_without_discounts_has_none_to_cut(bare_ledger):
    filters = FilterSpec("2025-01-01", "2025-09-30")
    plain = simulate_scenario(bare_ledger, filters, ScenarioInputs())
    cut = simulate_scenario(bare_ledger, filters, ScenarioInputs(discount_change_pp=-3.0))
    assert cut["contribution_profit"] == pytest.approx(plain["contribution_profit"])
    plans = search_plans(bare_ledger, filters, uncertainty=UncertaintyInputs(simulations=500))
    assert plans["discount_change_pp"].min() == 0
    assert len(plans) == 7 * 4 * 5


@pytest.mark.parametrize(
    "name",
    [
        "overview",
        "markets",
        "sales",
        "profit",
        "customers",
        "products",
        "inventory",
        "diagnostics",
        "planning",
        "pricing",
        "decision_lab",
        "experiments",
        "actions",
        "assistant",
        "data_hub",
        "quality",
        "report",
    ],
)
def test_every_page_handles_a_bare_ledger(name, bare_ledger, page_warehouse, monkeypatch):
    page = importlib.import_module(f"insightflow.pages.{name}")
    monkeypatch.setattr(page, "DEFAULT_DB_PATH", bare_ledger)
    script = f"from insightflow.pages import {name}\n{name}.render()\n"
    app = AppTest.from_string(script, default_timeout=120).run()
    assert not app.exception, [str(item.value) for item in app.exception]


def test_inventory_says_stock_is_unknown(bare_ledger, page_warehouse, monkeypatch):
    page = importlib.import_module("insightflow.pages.inventory")
    monkeypatch.setattr(page, "DEFAULT_DB_PATH", bare_ledger)
    app = AppTest.from_string(
        "from insightflow.pages import inventory\ninventory.render()\n", default_timeout=120
    ).run()
    assert not app.exception
    assert not app.slider
    assert not app.dataframe


def test_the_assistant_declines_to_guess_stock(bare_ledger):
    from insightflow.query_assistant import answer_business_question

    answer = answer_business_question(bare_ledger, FilterSpec("2025-01-01", "2025-09-30"), "哪些商品需要补货？")
    assert "没有库存字段" in answer.answer
    assert answer.data.empty


def test_quality_lists_what_was_held_back(bare_ledger, page_warehouse, monkeypatch):
    page = importlib.import_module("insightflow.pages.quality")
    monkeypatch.setattr(page, "DEFAULT_DB_PATH", bare_ledger)
    app = AppTest.from_string(
        "from insightflow.pages import quality\nquality.render()\n", default_timeout=120
    ).run()
    assert not app.exception
    tables = [item.value for item in app.dataframe]
    held = next(table for table in tables if "原因" in table.columns)
    assert set(held["原因"]) == {"运费、手续费、调整等非商品行", "单价为零或负数"}
