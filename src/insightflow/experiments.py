from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .config import is_read_only
from .warehouse import connect, query_df, table_exists


@dataclass(frozen=True)
class ExperimentSummary:
    experiment_id: str
    experiment_name: str
    primary_metric: str
    sample_size: int
    lift: float
    confidence_low: float
    confidence_high: float
    probability_positive: float
    decision: str
    guardrail_status: str


def stable_seed(value: str) -> int:
    """Create a process-stable NumPy seed from text."""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _fraction(value: str, salt: str) -> float:
    digest = hashlib.sha256(f"{salt}|{value}".encode()).hexdigest()
    return int(digest[:12], 16) / float(16**12 - 1)


def seed_demo_experiments(db_path: str | Path) -> None:
    if not table_exists(db_path, "dim_customer"):
        return
    customers = query_df(db_path, "SELECT customer_id FROM dim_customer WHERE customer_id IS NOT NULL")
    if customers.empty:
        return
    customer_ids = customers["customer_id"].astype(str).tolist()
    definitions = [
        {
            "experiment_id": "EXP_FREE_SHIPPING_01",
            "experiment_name": "高价值客户免邮测试",
            "primary_metric": "contribution_profit",
            "treatment_revenue_lift": 0.08,
            "treatment_profit_lift": 0.04,
            "treatment_conversion_lift": 0.06,
            "treatment_return_lift": 0.003,
        },
        {
            "experiment_id": "EXP_BLANKET_DISCOUNT_01",
            "experiment_name": "全客群九折促销测试",
            "primary_metric": "contribution_profit",
            "treatment_revenue_lift": 0.12,
            "treatment_profit_lift": -0.55,
            "treatment_conversion_lift": 0.09,
            "treatment_return_lift": 0.018,
        },
    ]
    rows: list[dict] = []
    max_customers = min(len(customer_ids), 2600)
    selected = customer_ids[:max_customers]
    for definition in definitions:
        for customer_id in selected:
            assignment = "Treatment" if _fraction(customer_id, definition["experiment_id"] + "assign") >= 0.5 else "Control"
            baseline_revenue = 18 + 170 * _fraction(customer_id, definition["experiment_id"] + "revenue")
            baseline_margin = 0.12 + 0.18 * _fraction(customer_id, definition["experiment_id"] + "margin")
            conversion_prob = 0.28 + 0.24 * _fraction(customer_id, definition["experiment_id"] + "conv")
            if assignment == "Treatment":
                conversion_prob *= 1 + definition["treatment_conversion_lift"]
            converted = _fraction(customer_id, definition["experiment_id"] + "outcome") < min(conversion_prob, 0.95)
            revenue = baseline_revenue if converted else 0.0
            profit = revenue * baseline_margin
            return_prob = 0.035
            if assignment == "Treatment":
                revenue *= 1 + definition["treatment_revenue_lift"]
                profit *= 1 + definition["treatment_profit_lift"]
                return_prob += definition["treatment_return_lift"]
            returned = _fraction(customer_id, definition["experiment_id"] + "return") < return_prob
            if returned:
                profit -= revenue * 0.18 + 3.5
            rows.append(
                {
                    "experiment_id": definition["experiment_id"],
                    "experiment_name": definition["experiment_name"],
                    "primary_metric": definition["primary_metric"],
                    "customer_id": customer_id,
                    "assignment": assignment,
                    "converted": int(converted),
                    "net_revenue": round(revenue, 2),
                    "contribution_profit": round(profit, 2),
                    "returned": int(returned),
                    "data_status": "Simulated",
                }
            )
    with connect(db_path) as conn:
        pd.DataFrame(rows).to_sql("experiment_assignments", conn, if_exists="replace", index=False)
        pd.DataFrame(definitions).to_sql("experiment_catalog", conn, if_exists="replace", index=False)


def experiment_catalog(db_path: str | Path) -> pd.DataFrame:
    if not table_exists(db_path, "experiment_catalog"):
        if is_read_only():
            return pd.DataFrame()
        seed_demo_experiments(db_path)
    return query_df(db_path, "SELECT * FROM experiment_catalog")


def _bootstrap_difference(control: np.ndarray, treatment: np.ndarray, seed: int = 42) -> tuple[float, float, float]:
    if len(control) == 0 or len(treatment) == 0:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    n_boot = 1200
    control_idx = rng.integers(0, len(control), size=(n_boot, len(control)))
    treatment_idx = rng.integers(0, len(treatment), size=(n_boot, len(treatment)))
    diffs = treatment[treatment_idx].mean(axis=1) - control[control_idx].mean(axis=1)
    return float(np.quantile(diffs, 0.025)), float(np.quantile(diffs, 0.975)), float((diffs > 0).mean())


def analyze_experiment(db_path: str | Path, experiment_id: str) -> tuple[ExperimentSummary, pd.DataFrame, pd.DataFrame]:
    data = query_df(
        db_path,
        "SELECT * FROM experiment_assignments WHERE experiment_id=?",
        (experiment_id,),
    )
    if data.empty:
        raise ValueError(f"未找到实验 {experiment_id}")
    metrics = []
    for metric in ("converted", "net_revenue", "contribution_profit", "returned"):
        group = data.groupby("assignment")[metric].agg(["mean", "sum", "count"]).reset_index()
        control = data.loc[data["assignment"] == "Control", metric].to_numpy(float)
        treatment = data.loc[data["assignment"] == "Treatment", metric].to_numpy(float)
        low, high, probability = _bootstrap_difference(control, treatment, seed=stable_seed(metric))
        control_mean = float(control.mean()) if len(control) else 0.0
        treatment_mean = float(treatment.mean()) if len(treatment) else 0.0
        metrics.append(
            {
                "metric": metric,
                "control_mean": control_mean,
                "treatment_mean": treatment_mean,
                "absolute_lift": treatment_mean - control_mean,
                "relative_lift": (treatment_mean - control_mean) / abs(control_mean) if control_mean else np.nan,
                "ci_low": low,
                "ci_high": high,
                "probability_positive": probability,
            }
        )
    metric_table = pd.DataFrame(metrics)
    primary = metric_table.loc[metric_table["metric"] == "contribution_profit"].iloc[0]
    revenue = metric_table.loc[metric_table["metric"] == "net_revenue"].iloc[0]
    returns = metric_table.loc[metric_table["metric"] == "returned"].iloc[0]
    guardrail_ok = returns["absolute_lift"] <= 0.01 and primary["absolute_lift"] >= 0
    if primary["absolute_lift"] < 0 or not guardrail_ok:
        decision = (
            "不建议推广：收入增长但利润受损"
            if revenue["absolute_lift"] > 0
            else "不建议推广：利润护栏未通过"
        )
    elif primary["probability_positive"] >= 0.90:
        decision = "建议推广"
    else:
        decision = "继续实验或定向推广"
    summary = ExperimentSummary(
        experiment_id=experiment_id,
        experiment_name=str(data["experiment_name"].iloc[0]),
        primary_metric="contribution_profit",
        sample_size=len(data),
        lift=float(primary["absolute_lift"]),
        confidence_low=float(primary["ci_low"]),
        confidence_high=float(primary["ci_high"]),
        probability_positive=float(primary["probability_positive"]),
        decision=decision,
        guardrail_status="通过" if guardrail_ok else "未通过",
    )
    balance = (
        data.groupby("assignment", as_index=False)
        .agg(customers=("customer_id", "nunique"), conversion_rate=("converted", "mean"), return_rate=("returned", "mean"))
    )
    return summary, metric_table, balance
