"""Price-volume-mix bridge between two periods.

The bridge explains the whole change in contribution profit at product level. Every
component is computed from one identity, so the steps always add up to the real change;
a test enforces that to the penny. Sales are read at list price so that price rises and
discounting show up as separate decisions.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .metrics import FilterSpec, filter_clause, kpi_summary, previous_period
from .warehouse import query_df

STEP_LABELS = {
    "volume": ("销量规模", "Volume"),
    "mix": ("商品结构", "Product mix"),
    "price": ("标价变化", "List price"),
    "discount": ("折扣力度", "Discounting"),
    "unit_cost": ("单位成本", "Unit cost"),
    "new_products": ("新增商品", "New products"),
    "lost_products": ("停售商品", "Lost products"),
    "shipping": ("物流费用", "Shipping"),
    "payment": ("支付费用", "Payment fees"),
    "marketing": ("营销费用", "Marketing"),
    "returns": ("退货影响", "Returns"),
}


def _product_period(db_path: str | Path, filters: FilterSpec) -> pd.DataFrame:
    where, params = filter_clause(filters)
    frame = query_df(
        db_path,
        f"""
        SELECT stock_code,
               SUM(quantity) AS units,
               SUM(gross_revenue) AS gross,
               SUM(discount_amount) AS discount,
               SUM(cogs) AS cogs
        FROM v_sales
        WHERE {where}
        GROUP BY stock_code
        HAVING units > 0
        """,
        params,
    )
    return frame.set_index("stock_code")


def price_volume_mix(
    db_path: str | Path, filters: FilterSpec, *, language: str = "zh-CN"
) -> pd.DataFrame:
    """Return the ordered bridge from last period's profit to this period's."""
    previous_filters = previous_period(filters)
    current = kpi_summary(db_path, filters)
    previous = kpi_summary(db_path, previous_filters)
    now = _product_period(db_path, filters)
    before = _product_period(db_path, previous_filters)

    common = now.index.intersection(before.index)
    q1 = now.loc[common, "units"].astype(float)
    q0 = before.loc[common, "units"].astype(float)
    list1, list0 = now.loc[common, "gross"] / q1, before.loc[common, "gross"] / q0
    disc1, disc0 = now.loc[common, "discount"] / q1, before.loc[common, "discount"] / q0
    cost1, cost0 = now.loc[common, "cogs"] / q1, before.loc[common, "cogs"] / q0
    margin0 = list0 - disc0 - cost0

    growth = float(q1.sum() / q0.sum()) - 1 if float(q0.sum()) > 0 else 0.0
    volume = float((q0 * growth * margin0).sum())
    mix = float(((q1 - q0 * (1 + growth)) * margin0).sum())
    price = float((q1 * (list1 - list0)).sum())
    discount = float(-(q1 * (disc1 - disc0)).sum())
    unit_cost = float(-(q1 * (cost1 - cost0)).sum())

    def sale_margin(frame: pd.DataFrame) -> float:
        return float((frame["gross"] - frame["discount"] - frame["cogs"]).sum())

    new_products = sale_margin(now.loc[now.index.difference(before.index)])
    lost_products = -sale_margin(before.loc[before.index.difference(now.index)])

    def return_impact(kpi: dict[str, float]) -> float:
        return kpi["returned_cogs"] - kpi["returns_value"] - kpi["return_processing_cost"]

    steps = {
        "volume": volume,
        "mix": mix,
        "price": price,
        "discount": discount,
        "unit_cost": unit_cost,
        "new_products": new_products,
        "lost_products": lost_products,
        "shipping": previous["shipping_cost"] - current["shipping_cost"],
        "payment": previous["payment_fee"] - current["payment_fee"],
        "marketing": previous["marketing_cost"] - current["marketing_cost"],
        "returns": return_impact(current) - return_impact(previous),
    }
    position = 0 if language == "zh-CN" else 1
    rows = [
        {"step": key, "label": STEP_LABELS[key][position], "impact": value}
        for key, value in steps.items()
    ]
    bridge = pd.DataFrame(rows)
    bridge.attrs["start"] = previous["contribution_profit"]
    bridge.attrs["end"] = current["contribution_profit"]
    bridge.attrs["unexplained"] = float(
        current["contribution_profit"]
        - previous["contribution_profit"]
        - np.sum(bridge["impact"].to_numpy())
    )
    return bridge
