from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from insightflow.action_center import sync_action_register, update_action_register
from insightflow.config import env_bool, is_read_only
from insightflow.decision_lab import ScenarioInputs, simulate_scenario
from insightflow.demo_data import DemoConfig, generate_demo_transactions
from insightflow.etl import clean_transactions
from insightflow.experiments import analyze_experiment, stable_seed
from insightflow.metrics import FilterSpec, kpi_summary
from insightflow.reporting import build_word_report_bytes, render_html_report
from insightflow.warehouse import build_warehouse


def _db(tmp_path: Path) -> tuple[Path, FilterSpec]:
    db = tmp_path / "hardening.db"
    frame = generate_demo_transactions(
        DemoConfig(
            start="2025-01-01",
            end="2025-12-31",
            base_daily_orders=3,
            min_daily_orders=2,
            n_customers=90,
            n_products=20,
        )
    )
    build_warehouse(clean_transactions(frame), db, source_name="hardening_test")
    return db, FilterSpec("2025-10-01", "2025-12-31")


def test_stable_seed_and_experiment_results_are_reproducible(tmp_path: Path):
    assert stable_seed("contribution_profit") == stable_seed("contribution_profit")
    assert stable_seed("revenue") != stable_seed("contribution_profit")
    db, _ = _db(tmp_path)
    first, metrics_first, _ = analyze_experiment(db, "EXP_BLANKET_DISCOUNT_01")
    second, metrics_second, _ = analyze_experiment(db, "EXP_BLANKET_DISCOUNT_01")
    assert first.confidence_low == second.confidence_low
    pd.testing.assert_frame_equal(metrics_first, metrics_second)


def test_zero_elasticity_override_is_respected(tmp_path: Path):
    db, filters = _db(tmp_path)
    baseline = kpi_summary(db, filters)
    result = simulate_scenario(
        db,
        filters,
        ScenarioInputs(name="Zero elasticity", price_change_pct=10, elasticity_override=0.0),
    )
    assert result["elasticity"] == 0.0
    assert result["units"] == pytest.approx(baseline["units"])


def test_action_state_persists_across_diagnostic_refresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INSIGHTFLOW_READ_ONLY", "false")
    db, filters = _db(tmp_path)
    actions = sync_action_register(db, filters, persist=True)
    assert not actions.empty
    edited = actions.head(1).copy()
    edited.loc[:, "status"] = "In Progress"
    edited.loc[:, "owner"] = "Test Owner"
    edited.loc[:, "resolution_note"] = "正在验证"
    assert update_action_register(db, edited) == 1
    refreshed = sync_action_register(db, filters, persist=True, include_inactive=True)
    row = refreshed.loc[refreshed["action_id"] == edited.iloc[0]["action_id"]].iloc[0]
    assert row["status"] == "In Progress"
    assert row["owner"] == "Test Owner"
    assert row["resolution_note"] == "正在验证"


def test_read_only_policy_is_enforced(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("INSIGHTFLOW_READ_ONLY", "true")
    assert is_read_only() is True
    db, filters = _db(tmp_path)
    actions = sync_action_register(db, filters, persist=False)
    assert not actions.empty
    with pytest.raises(PermissionError):
        update_action_register(db, actions.head(1))
    monkeypatch.setenv("INSIGHTFLOW_BAD_BOOL", "maybe")
    with pytest.raises(ValueError):
        env_bool("INSIGHTFLOW_BAD_BOOL")


def test_report_can_be_generated_fully_in_memory(tmp_path: Path):
    db, filters = _db(tmp_path)
    kpi = kpi_summary(db, filters)
    from insightflow.diagnostics import generate_diagnostics
    from insightflow.metrics import monthly_trend

    issues, drivers = generate_diagnostics(db, filters)
    trend = monthly_trend(db, filters)
    html = render_html_report("2025 Q4", kpi, issues, drivers, trend)
    docx = build_word_report_bytes("2025 Q4", kpi, issues, drivers)
    assert "InsightFlow" in html
    assert docx[:2] == b"PK"


def test_fault_injection_surfaces_contract_failures():
    from insightflow.fault_injection import FaultPlan, inject_faults

    source = generate_demo_transactions(
        DemoConfig(
            start="2025-01-01",
            end="2025-02-28",
            base_daily_orders=2,
            min_daily_orders=2,
            n_customers=30,
            n_products=10,
        )
    ).head(1000)
    corrupted = inject_faults(
        source,
        FaultPlan(
            duplicate_rate=0.05,
            missing_customer_rate=0.05,
            invalid_price_rate=0.03,
            future_date_rate=0.02,
            unknown_channel_rate=0.03,
            remove_month=False,
        ),
    )
    result = clean_transactions(corrupted, source_profile="fault_test", transaction_status="Simulated")
    assert len(corrupted) > len(source)
    assert (result.contract_issues["severity"] != "PASS").any()
