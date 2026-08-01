from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .metrics import FilterSpec, kpi_summary
from .warehouse import query_df


@dataclass(frozen=True)
class ScenarioInputs:
    name: str = "Scenario"
    price_change_pct: float = 0.0
    discount_change_pp: float = 0.0
    marketing_change_pct: float = 0.0
    unit_cost_change_pct: float = 0.0
    shipping_cost_change_pct: float = 0.0
    cancellation_change_pp: float = 0.0
    elasticity_override: float | None = None


def _weighted_elasticity(db_path: str | Path, filters: FilterSpec) -> float:
    clauses = ["sale_valid=1"]
    params: list = []
    if filters.start_date:
        clauses.append("date>=?")
        params.append(filters.start_date)
    if filters.end_date:
        clauses.append("date<=?")
        params.append(filters.end_date)
    for column, values in (
        ("country", filters.countries),
        ("category", filters.categories),
        ("channel", filters.channels),
    ):
        if values:
            placeholders = ",".join("?" for _ in values)
            clauses.append(f"{column} IN ({placeholders})")
            params.extend(values)
    row = query_df(
        db_path,
        f"""
        SELECT SUM(price_elasticity * net_revenue) / NULLIF(SUM(net_revenue),0) elasticity
        FROM fact_transactions WHERE {' AND '.join(clauses)}
        """,
        params,
    ).iloc[0, 0]
    return float(row if row is not None else -1.4)


def simulate_scenario(
    db_path: str | Path,
    filters: FilterSpec,
    scenario: ScenarioInputs,
) -> dict[str, float | str]:
    baseline = kpi_summary(db_path, filters)
    elasticity = (
        scenario.elasticity_override
        if scenario.elasticity_override is not None
        else _weighted_elasticity(db_path, filters)
    )
    price_change = scenario.price_change_pct / 100
    discount_change = scenario.discount_change_pp / 100
    marketing_change = scenario.marketing_change_pct / 100
    cost_change = scenario.unit_cost_change_pct / 100
    shipping_change = scenario.shipping_cost_change_pct / 100
    cancellation_change = scenario.cancellation_change_pp / 100

    baseline_discount = baseline["discount_rate"]
    effective_price_change = price_change - discount_change / max(1 - baseline_discount, 0.3)
    price_demand_factor = max(0.35, (1 + effective_price_change) ** elasticity)
    marketing_demand_factor = max(0.6, 1 + 0.18 * marketing_change)
    demand_factor = price_demand_factor * marketing_demand_factor

    projected_units = baseline["units"] * demand_factor
    projected_orders = baseline["orders"] * demand_factor
    projected_customers = baseline["active_customers"] * (0.65 + 0.35 * demand_factor)
    projected_gross_revenue = baseline["gross_revenue"] * demand_factor * (1 + price_change)
    projected_discount_rate = float(np.clip(baseline_discount + discount_change, 0, 0.40))
    projected_revenue = projected_gross_revenue * (1 - projected_discount_rate)
    projected_cogs = baseline["cogs"] * demand_factor * (1 + cost_change)
    projected_shipping = baseline["shipping_cost"] * demand_factor * (1 + shipping_change)
    projected_payment = baseline["payment_fee"] * (projected_revenue / max(baseline["revenue"], 1))
    projected_marketing = baseline["marketing_cost"] * (1 + marketing_change)
    projected_cancellation_rate = float(np.clip(baseline["cancellation_rate"] + cancellation_change, 0, 0.30))
    projected_return_loss = baseline["return_loss"] * (
        projected_cancellation_rate / max(baseline["cancellation_rate"], 0.005)
    )
    projected_gross_profit = projected_revenue - projected_cogs
    incremental_return_loss = projected_return_loss - baseline["return_loss"]
    projected_contribution = (
        projected_gross_profit
        - projected_shipping
        - projected_payment
        - projected_marketing
        - incremental_return_loss
    )
    result: dict[str, float | str] = {
        "scenario": scenario.name,
        "elasticity": elasticity,
        "demand_factor": demand_factor,
        "revenue": projected_revenue,
        "revenue_change": projected_revenue - baseline["revenue"],
        "gross_profit": projected_gross_profit,
        "gross_margin": projected_gross_profit / projected_revenue if projected_revenue else 0.0,
        "contribution_profit": projected_contribution,
        "contribution_margin": projected_contribution / projected_revenue if projected_revenue else 0.0,
        "contribution_profit_change": projected_contribution - baseline["contribution_profit"],
        "orders": projected_orders,
        "active_customers": projected_customers,
        "units": projected_units,
        "discount_rate": projected_discount_rate,
        "cancellation_rate": projected_cancellation_rate,
        **{f"input_{k}": v for k, v in asdict(scenario).items() if k != "name"},
    }
    return result


def compare_scenarios(
    db_path: str | Path,
    filters: FilterSpec,
    scenarios: list[ScenarioInputs],
) -> pd.DataFrame:
    baseline = ScenarioInputs(name="Baseline")
    rows = [simulate_scenario(db_path, filters, baseline)]
    rows.extend(simulate_scenario(db_path, filters, scenario) for scenario in scenarios)
    out = pd.DataFrame(rows)
    out["recommended"] = False
    if not out.empty:
        feasible = out[out["revenue"] > 0]
        if not feasible.empty:
            best_idx = feasible["contribution_profit"].idxmax()
            out.loc[best_idx, "recommended"] = True
    return out


@dataclass(frozen=True)
class UncertaintyInputs:
    elasticity_sd: float = 0.22
    marketing_response_mean: float = 0.18
    marketing_response_sd: float = 0.05
    baseline_demand_sd: float = 0.035
    cost_shock_sd: float = 0.025
    shipping_shock_sd: float = 0.03
    simulations: int = 5000
    seed: int = 20260801


def monte_carlo_scenario(
    db_path: str | Path,
    filters: FilterSpec,
    scenario: ScenarioInputs,
    uncertainty: UncertaintyInputs | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run a vectorized probabilistic scenario simulation.

    Returns a one-row summary, the simulation sample and a sensitivity table based on
    rank correlations. Inputs are explicit so the result is auditable rather than a
    black-box recommendation.
    """
    uncertainty = uncertainty or UncertaintyInputs()
    baseline = kpi_summary(db_path, filters)
    base_elasticity = (
        scenario.elasticity_override
        if scenario.elasticity_override is not None
        else _weighted_elasticity(db_path, filters)
    )
    rng = np.random.default_rng(uncertainty.seed)
    n = max(500, int(uncertainty.simulations))

    elasticity = rng.normal(base_elasticity, uncertainty.elasticity_sd, n)
    marketing_response = np.clip(
        rng.normal(uncertainty.marketing_response_mean, uncertainty.marketing_response_sd, n),
        0.02,
        0.45,
    )
    baseline_demand = np.clip(rng.normal(1.0, uncertainty.baseline_demand_sd, n), 0.75, 1.25)
    cost_shock = rng.normal(0.0, uncertainty.cost_shock_sd, n)
    shipping_shock = rng.normal(0.0, uncertainty.shipping_shock_sd, n)

    price_change = scenario.price_change_pct / 100
    discount_change = scenario.discount_change_pp / 100
    marketing_change = scenario.marketing_change_pct / 100
    cost_change = scenario.unit_cost_change_pct / 100 + cost_shock
    shipping_change = scenario.shipping_cost_change_pct / 100 + shipping_shock
    cancellation_change = scenario.cancellation_change_pp / 100

    baseline_discount = baseline["discount_rate"]
    effective_price_change = price_change - discount_change / max(1 - baseline_discount, 0.3)
    price_factor = np.clip((1 + effective_price_change) ** elasticity, 0.35, 2.25)
    marketing_factor = np.clip(1 + marketing_response * marketing_change, 0.55, 1.8)
    demand_factor = price_factor * marketing_factor * baseline_demand

    gross_revenue = baseline["gross_revenue"] * demand_factor * (1 + price_change)
    discount_rate = float(np.clip(baseline_discount + discount_change, 0, 0.40))
    revenue = gross_revenue * (1 - discount_rate)
    cogs = baseline["cogs"] * demand_factor * (1 + cost_change)
    shipping = baseline["shipping_cost"] * demand_factor * (1 + shipping_change)
    payment = baseline["payment_fee"] * revenue / max(baseline["revenue"], 1)
    marketing = baseline["marketing_cost"] * (1 + marketing_change)
    cancellation_rate = float(np.clip(baseline["cancellation_rate"] + cancellation_change, 0, 0.30))
    return_loss = baseline["return_loss"] * cancellation_rate / max(baseline["cancellation_rate"], 0.005)
    incremental_return = return_loss - baseline["return_loss"]
    contribution = revenue - cogs - shipping - payment - marketing - incremental_return

    samples = pd.DataFrame(
        {
            "elasticity": elasticity,
            "marketing_response": marketing_response,
            "baseline_demand_factor": baseline_demand,
            "cost_shock": cost_shock,
            "shipping_shock": shipping_shock,
            "revenue": revenue,
            "revenue_change": revenue - baseline["revenue"],
            "contribution_profit": contribution,
            "contribution_profit_change": contribution - baseline["contribution_profit"],
        }
    )
    profit_change = samples["contribution_profit_change"]
    summary = pd.DataFrame(
        [
            {
                "scenario": scenario.name,
                "simulations": n,
                "median_profit_change": float(profit_change.median()),
                "p05_profit_change": float(profit_change.quantile(0.05)),
                "p95_profit_change": float(profit_change.quantile(0.95)),
                "probability_profit_improves": float((profit_change > 0).mean()),
                "probability_revenue_up_profit_down": float(
                    ((samples["revenue_change"] > 0) & (profit_change < 0)).mean()
                ),
                "median_revenue_change": float(samples["revenue_change"].median()),
            }
        ]
    )
    driver_columns = [
        "elasticity",
        "marketing_response",
        "baseline_demand_factor",
        "cost_shock",
        "shipping_shock",
    ]
    sensitivity = (
        samples[driver_columns + ["contribution_profit_change"]]
        .corr(method="spearman")["contribution_profit_change"]
        .drop("contribution_profit_change")
        .rename("rank_correlation")
        .reset_index().rename(columns={"index": "driver"})
    )
    sensitivity["absolute_importance"] = sensitivity["rank_correlation"].abs()
    sensitivity = sensitivity.sort_values("absolute_importance", ascending=False)
    return summary, samples, sensitivity
