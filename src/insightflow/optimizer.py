"""Search many pricing plans at once and keep the ones worth the risk.

Every candidate faces the same simulated futures (common random numbers), so two plans
differ only because of the plan, not the luck of the draw. The output is a risk-return
frontier: for any tolerance for bad outcomes, the plan with the best typical result.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from .decision_lab import (
    ScenarioInputs,
    UncertaintyInputs,
    _scenario_elasticity,
    project_outcome,
    uncertainty_draws,
)
from .metrics import FilterSpec, kpi_summary


@dataclass(frozen=True)
class SearchSpace:
    price_steps: tuple[float, ...] = (-6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0)
    discount_steps: tuple[float, ...] = (-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0)
    marketing_steps: tuple[float, ...] = (-30.0, -15.0, 0.0, 15.0, 30.0)


@dataclass(frozen=True)
class Guardrails:
    max_revenue_drop_pct: float = 5.0
    min_probability: float = 0.6


def search_plans(
    db_path: str | Path,
    filters: FilterSpec,
    *,
    space: SearchSpace | None = None,
    guardrails: Guardrails | None = None,
    uncertainty: UncertaintyInputs | None = None,
) -> pd.DataFrame:
    """Evaluate every combination and mark the plans that pass the guardrails."""
    space = space or SearchSpace()
    guardrails = guardrails or Guardrails()
    uncertainty = uncertainty or UncertaintyInputs(simulations=1500)
    baseline = kpi_summary(db_path, filters)
    base_elasticity = _scenario_elasticity(db_path, filters, ScenarioInputs())
    draws = uncertainty_draws(base_elasticity, uncertainty)

    rows: list[dict] = []
    for price, discount, marketing in product(
        space.price_steps, space.discount_steps, space.marketing_steps
    ):
        plan = ScenarioInputs(
            name=f"{price:+.0f}% / {discount:+.0f}pp / {marketing:+.0f}%",
            price_change_pct=price,
            discount_change_pp=discount,
            marketing_change_pct=marketing,
        )
        outcome = project_outcome(baseline, plan, **draws)
        change = outcome["contribution_profit"] - baseline["contribution_profit"]
        revenue_change = outcome["revenue"] - baseline["revenue"]
        rows.append(
            {
                "plan": plan.name,
                "price_change_pct": price,
                "discount_change_pp": discount,
                "marketing_change_pct": marketing,
                "median_profit_change": float(np.median(change)),
                "p05_profit_change": float(np.quantile(change, 0.05)),
                "p95_profit_change": float(np.quantile(change, 0.95)),
                "probability_profit_improves": float(np.mean(change > 0)),
                "median_revenue_change": float(np.median(revenue_change)),
            }
        )
    plans = pd.DataFrame(rows)
    floor = -guardrails.max_revenue_drop_pct / 100 * max(baseline["revenue"], 1)
    plans["passes_guardrails"] = (plans["median_revenue_change"] >= floor) & (
        plans["probability_profit_improves"] >= guardrails.min_probability
    )
    return plans.sort_values("median_profit_change", ascending=False).reset_index(drop=True)


def efficient_frontier(plans: pd.DataFrame) -> pd.DataFrame:
    """Keep plans no other plan beats on both typical result and bad-case result."""
    ordered = plans.sort_values("p05_profit_change", ascending=False)
    best_median = -np.inf
    keep: list[int] = []
    for index, row in ordered.iterrows():
        if row["median_profit_change"] > best_median:
            keep.append(index)
            best_median = row["median_profit_change"]
    return plans.loc[keep].sort_values("p05_profit_change").reset_index(drop=True)


def recommend_plan(plans: pd.DataFrame) -> pd.Series | None:
    """Pick the passing plan with the strongest bad-case result among the leaders."""
    passing = plans[plans["passes_guardrails"]]
    if passing.empty:
        return None
    leaders = passing.head(max(3, len(passing) // 4))
    return leaders.sort_values("p05_profit_change", ascending=False).iloc[0]
