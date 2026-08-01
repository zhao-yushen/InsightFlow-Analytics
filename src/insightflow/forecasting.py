from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .metrics import FilterSpec, monthly_trend


@dataclass
class ForecastResult:
    metric: str
    selected_model: str
    leaderboard: pd.DataFrame
    history: pd.DataFrame
    forecast: pd.DataFrame


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
        if len(values) < 12:
            return np.repeat(values[-1], horizon)
        season = values[-12:]
        return np.array([season[i % 12] for i in range(horizon)])
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
    values = history[metric].astype(float).to_numpy()
    if len(values) < 6:
        raise ValueError("至少需要6个月数据才能进行模型比较")

    models = [
        "naive",
        "moving_average",
        "drift",
        "linear_trend",
        "exp_smoothing_0.3",
        "exp_smoothing_0.6",
    ]
    if len(values) >= 18:
        models.append("seasonal_naive")
    holdout = min(6, max(3, len(values) // 4))
    rows = []
    for model in models:
        scores = _backtest(values, model, holdout)
        rows.append({"model": model, **scores})
    leaderboard = pd.DataFrame(rows).sort_values(["wape", "smape", "rmse"], ascending=True).reset_index(drop=True)
    selected = str(leaderboard.iloc[0]["model"])
    predictions = _forecast_values(values, selected, horizon)
    residual_rmse = float(leaderboard.iloc[0]["rmse"])
    last_month = pd.Period(str(history.iloc[-1]["month"]), freq="M")
    future_months = [(last_month + i).strftime("%Y-%m") for i in range(1, horizon + 1)]
    forecast = pd.DataFrame(
        {
            "month": future_months,
            "forecast": predictions,
            "lower": [max(0.0, p - 1.96 * residual_rmse * np.sqrt(i)) for i, p in enumerate(predictions, 1)],
            "upper": [p + 1.96 * residual_rmse * np.sqrt(i) for i, p in enumerate(predictions, 1)],
        }
    )
    if metric in {"gross_margin", "contribution_margin", "discount_rate"}:
        forecast[["forecast", "lower", "upper"]] = forecast[["forecast", "lower", "upper"]].clip(0, 1)
    return ForecastResult(metric, selected, leaderboard, history, forecast)


def forecast_business_metrics(db_path: str | Path, horizon: int = 3) -> dict[str, ForecastResult]:
    results: dict[str, ForecastResult] = {}
    for metric in ("revenue", "contribution_profit", "orders"):
        results[metric] = forecast_metric(db_path, metric, horizon=horizon)
    return results
