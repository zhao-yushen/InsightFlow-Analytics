"""Regressions for defects measured against the v1 codebase."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from insightflow.action_center import sync_action_register
from insightflow.ai_assistant import deterministic_executive_summary, executive_summary
from insightflow.currency import money, warehouse_currency
from insightflow.data_contracts import blocking_contract_issues
from insightflow.decision_lab import (
    ScenarioInputs,
    UncertaintyInputs,
    _weighted_elasticity,
    monte_carlo_scenario,
    simulate_scenario,
)
from insightflow.diagnostics import generate_diagnostics, profit_driver_decomposition
from insightflow.etl import clean_transactions
from insightflow.experiments import (
    analyze_experiment,
    experiment_catalog,
    import_experiment,
    minimum_detectable_lift,
    sample_ratio_p_value,
)
from insightflow.metrics import (
    FilterSpec,
    cost_waterfall,
    kpi_summary,
    monthly_trend,
    previous_period,
    quality_score,
)
from insightflow.pvm import price_volume_mix
from insightflow.query_assistant import answer_business_question
from insightflow.warehouse import build_warehouse, query_df


def _line(invoice: str, quantity: float = 2, **overrides) -> dict:
    return {
        "invoice_no": invoice,
        "stock_code": "SKU-1",
        "description": "Item",
        "category": "Kitchen",
        "quantity": quantity,
        "invoice_date": "2025-03-01 10:00:00",
        "unit_price": 30.0,
        "customer_id": f"C-{invoice}",
        "country": "United Kingdom",
        "channel": "Web",
        **overrides,
    }


def _full_economics(invoice: str, **overrides) -> dict:
    return _line(
        invoice,
        discount_rate=0.05,
        unit_cost=12.0,
        shipping_cost=2.0,
        payment_fee=0.5,
        marketing_cost=1.0,
        return_processing_cost=0.0,
        price_elasticity=-1.2,
        supplier="S",
        supplier_lead_days=10,
        inventory_on_hand=100,
        reorder_point=20,
        **overrides,
    )


def _copy(source: Path, tmp_path: Path) -> Path:
    target = tmp_path / "copy.db"
    shutil.copy(source, target)
    return target


def test_appending_clean_rows_cannot_relabel_a_simulated_warehouse(demo_warehouse, tmp_path):
    db = _copy(demo_warehouse, tmp_path)
    before_rows = float(
        query_df(db, "SELECT value FROM data_quality_summary WHERE metric='raw_rows'").iloc[0, 0]
    )
    before_score = quality_score(db)
    upload = clean_transactions(
        pd.DataFrame([_full_economics(f"NEW-{i}") for i in range(5)]),
        source_profile="web_incremental_import",
        transaction_status="Verified",
    )
    build_warehouse(upload, db, load_mode="append", source_name="five.csv")
    catalog = query_df(db, "SELECT metric_id, data_status, confidence FROM metric_catalog")
    assert set(catalog["data_status"]) == {"Mixed"}
    assert catalog["confidence"].max() < 0.6
    after_rows = float(
        query_df(db, "SELECT value FROM data_quality_summary WHERE metric='raw_rows'").iloc[0, 0]
    )
    assert after_rows == before_rows + 5
    assert quality_score(db) == pytest.approx(before_score, abs=0.5)


def test_a_ledger_without_discounts_reconciles_to_its_source(tmp_path):
    frame = pd.DataFrame([_line(str(i)) for i in range(20)])
    result = clean_transactions(frame, source_profile="uci_online_retail")
    db = tmp_path / "uci.db"
    build_warehouse(result, db)
    kpi = kpi_summary(db, FilterSpec())
    assert kpi["revenue"] == pytest.approx((frame["quantity"] * frame["unit_price"]).sum())
    assert kpi["discount_amount"] == 0
    status = query_df(db, "SELECT data_status, confidence FROM metric_catalog WHERE metric_id='net_revenue'")
    assert status.iloc[0]["data_status"] == "Verified"
    profit = query_df(db, "SELECT data_status FROM metric_catalog WHERE metric_id='gross_profit'")
    assert profit.iloc[0]["data_status"] == "Estimated"


def test_contract_sees_values_before_they_are_clipped():
    frame = pd.DataFrame([_line("1", discount_rate=0.95), _line("2", unit_cost=-5.0)])
    result = clean_transactions(frame, transaction_status="Verified")
    rules = set(zip(result.contract_issues["rule_id"], result.contract_issues["column"], strict=True))
    assert ("max_value", "discount_rate") in rules
    assert ("min_exclusive", "unit_cost") in rules
    assert not blocking_contract_issues(result.contract_issues).empty


def test_a_return_nets_the_sale_to_zero_and_adds_its_handling_cost(tmp_path):
    frame = pd.DataFrame(
        [
            _line("100", 2, unit_cost=10.0, discount_rate=0.0, shipping_cost=3.0, payment_fee=1.0, marketing_cost=2.0),
            _line(
                "C100",
                -2,
                invoice_date="2025-03-04",
                unit_cost=10.0,
                discount_rate=0.0,
                shipping_cost=0.0,
                payment_fee=0.0,
                marketing_cost=0.0,
                return_processing_cost=4.0,
            ),
        ]
    )
    db = tmp_path / "returns.db"
    build_warehouse(clean_transactions(frame, transaction_status="Verified"), db)
    kpi = kpi_summary(db, FilterSpec("2025-03-01", "2025-03-31"))
    assert kpi["gross_revenue"] == 60
    assert kpi["returns_value"] == 60
    assert kpi["revenue"] == 0
    assert kpi["cogs"] == 0
    # Shipping, payment and marketing stay spent; handling is added on top.
    assert kpi["contribution_profit"] == pytest.approx(-10.0)
    assert kpi["orders"] == 1
    assert kpi["cancellation_rate"] == 1.0
    waterfall = cost_waterfall(db, FilterSpec("2025-03-01", "2025-03-31"))
    assert waterfall["value"].iloc[:-1].sum() == pytest.approx(kpi["contribution_profit"])


def test_derived_costs_are_not_charged_a_second_time_on_reversals():
    frame = pd.DataFrame([_line("100", 2), _line("C100", -2)])
    curated = clean_transactions(frame, transaction_status="Verified").curated
    reversal = curated.loc[curated["is_cancellation"]].iloc[0]
    assert reversal["shipping_cost"] == 0
    assert reversal["payment_fee"] == 0
    assert reversal["marketing_cost"] == 0
    assert reversal["return_processing_cost"] > 0


def test_order_numbers_starting_with_c_are_ordinary_sales():
    frame = pd.DataFrame([_line("CN-2025-001"), _line("C9000")])
    curated = clean_transactions(frame, transaction_status="Verified").curated
    assert not curated["is_cancellation"].any()
    assert curated["sale_valid"].all()


def test_numeric_customer_ids_lose_the_float_suffix():
    frame = pd.DataFrame([_line("1", customer_id=17850.0), _line("2", customer_id=None)])
    curated = clean_transactions(frame, transaction_status="Verified").curated
    assert curated["customer_id"].iloc[0] == "17850"
    assert pd.isna(curated["customer_id"].iloc[1])


def test_profit_bridge_reconciles_with_return_handling(demo_warehouse, last_quarter):
    current = kpi_summary(demo_warehouse, last_quarter)
    previous = kpi_summary(demo_warehouse, previous_period(last_quarter))
    bridge = profit_driver_decomposition(current, previous)
    expected = current["contribution_profit"] - previous["contribution_profit"]
    assert bridge["profit_contribution"].sum() == pytest.approx(expected, abs=0.01)


def test_actions_keep_one_identity_across_date_windows(demo_warehouse, tmp_path, last_quarter):
    db = _copy(demo_warehouse, tmp_path)
    first = sync_action_register(db, last_quarter, persist=True, include_inactive=True)
    again = sync_action_register(db, last_quarter, persist=True, include_inactive=True)
    assert len(first) == len(again)
    wider = FilterSpec("2025-09-01", "2025-12-31")
    sync_action_register(db, wider, persist=True)
    titles = query_df(
        db,
        """
        SELECT issue, COUNT(*) copies FROM action_register
        WHERE source='diagnostic_engine' GROUP BY issue HAVING copies > 1
        """,
    )
    assert titles.empty


def test_switching_language_updates_the_same_actions(demo_warehouse, tmp_path, last_quarter):
    db = _copy(demo_warehouse, tmp_path)
    chinese = sync_action_register(db, last_quarter, persist=True, include_inactive=True)
    english = sync_action_register(
        db, last_quarter, persist=True, include_inactive=True, language="en"
    )
    assert len(english) == len(chinese)
    assert set(english["action_id"]) == set(chinese["action_id"])
    assert not english["issue"].str.contains(r"[一-鿿]").any()


def test_english_analysis_text_contains_no_chinese(demo_warehouse, last_quarter):
    issues, drivers = generate_diagnostics(demo_warehouse, last_quarter, language="en")
    text = " ".join(
        f"{i.category} {i.title} {i.finding} {i.evidence} {i.recommendation}" for i in issues
    )
    assert issues
    assert not re.search(r"[一-鿿]", text)
    assert not drivers["driver"].str.contains(r"[一-鿿]").any()
    summary, engine = executive_summary(issues, "en")
    assert not re.search(r"[一-鿿]", summary + engine)
    bridge = price_volume_mix(demo_warehouse, last_quarter, language="en")
    assert not bridge["label"].str.contains(r"[一-鿿]").any()


def test_alert_evidence_states_its_currency(demo_warehouse, last_quarter):
    issues, _ = generate_diagnostics(demo_warehouse, last_quarter)
    money_lines = [i.evidence for i in issues if i.code in {"revenue_growth", "revenue_drop"}]
    assert money_lines
    assert all("£" in line for line in money_lines)


def test_summary_handles_a_scope_with_no_findings():
    assert deterministic_executive_summary([], "en").startswith("The sample")
    assert "样本" in deterministic_executive_summary([])


def test_stale_untouched_actions_leave_the_default_view(demo_warehouse, tmp_path, last_quarter):
    db = _copy(demo_warehouse, tmp_path)
    sync_action_register(db, last_quarter, persist=True)
    narrow = FilterSpec(last_quarter.start_date, last_quarter.end_date, channels=("Web",))
    shown = sync_action_register(db, narrow, persist=True)
    assert shown["is_active"].astype(bool).all()


def test_region_filter_reaches_the_elasticity_query(tmp_path):
    frame = pd.DataFrame(
        [
            _line("1", country="China", price_elasticity=-1.0),
            _line("2", country="United Kingdom", price_elasticity=-2.0),
        ]
    )
    db = tmp_path / "regions.db"
    build_warehouse(clean_transactions(frame, transaction_status="Verified"), db)
    scope = FilterSpec("2025-03-01", "2025-03-31", regions=("Greater China",))
    assert _weighted_elasticity(db, scope) == pytest.approx(-1.0)


def test_concentration_alert_follows_the_filter(demo_warehouse, last_quarter):
    narrow = FilterSpec(
        last_quarter.start_date, last_quarter.end_date, categories=("Electronics",)
    )
    titles = [issue.title for issue in generate_diagnostics(demo_warehouse, narrow)[0]]
    # Few products in scope makes "top ten" meaningless, so the alert must stay silent.
    assert "收入对头部商品依赖较高" not in titles


def test_monthly_trend_carries_the_cancellation_rate(demo_warehouse):
    trend = monthly_trend(demo_warehouse, FilterSpec())
    assert "cancellation_rate" in trend.columns
    assert trend["cancellation_rate"].notna().all()
    assert (trend["cancellation_rate"] > 0).any()


@pytest.mark.parametrize("question", ["今天天气怎么样？", "公司有多少员工？", "what is the meaning of life"])
def test_assistant_declines_questions_it_cannot_ground(demo_warehouse, last_quarter, question):
    answer = answer_business_question(demo_warehouse, last_quarter, question)
    assert answer.supported is False
    assert answer.query_id == "unsupported"
    assert answer.data.empty
    assert answer.suggestions


def test_assistant_routes_a_returns_question_to_returns(demo_warehouse, last_quarter):
    answer = answer_business_question(demo_warehouse, last_quarter, "哪个渠道的退货最多？")
    assert answer.query_id == "returns_by_dimension_v1"
    assert "channel" in answer.data.columns
    assert answer.data["returns_value"].is_monotonic_decreasing


@pytest.mark.parametrize(
    ("question", "query_id"),
    [
        ("未来三个月收入预测是多少？", "forecast_v2"),
        ("哪些品类应该调价？", "price_moves_v1"),
        ("哪些商品适合搭配销售？", "bundles_v1"),
        ("为什么收入变化了？", "revenue_driver_v1"),
        ("哪些国家对销售变化影响最大？", "country_driver_v2"),
        ("Which channel has the most returns?", "returns_by_dimension_v1"),
    ],
)
def test_assistant_covers_each_advertised_question(demo_warehouse, last_quarter, question, query_id):
    answer = answer_business_question(demo_warehouse, last_quarter, question)
    assert answer.query_id == query_id
    assert not answer.data.empty


def test_experiments_reach_three_different_conclusions(demo_warehouse):
    outcomes = {
        row: analyze_experiment(demo_warehouse, row)[0].decision_code
        for row in experiment_catalog(demo_warehouse)["experiment_id"]
    }
    assert outcomes["EXP_BLANKET_DISCOUNT_01"] == "stop"
    assert outcomes["EXP_WINBACK_EMAIL_01"] == "inconclusive"
    assert outcomes["EXP_FREE_SHIPPING_01"] in {"ship", "pilot", "inconclusive"}


def test_a_small_negative_estimate_is_not_called_harm(tmp_path):
    db = tmp_path / "experiment.db"
    build_warehouse(
        clean_transactions(pd.DataFrame([_line("1")]), transaction_status="Verified"), db
    )
    profit = np.random.default_rng(5).normal(20, 10, 200)
    rows = [
        {
            "experiment_id": "EXP_NOISE",
            "customer_id": f"{arm}-{index}",
            "assignment": arm,
            "converted": 1,
            "net_revenue": 100,
            "contribution_profit": value - shift,
            "returned": 0,
        }
        for arm, shift in (("Control", 0.0), ("Treatment", 0.3))
        for index, value in enumerate(profit)
    ]
    import_experiment(db, pd.DataFrame(rows), "Noise check")
    summary, _, _ = analyze_experiment(db, "EXP_NOISE")
    assert summary.lift < 0
    assert summary.decision_code == "inconclusive"
    assert summary.data_status == "Verified"
    assert summary.minimum_detectable_lift > abs(summary.lift)


def test_real_warehouses_get_no_invented_experiments(tmp_path):
    db = tmp_path / "real.db"
    build_warehouse(
        clean_transactions(pd.DataFrame([_line("1")]), transaction_status="Verified"), db
    )
    assert experiment_catalog(db).empty


def test_sample_ratio_check_flags_a_broken_split():
    assert sample_ratio_p_value(500, 500) == pytest.approx(1.0)
    assert sample_ratio_p_value(620, 380) < 0.001
    assert minimum_detectable_lift(pd.Series([1.0]).to_numpy(), pd.Series([1.0]).to_numpy()) == 0.0


def test_public_datasets_report_their_own_currency(tmp_path):
    db = tmp_path / "olist.db"
    build_warehouse(
        clean_transactions(pd.DataFrame([_line("1")]), source_profile="olist_public"), db
    )
    assert warehouse_currency(db) == "BRL"
    units = query_df(db, "SELECT unit FROM metric_catalog WHERE metric_id='net_revenue'")
    assert units.iloc[0, 0] == "BRL"
    assert money(1234.5, "BRL") == "R$1,234"


def test_a_second_currency_cannot_be_added_silently(tmp_path):
    db = tmp_path / "gbp.db"
    build_warehouse(clean_transactions(pd.DataFrame([_line("1")]), currency="GBP"), db)
    other = clean_transactions(pd.DataFrame([_line("2")]), currency="BRL")
    with pytest.raises(ValueError, match="币种"):
        build_warehouse(other, db, load_mode="append")


def test_foreign_amounts_convert_or_are_refused():
    frame = pd.DataFrame([_line("1", currency="USD"), _line("2", currency="GBP")])
    converted = clean_transactions(frame, currency="GBP", fx_rates={"USD": 0.8}).curated
    assert converted.set_index("invoice_no").loc["1", "unit_price"] == pytest.approx(24.0)
    refused = clean_transactions(frame, currency="GBP")
    assert "fx_rate_missing" in set(refused.contract_issues["rule_id"])
    assert not blocking_contract_issues(refused.contract_issues).empty


def test_point_estimate_and_simulation_share_one_formula(demo_warehouse, last_quarter):
    scenario = ScenarioInputs(name="s", price_change_pct=3, discount_change_pp=-1)
    point = simulate_scenario(demo_warehouse, last_quarter, scenario)
    silent = UncertaintyInputs(
        elasticity_sd=1e-9,
        marketing_response_sd=1e-9,
        baseline_demand_sd=1e-9,
        cost_shock_sd=1e-9,
        shipping_shock_sd=1e-9,
        simulations=600,
    )
    summary, _, _ = monte_carlo_scenario(demo_warehouse, last_quarter, scenario, silent)
    assert summary.iloc[0]["median_profit_change"] == pytest.approx(
        point["contribution_profit_change"], rel=1e-5
    )


def test_baseline_scenario_reproduces_results_with_returns(demo_warehouse, last_quarter):
    current = kpi_summary(demo_warehouse, last_quarter)
    baseline = simulate_scenario(demo_warehouse, last_quarter, ScenarioInputs(name="Baseline"))
    assert baseline["revenue"] == pytest.approx(current["revenue"], abs=0.01)
    assert baseline["contribution_profit"] == pytest.approx(current["contribution_profit"], abs=0.01)
