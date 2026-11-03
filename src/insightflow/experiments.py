from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from .config import is_read_only
from .warehouse import connect, query_df, table_exists

RETURN_GUARDRAIL = 0.01
MAX_BOOTSTRAP_ROWS = 50_000
HARM_PROBABILITY = 0.10
CONFIDENT_PROBABILITY = 0.90
Z_ALPHA = 1.96
Z_POWER = 0.8416
ASSIGNMENT_COLUMNS = (
    "experiment_id",
    "customer_id",
    "assignment",
    "converted",
    "net_revenue",
    "contribution_profit",
    "returned",
)


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
    decision_code: str = "inconclusive"
    sample_ratio_p: float = 1.0
    minimum_detectable_lift: float = 0.0
    required_sample_per_arm: int = 0
    data_status: str = "Simulated"


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
    customers = query_df(
        db_path, "SELECT customer_id FROM dim_customer WHERE customer_id IS NOT NULL"
    )
    if customers.empty:
        return
    customer_ids = customers["customer_id"].astype(str).tolist()
    # Three deliberately different outcomes: one worth shipping, one that grows revenue
    # while destroying profit, and one too small to call either way.
    definitions = [
        {
            "experiment_id": "EXP_FREE_SHIPPING_01",
            "experiment_name": "高价值客户免邮测试",
            "primary_metric": "contribution_profit",
            "treatment_revenue_lift": 0.08,
            "treatment_profit_lift": 0.24,
            "treatment_conversion_lift": 0.06,
            "treatment_return_lift": 0.003,
        },
        {
            "experiment_id": "EXP_BLANKET_DISCOUNT_01",
            "experiment_name": "全客群九折促销测试",
            "primary_metric": "contribution_profit",
            "treatment_revenue_lift": 0.12,
            "treatment_profit_lift": -0.62,
            "treatment_conversion_lift": 0.09,
            "treatment_return_lift": 0.018,
        },
        {
            "experiment_id": "EXP_WINBACK_EMAIL_01",
            "experiment_name": "沉睡客户召回邮件测试",
            "primary_metric": "contribution_profit",
            "treatment_revenue_lift": 0.01,
            "treatment_profit_lift": 0.01,
            "treatment_conversion_lift": 0.01,
            "treatment_return_lift": 0.0,
        },
    ]
    rows: list[dict] = []
    max_customers = min(len(customer_ids), 2600)
    selected = customer_ids[:max_customers]
    for definition in definitions:
        for customer_id in selected:
            assignment = (
                "Treatment"
                if _fraction(customer_id, definition["experiment_id"] + "assign") >= 0.5
                else "Control"
            )
            baseline_revenue = 18 + 170 * _fraction(
                customer_id, definition["experiment_id"] + "revenue"
            )
            baseline_margin = 0.12 + 0.18 * _fraction(
                customer_id, definition["experiment_id"] + "margin"
            )
            conversion_prob = 0.28 + 0.24 * _fraction(
                customer_id, definition["experiment_id"] + "conv"
            )
            if assignment == "Treatment":
                conversion_prob *= 1 + definition["treatment_conversion_lift"]
            converted = _fraction(customer_id, definition["experiment_id"] + "outcome") < min(
                conversion_prob, 0.95
            )
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
        pd.DataFrame(definitions).to_sql(
            "experiment_catalog", conn, if_exists="replace", index=False
        )


def experiment_catalog(db_path: str | Path) -> pd.DataFrame:
    if not table_exists(db_path, "experiment_catalog"):
        return pd.DataFrame()
    return query_df(db_path, "SELECT * FROM experiment_catalog")


def import_experiment(db_path: str | Path, frame: pd.DataFrame, name: str) -> int:
    """Load a real experiment's customer-level results and replace any earlier version."""
    if is_read_only():
        raise PermissionError("当前为只读模式，不能导入实验数据。")
    missing = [column for column in ASSIGNMENT_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError("实验数据缺少字段: " + ", ".join(missing))
    data = frame[list(ASSIGNMENT_COLUMNS)].copy()
    data["assignment"] = data["assignment"].astype(str).str.strip().str.title()
    if set(data["assignment"].unique()) != {"Control", "Treatment"}:
        raise ValueError("assignment 字段只能包含 Control 和 Treatment 两组。")
    for column in ("converted", "net_revenue", "contribution_profit", "returned"):
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0.0)
    data["experiment_name"] = name
    data["primary_metric"] = "contribution_profit"
    data["data_status"] = "Verified"
    experiment_ids = data["experiment_id"].astype(str).unique().tolist()
    catalog_rows = pd.DataFrame(
        {
            "experiment_id": experiment_ids,
            "experiment_name": name,
            "primary_metric": "contribution_profit",
        }
    )
    with connect(db_path) as conn:
        if table_exists(db_path, "experiment_assignments"):
            placeholders = ",".join("?" for _ in experiment_ids)
            conn.execute(
                f"DELETE FROM experiment_assignments WHERE experiment_id IN ({placeholders})",
                experiment_ids,
            )
            conn.execute(
                f"DELETE FROM experiment_catalog WHERE experiment_id IN ({placeholders})",
                experiment_ids,
            )
        data.to_sql("experiment_assignments", conn, if_exists="append", index=False)
        catalog_rows.to_sql("experiment_catalog", conn, if_exists="append", index=False)
    return len(data)


def _bootstrap_difference(
    control: np.ndarray, treatment: np.ndarray, seed: int = 42
) -> tuple[float, float, float]:
    if len(control) == 0 or len(treatment) == 0:
        return 0.0, 0.0, 0.0
    if max(len(control), len(treatment)) > MAX_BOOTSTRAP_ROWS:
        # Resampling millions of rows would exhaust memory, and at this size the normal
        # approximation gives the same answer.
        difference = float(treatment.mean() - control.mean())
        error = math.sqrt(
            float(control.var(ddof=1)) / len(control) + float(treatment.var(ddof=1)) / len(treatment)
        )
        if error == 0:
            return difference, difference, float(difference > 0)
        return (
            difference - Z_ALPHA * error,
            difference + Z_ALPHA * error,
            NormalDist().cdf(difference / error),
        )
    rng = np.random.default_rng(seed)
    n_boot = 1200
    control_idx = rng.integers(0, len(control), size=(n_boot, len(control)))
    treatment_idx = rng.integers(0, len(treatment), size=(n_boot, len(treatment)))
    diffs = treatment[treatment_idx].mean(axis=1) - control[control_idx].mean(axis=1)
    return (
        float(np.quantile(diffs, 0.025)),
        float(np.quantile(diffs, 0.975)),
        float((diffs > 0).mean()),
    )


def sample_ratio_p_value(control_n: int, treatment_n: int) -> float:
    """Chi-square test of a 50/50 split. A tiny p-value means assignment itself is broken."""
    total = control_n + treatment_n
    if total == 0:
        return 1.0
    expected = total / 2
    statistic = (control_n - expected) ** 2 / expected + (treatment_n - expected) ** 2 / expected
    return float(math.erfc(math.sqrt(statistic / 2)))


def minimum_detectable_lift(control: np.ndarray, treatment: np.ndarray) -> float:
    """Smallest true difference this sample would catch with 80% power at a 5% error rate."""
    if len(control) < 2 or len(treatment) < 2:
        return 0.0
    standard_error = math.sqrt(
        float(control.var(ddof=1)) / len(control) + float(treatment.var(ddof=1)) / len(treatment)
    )
    return (Z_ALPHA + Z_POWER) * standard_error


def required_sample_per_arm(control: np.ndarray, treatment: np.ndarray, effect: float) -> int:
    """Customers needed in each arm to detect a given effect with 80% power."""
    if effect <= 0 or len(control) < 2 or len(treatment) < 2:
        return 0
    pooled = (float(control.var(ddof=1)) + float(treatment.var(ddof=1))) / 2
    return math.ceil(2 * (Z_ALPHA + Z_POWER) ** 2 * pooled / effect**2)


def _decide(primary: pd.Series, revenue: pd.Series, returns: pd.Series) -> tuple[str, str, bool]:
    """Call a result only when the evidence supports it.

    A negative point estimate inside a wide interval is not proof of harm, so noise now
    reads as inconclusive rather than as a confident rejection.
    """
    returns_ok = bool(returns["absolute_lift"] <= RETURN_GUARDRAIL)
    harmful = (
        primary["ci_high"] < 0 or primary["probability_positive"] <= HARM_PROBABILITY
    )
    if harmful:
        reason = "收入增长但利润受损" if revenue["absolute_lift"] > 0 else "利润明显下降"
        return "stop", f"不建议推广：{reason}", False
    if not returns_ok:
        return "stop", "不建议推广：退货率超过护栏", False
    if primary["ci_low"] > 0:
        return "ship", "建议推广", True
    if primary["probability_positive"] >= CONFIDENT_PROBABILITY:
        return "pilot", "方向向好：先小范围推广并继续观察", True
    return "inconclusive", "证据不足：继续实验，暂不下结论", True


def analyze_experiment(
    db_path: str | Path, experiment_id: str
) -> tuple[ExperimentSummary, pd.DataFrame, pd.DataFrame]:
    data = query_df(
        db_path,
        "SELECT * FROM experiment_assignments WHERE experiment_id=?",
        (experiment_id,),
    )
    if data.empty:
        raise ValueError(f"未找到实验 {experiment_id}")
    metrics = []
    for metric in ("converted", "net_revenue", "contribution_profit", "returned"):
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
                "relative_lift": (treatment_mean - control_mean) / abs(control_mean)
                if control_mean
                else np.nan,
                "ci_low": low,
                "ci_high": high,
                "probability_positive": probability,
            }
        )
    metric_table = pd.DataFrame(metrics)
    primary = metric_table.loc[metric_table["metric"] == "contribution_profit"].iloc[0]
    revenue = metric_table.loc[metric_table["metric"] == "net_revenue"].iloc[0]
    returns = metric_table.loc[metric_table["metric"] == "returned"].iloc[0]
    code, decision, guardrail_ok = _decide(primary, revenue, returns)

    control = data.loc[data["assignment"] == "Control", "contribution_profit"].to_numpy(float)
    treatment = data.loc[data["assignment"] == "Treatment", "contribution_profit"].to_numpy(float)
    meaningful_effect = max(abs(float(primary["control_mean"])) * 0.05, 1e-6)
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
        decision_code=code,
        sample_ratio_p=sample_ratio_p_value(len(control), len(treatment)),
        minimum_detectable_lift=minimum_detectable_lift(control, treatment),
        required_sample_per_arm=required_sample_per_arm(control, treatment, meaningful_effect),
        data_status=str(data["data_status"].iloc[0]),
    )
    balance = data.groupby("assignment", as_index=False).agg(
        customers=("customer_id", "nunique"),
        conversion_rate=("converted", "mean"),
        return_rate=("returned", "mean"),
    )
    return summary, metric_table, balance
