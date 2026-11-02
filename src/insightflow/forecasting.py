from __future__ import annotations

import calendar
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .metrics import FilterSpec, monthly_trend
from .warehouse import query_df

SEASON = 12
RATIO_METRICS = {"gross_margin", "contribution_margin", "discount_rate", "cancellation_rate"}
NON_NEGATIVE_METRICS = {"revenue", "orders", "active_customers", "units", "gross_revenue"}
ENSEMBLE = "ensemble_top3"


@dataclass
class ForecastResult:
    metric: str
    selected_model: str
    leaderboard: pd.DataFrame
    history: pd.DataFrame
    forecast: pd.DataFrame
    dropped_partial_month: str | None = None
    skill_vs_naive: float | None = None


def _holt(values: np.ndarray, horizon: int, alpha: float, beta: float, phi: float) -> np.ndarray:
    """Holt's linear method with a damped trend, so forecasts level off instead of running away."""
    level = float(values[0])
    trend = float(values[1] - values[0]) if len(values) > 1 else 0.0
    for value in values[1:]:
        previous = level
        level = alpha * float(value) + (1 - alpha) * (level + phi * trend)
        trend = beta * (level - previous) + (1 - beta) * phi * trend
    damping = np.cumsum(phi ** np.arange(1, horizon + 1))
    return level + damping * trend


def _holt_winters(
    values: np.ndarray, horizon: int, alpha: float, beta: float, gamma: float
) -> np.ndarray:
    """Additive Holt-Winters seeded from the first two seasonal cycles."""
    first, second = values[:SEASON], values[SEASON : 2 * SEASON]
    level = float(first.mean())
    trend = float((second.mean() - first.mean()) / SEASON)
    season = list(first - first.mean())
    for index, value in enumerate(values):
        previous = level
        slot = season[index % SEASON]
        level = alpha * (float(value) - slot) + (1 - alpha) * (level + trend)
        trend = beta * (level - previous) + (1 - beta) * trend
        season[index % SEASON] = gamma * (float(value) - level) + (1 - gamma) * slot
    start = len(values)
    return np.array(
        [level + (step + 1) * trend + season[(start + step) % SEASON] for step in range(horizon)]
    )


def _forecast_values(values: np.ndarray, model: str, horizon: int) -> np.ndarray:
    if len(values) == 0:
        return np.zeros(horizon)
    if model == "naive":
        return np.repeat(values[-1], horizon)
    if model == "moving_average":
        return np.repeat(values[-min(3, len(values)) :].mean(), horizon)
    if model == "drift":
        slope = (values[-1] - values[0]) / max(len(values) - 1, 1)
        return np.array([values[-1] + slope * (i + 1) for i in range(horizon)])
    if model == "linear_trend":
        x = np.arange(len(values), dtype=float)
        slope, intercept = np.polyfit(x, values, 1) if len(values) >= 2 else (0.0, values[-1])
        future_x = np.arange(len(values), len(values) + horizon, dtype=float)
        return intercept + slope * future_x
    if model == "seasonal_naive":
        if len(values) < SEASON:
            return np.repeat(values[-1], horizon)
        season = values[-SEASON:]
        return np.array([season[i % SEASON] for i in range(horizon)])
    if model == "seasonal_drift":
        if len(values) < SEASON + 1:
            return np.repeat(values[-1], horizon)
        season = values[-SEASON:]
        step = np.mean(values[SEASON:] - values[:-SEASON]) / SEASON
        return np.array(
            [season[i % SEASON] + step * SEASON * (i // SEASON + 1) for i in range(horizon)]
        )
    if model == "holt_damped":
        return _holt(values, horizon, alpha=0.5, beta=0.2, phi=0.9)
    if model == "holt_winters":
        if len(values) < 2 * SEASON:
            return np.repeat(values[-1], horizon)
        return _holt_winters(values, horizon, alpha=0.35, beta=0.05, gamma=0.25)
    if model.startswith("exp_smoothing_"):
        alpha = float(model.rsplit("_", 1)[-1])
        level = float(values[0])
        for value in values[1:]:
            level = alpha * float(value) + (1 - alpha) * level
        return np.repeat(level, horizon)
    raise ValueError(f"未知预测模型: {model}")


def _backtest(values: np.ndarray, model: str, holdout: int) -> dict[str, float]:
    absolute_errors: list[float] = []
    absolute_pct: list[float] = []
    symmetric_pct: list[float] = []
    squared: list[float] = []
    signed_errors: list[float] = []
    actuals: list[float] = []
    start = len(values) - holdout
    for idx in range(start, len(values)):
        train = values[:idx]
        if len(train) < 3:
            continue
        pred = float(_forecast_values(train, model, 1)[0])
        actual = float(values[idx])
        err = pred - actual
        absolute_errors.append(abs(err))
        absolute_pct.append(abs(err) / max(abs(actual), 1.0))
        symmetric_pct.append(2 * abs(err) / max(abs(actual) + abs(pred), 1.0))
        squared.append(err**2)
        signed_errors.append(err)
        actuals.append(actual)
    if not absolute_errors:
        return {
            "mae": np.inf,
            "mape": np.inf,
            "smape": np.inf,
            "wape": np.inf,
            "mase": np.inf,
            "rmse": np.inf,
            "bias": np.inf,
            "n_backtest": 0,
        }
    naive_scale = float(np.mean(np.abs(np.diff(values[:start])))) if start >= 3 else 0.0
    mae = float(np.mean(absolute_errors))
    return {
        "mae": mae,
        "mape": float(np.mean(absolute_pct)),
        "smape": float(np.mean(symmetric_pct)),
        "wape": float(np.sum(absolute_errors) / max(np.sum(np.abs(actuals)), 1.0)),
        "mase": mae / naive_scale if naive_scale > 0 else np.nan,
        "rmse": float(np.sqrt(np.mean(squared))),
        "bias": float(np.mean(signed_errors)),
        "n_backtest": len(absolute_errors),
    }


def _ensemble_backtest(
    values: np.ndarray, members: list[str], holdout: int, metrics_like: dict[str, float]
) -> dict[str, float]:
    start = len(values) - holdout
    errors: list[float] = []
    actuals: list[float] = []
    for idx in range(start, len(values)):
        train = values[:idx]
        if len(train) < 3:
            continue
        pred = float(np.mean([_forecast_values(train, m, 1)[0] for m in members]))
        errors.append(pred - float(values[idx]))
        actuals.append(float(values[idx]))
    if not errors:
        return dict(metrics_like)
    array = np.array(errors)
    naive_scale = float(np.mean(np.abs(np.diff(values[:start])))) if start >= 3 else 0.0
    mae = float(np.mean(np.abs(array)))
    return {
        "mae": mae,
        "mape": float(np.mean(np.abs(array) / np.maximum(np.abs(actuals), 1.0))),
        "smape": float(
            np.mean(
                2
                * np.abs(array)
                / np.maximum(np.abs(actuals) + np.abs(array + np.array(actuals)), 1.0)
            )
        ),
        "wape": float(np.sum(np.abs(array)) / max(np.sum(np.abs(actuals)), 1.0)),
        "mase": mae / naive_scale if naive_scale > 0 else np.nan,
        "rmse": float(np.sqrt(np.mean(array**2))),
        "bias": float(np.mean(array)),
        "n_backtest": len(errors),
    }


def _candidate_models(length: int) -> list[str]:
    models = [
        "naive",
        "moving_average",
        "drift",
        "linear_trend",
        "exp_smoothing_0.3",
        "exp_smoothing_0.6",
        "holt_damped",
    ]
    if length >= SEASON + 6:
        models.extend(["seasonal_naive", "seasonal_drift"])
    if length >= 2 * SEASON + 3:
        models.append("holt_winters")
    return models


def _complete_history(db_path: str | Path, history: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
    """Drop a final month the data has not finished, which would read as a collapse."""
    last_month = str(history.iloc[-1]["month"])
    last_date = query_df(
        db_path, "SELECT MAX(date) AS d FROM v_sales WHERE month = ?", (last_month,)
    ).iloc[0, 0]
    if last_date is None:
        return history, None
    stamp = pd.Timestamp(last_date)
    month_days = calendar.monthrange(stamp.year, stamp.month)[1]
    if stamp.day <= month_days - 3 and len(history) > 6:
        return history.iloc[:-1].copy(), last_month
    return history, None


def forecast_metric(
    db_path: str | Path,
    metric: str,
    *,
    horizon: int = 3,
    filters: FilterSpec | None = None,
) -> ForecastResult:
    trend = monthly_trend(db_path, filters or FilterSpec())
    if metric not in trend.columns:
        raise ValueError(f"月度趋势中不存在指标: {metric}")
    history = trend[["month", metric]].dropna().copy()
    if len(history) < 6:
        raise ValueError("至少需要6个月数据才能进行模型比较")
    history, dropped = _complete_history(db_path, history)
    values = history[metric].astype(float).to_numpy()

    holdout = min(6, max(3, len(values) // 4))
    rows = [
        {"model": model, **_backtest(values, model, holdout)}
        for model in _candidate_models(len(values))
    ]
    ranked = sorted(rows, key=lambda row: (row["wape"], row["smape"], row["rmse"]))
    members = [row["model"] for row in ranked[:3]]
    rows.append(
        {"model": ENSEMBLE, **_ensemble_backtest(values, members, holdout, ranked[0])}
    )
    leaderboard = (
        pd.DataFrame(rows)
        .sort_values(["wape", "smape", "rmse"], ascending=True)
        .reset_index(drop=True)
    )
    selected = str(leaderboard.iloc[0]["model"])
    predictions = (
        np.mean([_forecast_values(values, m, horizon) for m in members], axis=0)
        if selected == ENSEMBLE
        else _forecast_values(values, selected, horizon)
    )
    residual_rmse = float(leaderboard.iloc[0]["rmse"])
    last_month = pd.Period(str(history.iloc[-1]["month"]), freq="M")
    future_months = [(last_month + i).strftime("%Y-%m") for i in range(1, horizon + 1)]
    spread = residual_rmse * np.sqrt(np.arange(1, horizon + 1))
    forecast = pd.DataFrame(
        {
            "month": future_months,
            "forecast": predictions,
            "lower": predictions - 1.96 * spread,
            "upper": predictions + 1.96 * spread,
            "lower_80": predictions - 1.2816 * spread,
            "upper_80": predictions + 1.2816 * spread,
        }
    )
    bounds = ["forecast", "lower", "upper", "lower_80", "upper_80"]
    if metric in RATIO_METRICS:
        forecast[bounds] = forecast[bounds].clip(0, 1)
    elif metric in NON_NEGATIVE_METRICS:
        forecast[bounds] = forecast[bounds].clip(lower=0)

    naive_wape = leaderboard.loc[leaderboard["model"] == "naive", "wape"]
    best_wape = float(leaderboard.iloc[0]["wape"])
    skill = (
        1 - best_wape / float(naive_wape.iloc[0])
        if not naive_wape.empty and float(naive_wape.iloc[0]) > 0
        else None
    )
    return ForecastResult(metric, selected, leaderboard, history, forecast, dropped, skill)


def forecast_business_metrics(db_path: str | Path, horizon: int = 3) -> dict[str, ForecastResult]:
    results: dict[str, ForecastResult] = {}
    for metric in ("revenue", "contribution_profit", "orders"):
        results[metric] = forecast_metric(db_path, metric, horizon=horizon)
    return results
