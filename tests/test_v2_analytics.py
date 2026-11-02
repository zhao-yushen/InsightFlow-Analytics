from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from insightflow.basket import association_rules
from insightflow.churn import area_under_curve, train_churn_model
from insightflow.demo_data import DemoConfig, generate_demo_transactions
from insightflow.elasticity import category_price_moves, estimate_elasticities
from insightflow.etl import clean_transactions
from insightflow.forecasting import _forecast_values, forecast_metric
from insightflow.metrics import FilterSpec, customer_value_risk, market_performance
from insightflow.optimizer import (
    Guardrails,
    SearchSpace,
    efficient_frontier,
    recommend_plan,
    search_plans,
)
from insightflow.pvm import price_volume_mix
from insightflow.supply import inventory_policy, policy_matrix
from insightflow.warehouse import build_warehouse


def test_price_volume_mix_explains_the_whole_change(demo_warehouse, last_quarter):
    bridge = price_volume_mix(demo_warehouse, last_quarter)
    assert bridge.attrs["unexplained"] == pytest.approx(0.0, abs=0.05)
    total = bridge.attrs["start"] + bridge["impact"].sum()
    assert total == pytest.approx(bridge.attrs["end"], abs=0.05)
    assert {"volume", "mix", "price", "discount", "unit_cost", "returns"} <= set(bridge["step"])


def test_elasticities_are_negative_and_rank_with_the_truth(demo_warehouse):
    table = estimate_elasticities(demo_warehouse, FilterSpec())
    assert (table["basis"] == "data").sum() >= 6
    fitted = table.dropna(subset=["estimate"])
    assert (fitted["elasticity"] < 0).all()
    assert fitted["elasticity"].median() < -0.4


def test_flat_prices_fall_back_to_the_prior(tmp_path):
    rows = [
        {
            "invoice_no": f"{week}-{i}",
            "stock_code": f"SKU-{i % 3}",
            "description": "Item",
            "category": "Kitchen",
            "quantity": 1,
            "invoice_date": (pd.Timestamp("2025-01-06") + pd.Timedelta(weeks=week)).isoformat(),
            "unit_price": 20.0,
            "discount_rate": 0.0,
            "customer_id": str(i),
            "country": "China",
            "channel": "Web",
            "price_elasticity": -1.3,
        }
        for week in range(20)
        for i in range(12)
    ]
    db = tmp_path / "flat.db"
    build_warehouse(clean_transactions(pd.DataFrame(rows), transaction_status="Verified"), db)
    table = estimate_elasticities(db, FilterSpec())
    assert table.iloc[0]["basis"] == "prior"
    assert table.iloc[0]["elasticity"] == pytest.approx(-1.3)


def test_price_moves_stay_inside_the_cap(demo_warehouse, last_quarter):
    moves = category_price_moves(demo_warehouse, last_quarter, max_move=0.08)
    assert not moves.empty
    assert moves["recommended_move"].abs().max() <= 0.08 + 1e-9
    assert moves["expected_profit_change"].is_monotonic_decreasing


def test_optimizer_ranks_plans_and_enforces_guardrails(demo_warehouse, last_quarter):
    space = SearchSpace(
        price_steps=(-2.0, 0.0, 2.0), discount_steps=(-1.0, 0.0, 1.0), marketing_steps=(0.0, 15.0)
    )
    plans = search_plans(
        demo_warehouse, last_quarter, space=space, guardrails=Guardrails(min_probability=0.7)
    )
    assert len(plans) == 18
    do_nothing = plans[
        (plans["price_change_pct"] == 0)
        & (plans["discount_change_pp"] == 0)
        & (plans["marketing_change_pct"] == 0)
    ].iloc[0]
    assert abs(do_nothing["median_profit_change"]) < abs(plans["median_profit_change"]).max()
    assert not plans.loc[plans["probability_profit_improves"] < 0.7, "passes_guardrails"].any()
    choice = recommend_plan(plans)
    if choice is not None:
        assert bool(choice["passes_guardrails"])


def test_efficient_frontier_drops_dominated_plans():
    plans = pd.DataFrame(
        {
            "plan": ["a", "b", "c", "d"],
            "median_profit_change": [10.0, 20.0, 15.0, 30.0],
            "p05_profit_change": [5.0, 1.0, 0.0, -8.0],
        }
    )
    frontier = efficient_frontier(plans)
    assert list(frontier["plan"]) == ["d", "b", "a"]


def test_basket_analysis_finds_real_attachment(demo_warehouse):
    rules = association_rules(demo_warehouse, FilterSpec(), min_pair_orders=8, limit=20)
    assert not rules.empty
    assert rules["lift"].iloc[0] > 2
    assert rules["lift"].is_monotonic_decreasing
    assert (rules["confidence"] <= 1).all()


def test_inventory_policy_responds_to_service_level(demo_warehouse):
    relaxed = inventory_policy(demo_warehouse, service_level=0.90).set_index("stock_code")
    strict = inventory_policy(demo_warehouse, service_level=0.99).set_index("stock_code")
    moving = strict["daily_demand"] > 0
    assert (strict.loc[moving, "safety_stock"] >= relaxed.loc[moving, "safety_stock"]).all()
    assert strict["safety_stock"].sum() > relaxed["safety_stock"].sum()
    assert set(strict["abc_class"]) <= {"A", "B", "C"}
    assert set(strict["xyz_class"]) <= {"X", "Y", "Z"}
    assert (strict["recommended_order"] >= 0).all()
    assert policy_matrix(strict.reset_index()).shape == (3, 3)


def test_churn_model_is_graded_out_of_time(demo_warehouse):
    model = train_churn_model(demo_warehouse)
    assert model is not None
    assert model.auc > 0.7
    assert model.top_decile_lift > 1.2
    assert model.calibration["actual"].iloc[-1] > model.calibration["actual"].iloc[0]
    risk = customer_value_risk(demo_warehouse, FilterSpec("2025-07-01", "2025-12-31"))
    assert (risk["risk_basis"] == "model").any()
    assert risk["churn_risk"].between(0, 1).all()


def test_auc_matches_known_rankings():
    labels = np.array([0, 0, 1, 1])
    assert area_under_curve(labels, np.array([0.1, 0.2, 0.8, 0.9])) == 1.0
    assert area_under_curve(labels, np.array([0.9, 0.8, 0.2, 0.1])) == 0.0
    assert area_under_curve(labels, np.array([0.5, 0.5, 0.5, 0.5])) == 0.5


def test_too_few_customers_yields_no_model(tmp_path):
    db = tmp_path / "tiny.db"
    frame = generate_demo_transactions(
        DemoConfig(
            start="2025-01-01",
            end="2025-06-30",
            base_daily_orders=1,
            min_daily_orders=1,
            n_customers=20,
            n_products=8,
        )
    )
    build_warehouse(clean_transactions(frame, source_profile="demo_test"), db)
    assert train_churn_model(db) is None
    risk = customer_value_risk(db, FilterSpec("2025-01-01", "2025-06-30"))
    assert (risk["risk_basis"] == "rule").all()


def test_forecast_beats_or_matches_the_naive_baseline(demo_warehouse):
    result = forecast_metric(demo_warehouse, "revenue", horizon=3)
    board = result.leaderboard.set_index("model")
    assert board.iloc[0]["wape"] <= board.loc["naive", "wape"]
    assert result.skill_vs_naive is not None and result.skill_vs_naive >= 0
    assert (result.forecast["lower"] <= result.forecast["lower_80"]).all()
    assert (result.forecast["upper_80"] <= result.forecast["upper"]).all()
    assert (result.forecast["lower"] >= 0).all()


def test_profit_forecast_may_go_below_zero():
    # A loss-making business needs a band that can show losses.
    assert _forecast_values(np.array([-5.0, -6.0, -7.0]), "naive", 2).max() < 0


def test_seasonal_models_repeat_last_years_shape():
    history = np.tile(np.arange(12.0), 3)
    assert list(_forecast_values(history, "seasonal_naive", 3)) == [0.0, 1.0, 2.0]
    winters = _forecast_values(history, "holt_winters", 12)
    assert winters.argmax() == 11


def test_partial_final_month_is_excluded_from_training(tmp_path):
    frame = generate_demo_transactions(
        DemoConfig(
            start="2024-06-01",
            end="2025-06-10",
            base_daily_orders=4,
            min_daily_orders=3,
            n_customers=60,
            n_products=12,
        )
    )
    db = tmp_path / "partial.db"
    build_warehouse(clean_transactions(frame, source_profile="demo_test"), db)
    result = forecast_metric(db, "revenue", horizon=2)
    assert result.dropped_partial_month == "2025-06"
    assert result.history["month"].iloc[-1] == "2025-05"
    assert result.forecast["month"].iloc[0] == "2025-06"


def test_market_performance_places_each_market(demo_warehouse, last_quarter):
    markets = market_performance(demo_warehouse, last_quarter)
    assert markets["revenue_share"].sum() == pytest.approx(1.0)
    assert markets["lat"].notna().all()
    assert {"market_region", "contribution_margin"} <= set(markets.columns)
