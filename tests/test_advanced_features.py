import math
from pathlib import Path

from insightflow.decision_lab import ScenarioInputs, simulate_scenario
from insightflow.demo_data import DemoConfig, generate_demo_transactions
from insightflow.diagnostics import profit_driver_decomposition
from insightflow.etl import clean_transactions
from insightflow.forecasting import forecast_metric
from insightflow.metrics import (
    FilterSpec,
    inventory_kpis,
    kpi_summary,
    previous_period,
    quality_score,
    target_status,
)
from insightflow.query_assistant import answer_business_question
from insightflow.warehouse import build_warehouse, query_df


def _build(tmp_path: Path) -> tuple[Path, FilterSpec]:
    db = tmp_path / "advanced.db"
    df = generate_demo_transactions(
        DemoConfig(
            start="2024-01-01",
            end="2025-12-31",
            base_daily_orders=5,
            n_customers=100,
            n_products=25,
            min_daily_orders=3,
        )
    )
    result = clean_transactions(df)
    build_warehouse(result, db)
    return db, FilterSpec("2025-10-01", "2025-12-31")


def test_unit_economics_reconcile(tmp_path: Path):
    db, filters = _build(tmp_path)
    kpi = kpi_summary(db, filters)
    assert math.isclose(kpi["revenue"], kpi["gross_revenue"] - kpi["discount_amount"], abs_tol=0.1)
    assert math.isclose(kpi["gross_profit"], kpi["revenue"] - kpi["cogs"], abs_tol=0.1)
    expected = (
        kpi["gross_profit"] - kpi["shipping_cost"] - kpi["payment_fee"] - kpi["marketing_cost"]
    )
    assert math.isclose(kpi["contribution_profit"], expected, abs_tol=0.1)


def test_profit_bridge_and_baseline_scenario_reconcile(tmp_path: Path):
    db, filters = _build(tmp_path)
    current = kpi_summary(db, filters)
    previous = kpi_summary(db, previous_period(filters))
    bridge = profit_driver_decomposition(current, previous)
    expected_change = current["contribution_profit"] - previous["contribution_profit"]
    assert math.isclose(bridge["profit_contribution"].sum(), expected_change, abs_tol=0.2)
    baseline = simulate_scenario(db, filters, ScenarioInputs(name="Baseline"))
    assert math.isclose(float(baseline["revenue"]), current["revenue"], abs_tol=0.2)
    assert math.isclose(
        float(baseline["contribution_profit"]), current["contribution_profit"], abs_tol=0.2
    )


def test_forecast_targets_inventory_and_quality(tmp_path: Path):
    db, filters = _build(tmp_path)
    forecast = forecast_metric(db, "revenue", horizon=3)
    assert len(forecast.forecast) == 3
    assert not forecast.leaderboard.empty
    assert forecast.selected_model in forecast.leaderboard["model"].tolist()
    assert quality_score(db) > 90
    assert inventory_kpis(db)["sku_count"] > 0
    target = target_status(db, "2025-12")
    assert set(target["status"]).issubset({"On Track", "At Risk", "Off Track"})


def test_incremental_load_is_idempotent_and_assistant_is_grounded(tmp_path: Path):
    db, filters = _build(tmp_path)
    sample = generate_demo_transactions(
        DemoConfig(
            start="2025-12-01",
            end="2025-12-03",
            base_daily_orders=2,
            n_customers=20,
            n_products=8,
            min_daily_orders=2,
            seed=123,
        )
    )
    result = clean_transactions(sample)
    first = build_warehouse(result, db, load_mode="append", source_name="incremental_test")
    second = build_warehouse(result, db, load_mode="append", source_name="incremental_test_repeat")
    assert first["inserted_rows"] > 0
    assert second["inserted_rows"] == 0
    answer = answer_business_question(db, filters, "为什么利润下降？")
    assert answer.query_id
    assert not answer.data.empty
    runs = query_df(db, "SELECT COUNT(*) n FROM etl_runs")
    assert int(runs.iloc[0, 0]) >= 3
