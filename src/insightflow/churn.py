"""Customer return prediction, trained and graded on separate points in time.

Features are taken at a past cutoff and the label is whether the customer bought in the
following 90 days. The model trains on an older cutoff and is graded on a newer one, so
the reported AUC is an honest out-of-time score. If it shows no skill, the page says so
instead of ranking customers on noise.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .warehouse import database_version, query_df

HORIZON_DAYS = 90
FEATURES = ["log_recency", "log_frequency", "log_value", "tenure_years", "discount_share"]
MIN_CUSTOMERS = 60
USEFUL_AUC = 0.60


@dataclass(frozen=True)
class ChurnModel:
    coefficients: np.ndarray
    means: np.ndarray
    scales: np.ndarray
    auc: float
    top_decile_lift: float
    calibration: pd.DataFrame
    train_customers: int
    test_customers: int
    cutoff: str

    @property
    def useful(self) -> bool:
        return self.auc >= USEFUL_AUC


def _customer_features(db_path: str | Path, cutoff: str) -> pd.DataFrame:
    frame = query_df(
        db_path,
        """
        SELECT customer_id,
               MIN(date) AS first_date,
               MAX(date) AS last_date,
               COUNT(DISTINCT invoice_no) AS orders,
               SUM(net_revenue) AS revenue,
               AVG(discount_rate) AS discount_share
        FROM v_sales
        WHERE date <= ? AND customer_id IS NOT NULL
        GROUP BY customer_id
        """,
        (cutoff,),
    )
    if frame.empty:
        return frame
    at = pd.Timestamp(cutoff)
    frame["recency_days"] = (at - pd.to_datetime(frame["last_date"])).dt.days
    frame["tenure_years"] = (at - pd.to_datetime(frame["first_date"])).dt.days / 365.25
    frame["log_recency"] = np.log1p(frame["recency_days"])
    frame["log_frequency"] = np.log1p(frame["orders"])
    frame["log_value"] = np.log1p(frame["revenue"].clip(lower=0))
    return frame


def _labels(db_path: str | Path, start: str, end: str) -> set[str]:
    buyers = query_df(
        db_path,
        """
        SELECT DISTINCT customer_id FROM v_sales
        WHERE date > ? AND date <= ? AND customer_id IS NOT NULL
        """,
        (start, end),
    )
    return set(buyers["customer_id"].astype(str))


def _fit_logistic(x: np.ndarray, y: np.ndarray, *, ridge: float = 1.0) -> np.ndarray:
    """Newton-Raphson logistic regression with an L2 penalty on the slopes."""
    design = np.column_stack([np.ones(len(x)), x])
    beta = np.zeros(design.shape[1])
    penalty = np.eye(design.shape[1]) * ridge
    penalty[0, 0] = 0.0
    for _ in range(40):
        probability = 1 / (1 + np.exp(-np.clip(design @ beta, -30, 30)))
        weight = np.clip(probability * (1 - probability), 1e-6, None)
        gradient = design.T @ (y - probability) - penalty @ beta
        hessian = (design * weight[:, None]).T @ design + penalty
        step = np.linalg.solve(hessian, gradient)
        beta = beta + step
        if float(np.abs(step).max()) < 1e-6:
            break
    return beta


def _predict(model_beta: np.ndarray, x: np.ndarray) -> np.ndarray:
    design = np.column_stack([np.ones(len(x)), x])
    return 1 / (1 + np.exp(-np.clip(design @ model_beta, -30, 30)))


def area_under_curve(y: np.ndarray, score: np.ndarray) -> float:
    positives = int(y.sum())
    negatives = len(y) - positives
    if positives == 0 or negatives == 0:
        return 0.5
    ranks = pd.Series(score).rank().to_numpy()
    return float((ranks[y == 1].sum() - positives * (positives + 1) / 2) / (positives * negatives))


def _standardize(frame: pd.DataFrame, means, scales) -> np.ndarray:
    values = frame[FEATURES].astype(float).fillna(0.0).to_numpy()
    return (values - means) / scales


@lru_cache(maxsize=8)
def _train_cached(db_path: str, version: tuple[int, int, int, int]) -> ChurnModel | None:
    del version
    last = pd.Timestamp(query_df(db_path, "SELECT MAX(date) FROM v_sales").iloc[0, 0])
    test_cutoff = (last - pd.Timedelta(days=HORIZON_DAYS)).date().isoformat()
    train_cutoff = (last - pd.Timedelta(days=2 * HORIZON_DAYS)).date().isoformat()

    train = _customer_features(db_path, train_cutoff)
    test = _customer_features(db_path, test_cutoff)
    if len(train) < MIN_CUSTOMERS or len(test) < MIN_CUSTOMERS:
        return None
    train_buyers = _labels(db_path, train_cutoff, test_cutoff)
    test_buyers = _labels(db_path, test_cutoff, last.date().isoformat())
    y_train = train["customer_id"].astype(str).isin(train_buyers).to_numpy(dtype=float)
    y_test = test["customer_id"].astype(str).isin(test_buyers).to_numpy(dtype=float)
    if len(set(y_train)) < 2 or len(set(y_test)) < 2:
        return None

    raw = train[FEATURES].astype(float).fillna(0.0).to_numpy()
    means = raw.mean(axis=0)
    scales = np.where(raw.std(axis=0) > 0, raw.std(axis=0), 1.0)
    beta = _fit_logistic((raw - means) / scales, y_train)
    scores = _predict(beta, _standardize(test, means, scales))

    order = np.argsort(-scores)
    top = order[: max(1, len(order) // 10)]
    base_rate = float(y_test.mean())
    lift = float(y_test[top].mean() / base_rate) if base_rate else 1.0
    bins = pd.qcut(pd.Series(scores), 5, labels=False, duplicates="drop")
    calibration = (
        pd.DataFrame({"bin": bins, "predicted": scores, "actual": y_test})
        .groupby("bin", as_index=False)
        .agg(predicted=("predicted", "mean"), actual=("actual", "mean"), customers=("actual", "size"))
    )
    return ChurnModel(
        coefficients=beta,
        means=means,
        scales=scales,
        auc=area_under_curve(y_test, scores),
        top_decile_lift=lift,
        calibration=calibration,
        train_customers=len(train),
        test_customers=len(test),
        cutoff=test_cutoff,
    )


def train_churn_model(db_path: str | Path) -> ChurnModel | None:
    path = str(Path(db_path).resolve())
    return _train_cached(path, database_version(path))


def score_customers(db_path: str | Path) -> pd.DataFrame:
    """Score every known customer as of the latest date in the warehouse."""
    model = train_churn_model(db_path)
    if model is None:
        return pd.DataFrame()
    last = str(query_df(db_path, "SELECT MAX(date) FROM v_sales").iloc[0, 0])
    current = _customer_features(db_path, last)
    if current.empty:
        return current
    probability = _predict(model.coefficients, _standardize(current, model.means, model.scales))
    current["return_probability"] = probability
    current["model_churn_risk"] = 1 - probability
    return current[["customer_id", "return_probability", "model_churn_risk"]]
