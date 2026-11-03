from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .metrics import FilterSpec, filter_clause, kpi_summary
from .warehouse import query_df

DEFAULT_ELASTICITY = -1.4
MARKETING_RESPONSE = 0.18


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
    where, params = filter_clause(filters)
    row = query_df(
        db_path,
        f"""
        SELECT SUM(price_elasticity * net_revenue) / NULLIF(SUM(net_revenue),0) elasticity
        FROM v_sales WHERE {where}
        """,
        params,
    ).iloc[0, 0]
    return float(row) if row is not None and not pd.isna(row) else DEFAULT_ELASTICITY


def _scenario_elasticity(
    db_path: str | Path, filters: FilterSpec, scenario: ScenarioInputs
) -> float:
    if scenario.elasticity_override is not None:
        return float(scenario.elasticity_override)
    from .elasticity import blended_elasticity

    return blended_elasticity(db_path, filters, default=_weighted_elasticity(db_path, filters))


def project_outcome(
    baseline: dict[str, float],
    scenario: ScenarioInputs,
    *,
    elasticity,
    marketing_response=MARKETING_RESPONSE,
    baseline_demand=1.0,
    cost_shock=0.0,
    shipping_shock=0.0,
) -> dict[str, object]:
    """Project one scenario. Scalars give a point estimate; arrays give a simulation.

    The deterministic comparison and the Monte Carlo run share this single formula, so a
    median can never disagree with a point estimate because of a different clipping rule.
    With no changes it reproduces the baseline exactly, returns included.
    """
    price_change = scenario.price_change_pct / 100
    discount_change = scenario.discount_change_pp / 100
    marketing_change = scenario.marketing_change_pct / 100
    cost_change = scenario.unit_cost_change_pct / 100 + cost_shock
    shipping_change = scenario.shipping_cost_change_pct / 100 + shipping_shock
    cancellation_change = scenario.cancellation_change_pp / 100

    baseline_discount = baseline["discount_rate"]
    # Demand answers the discount that can really be given, not the one asked for: a ledger
    # with no discounts has none to cut.
    discount_rate = float(np.clip(baseline_discount + discount_change, 0, 0.40))
    given = discount_rate - baseline_discount
    effective_price_change = price_change - given / max(1 - baseline_discount, 0.3)
    price_base = max(1 + effective_price_change, 0.1)
    price_factor = np.clip(price_base**elasticity, 0.35, 2.25)
    marketing_factor = np.clip(1 + marketing_response * marketing_change, 0.55, 1.8)
    demand_factor = price_factor * marketing_factor * baseline_demand

    gross = baseline["gross_revenue"] * demand_factor * (1 + price_change)
    sales_net = gross * (1 - discount_rate)
    baseline_sales_net = baseline["gross_revenue"] - baseline["discount_amount"]
    sale_cogs = baseline["sale_cogs"] * demand_factor * (1 + cost_change)
    shipping = baseline["shipping_cost"] * demand_factor * (1 + shipping_change)
    payment = baseline["payment_fee"] * sales_net / max(baseline_sales_net, 1)
    marketing = baseline["marketing_cost"] * (1 + marketing_change)

    cancellation_rate = float(np.clip(baseline["cancellation_rate"] + cancellation_change, 0, 0.30))
    return_scale = cancellation_rate / max(baseline["cancellation_rate"], 0.005)
    if not cancellation_change:
        return_scale = 1.0
    refunds = baseline["returns_value"] * return_scale * sales_net / max(baseline_sales_net, 1)
    recovered = baseline["returned_cogs"] * return_scale * demand_factor * (1 + cost_change)
    handling = baseline["return_processing_cost"] * return_scale * demand_factor

    revenue = sales_net - refunds
    cogs = sale_cogs - recovered
    gross_profit = revenue - cogs
    contribution = gross_profit - shipping - payment - marketing - handling
    return {
        "demand_factor": demand_factor,
        "revenue": revenue,
        "gross_profit": gross_profit,
        "contribution_profit": contribution,
        "discount_rate": discount_rate,
        "cancellation_rate": cancellation_rate,
    }


def simulate_scenario(
    db_path: str | Path,
    filters: FilterSpec,
    scenario: ScenarioInputs,
) -> dict[str, float | str]:
    baseline = kpi_summary(db_path, filters)
    elasticity = _scenario_elasticity(db_path, filters, scenario)
    outcome = project_outcome(baseline, scenario, elasticity=elasticity)
    demand_factor = float(outcome["demand_factor"])
    revenue = float(outcome["revenue"])
    gross_profit = float(outcome["gross_profit"])
    contribution = float(outcome["contribution_profit"])
    result: dict[str, float | str] = {
        "scenario": scenario.name,
        "elasticity": elasticity,
        "demand_factor": demand_factor,
        "revenue": revenue,
        "revenue_change": revenue - baseline["revenue"],
        "gross_profit": gross_profit,
        "gross_margin": gross_profit / revenue if revenue else 0.0,
        "contribution_profit": contribution,
        "contribution_margin": contribution / revenue if revenue else 0.0,
        "contribution_profit_change": contribution - baseline["contribution_profit"],
        "orders": baseline["orders"] * demand_factor,
        "active_customers": baseline["active_customers"] * (0.65 + 0.35 * demand_factor),
        "units": baseline["units"] * demand_factor,
        "discount_rate": float(outcome["discount_rate"]),
        "cancellation_rate": float(outcome["cancellation_rate"]),
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
    marketing_response_mean: float = MARKETING_RESPONSE
    marketing_response_sd: float = 0.05
    baseline_demand_sd: float = 0.035
    cost_shock_sd: float = 0.025
    shipping_shock_sd: float = 0.03
    simulations: int = 5000
    seed: int = 20260801


def uncertainty_draws(
    base_elasticity: float, uncertainty: UncertaintyInputs
) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(uncertainty.seed)
    n = max(500, int(uncertainty.simulations))
    return {
        "elasticity": rng.normal(base_elasticity, uncertainty.elasticity_sd, n),
        "marketing_response": np.clip(
            rng.normal(uncertainty.marketing_response_mean, uncertainty.marketing_response_sd, n),
            0.02,
            0.45,
        ),
        "baseline_demand": np.clip(rng.normal(1.0, uncertainty.baseline_demand_sd, n), 0.75, 1.25),
        "cost_shock": rng.normal(0.0, uncertainty.cost_shock_sd, n),
        "shipping_shock": rng.normal(0.0, uncertainty.shipping_shock_sd, n),
    }


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
    draws = uncertainty_draws(_scenario_elasticity(db_path, filters, scenario), uncertainty)
    outcome = project_outcome(baseline, scenario, **draws)
    revenue = outcome["revenue"]
    contribution = outcome["contribution_profit"]

    samples = pd.DataFrame(
        {
            "elasticity": draws["elasticity"],
            "marketing_response": draws["marketing_response"],
            "baseline_demand_factor": draws["baseline_demand"],
            "cost_shock": draws["cost_shock"],
            "shipping_shock": draws["shipping_shock"],
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
                "simulations": len(samples),
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
        .reset_index()
        .rename(columns={"index": "driver"})
    )
    sensitivity["absolute_importance"] = sensitivity["rank_correlation"].abs()
    sensitivity = sensitivity.sort_values("absolute_importance", ascending=False)
    return summary, samples, sensitivity
