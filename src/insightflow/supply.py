"""Inventory policy from observed demand: how much to hold, when to order, what is at risk."""

from __future__ import annotations

from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from .warehouse import query_df

LOOKBACK_DAYS = 90
LEAD_TIME_VARIATION = 0.20


def _daily_demand(db_path: str | Path, days: int) -> tuple[pd.DataFrame, pd.Timestamp]:
    last = pd.Timestamp(query_df(db_path, "SELECT MAX(date) FROM v_sales").iloc[0, 0])
    start = (last - pd.Timedelta(days=days - 1)).date().isoformat()
    frame = query_df(
        db_path,
        """
        SELECT stock_code, date, SUM(quantity) AS units,
               SUM(net_revenue) AS revenue, SUM(contribution_profit) AS profit
        FROM v_sales WHERE date >= ?
        GROUP BY stock_code, date
        """,
        (start,),
    )
    return frame, last


def inventory_policy(
    db_path: str | Path,
    *,
    service_level: float = 0.95,
    review_days: int = 14,
) -> pd.DataFrame:
    """Compute ABC-XYZ class, safety stock, reorder point and the profit a stockout would cost."""
    snapshot = query_df(db_path, "SELECT * FROM inventory_snapshot")
    if snapshot.empty:
        return snapshot
    demand, last = _daily_demand(db_path, LOOKBACK_DAYS)
    z_score = NormalDist().inv_cdf(min(max(service_level, 0.5), 0.999))

    wide = demand.pivot_table(
        index="date", columns="stock_code", values="units", aggfunc="sum", fill_value=0.0
    ).reindex(
        pd.date_range(last - pd.Timedelta(days=LOOKBACK_DAYS - 1), last).strftime("%Y-%m-%d"),
        fill_value=0.0,
    )
    mean_daily = wide.mean()
    spread_daily = wide.std(ddof=1)
    weekly = wide.groupby(np.arange(len(wide)) // 7).sum()
    variation = weekly.std(ddof=1) / weekly.mean().replace(0, np.nan)
    totals = demand.groupby("stock_code")[["revenue", "profit"]].sum()

    policy = snapshot.set_index("stock_code").copy()
    policy["daily_demand"] = mean_daily.reindex(policy.index).fillna(0.0)
    policy["demand_spread"] = spread_daily.reindex(policy.index).fillna(0.0)
    policy["demand_cv"] = variation.reindex(policy.index)
    policy["revenue_90d"] = totals["revenue"].reindex(policy.index).fillna(0.0)
    policy["profit_90d"] = totals["profit"].reindex(policy.index).fillna(0.0)

    lead = policy["supplier_lead_days"].astype(float).clip(lower=1)
    lead_spread = lead * LEAD_TIME_VARIATION
    uncertainty = np.sqrt(
        lead * policy["demand_spread"] ** 2 + policy["daily_demand"] ** 2 * lead_spread**2
    )
    policy["safety_stock"] = np.ceil(z_score * uncertainty)
    policy["reorder_level"] = np.ceil(policy["daily_demand"] * lead + policy["safety_stock"])
    on_hand = policy["inventory_on_hand"].astype(float)
    policy["recommended_order"] = (
        np.ceil(policy["reorder_level"] + policy["daily_demand"] * review_days - on_hand)
        .clip(lower=0)
        .where(on_hand <= policy["reorder_level"], 0.0)
    )
    cover = (on_hand / policy["daily_demand"].replace(0, np.nan)).fillna(np.inf)
    policy["days_of_cover"] = cover.replace(np.inf, 999.0)
    policy["stockout_date"] = [
        (last + pd.Timedelta(days=int(days))).date().isoformat() if days < 365 else None
        for days in policy["days_of_cover"]
    ]
    gap_days = (lead - cover).clip(lower=0).replace(np.inf, 0.0)
    daily_profit = policy["profit_90d"] / LOOKBACK_DAYS
    policy["margin_at_risk"] = (gap_days * daily_profit).clip(lower=0)

    ranked = policy["revenue_90d"].sort_values(ascending=False)
    share = ranked.cumsum() / max(float(ranked.sum()), 1.0)
    abc = pd.Series(np.select([share <= 0.8, share <= 0.95], ["A", "B"], default="C"), share.index)
    policy["abc_class"] = abc.reindex(policy.index)
    policy["xyz_class"] = np.select(
        [policy["demand_cv"] <= 0.5, policy["demand_cv"] <= 1.0], ["X", "Y"], default="Z"
    )
    policy["policy_class"] = policy["abc_class"] + policy["xyz_class"]
    return policy.reset_index().sort_values("margin_at_risk", ascending=False)


def policy_matrix(policy: pd.DataFrame) -> pd.DataFrame:
    """Summarise revenue across the nine ABC-XYZ cells."""
    grouped = policy.pivot_table(
        index="abc_class",
        columns="xyz_class",
        values="revenue_90d",
        aggfunc="sum",
        fill_value=0.0,
    )
    return grouped.reindex(index=["A", "B", "C"], columns=["X", "Y", "Z"], fill_value=0.0)
