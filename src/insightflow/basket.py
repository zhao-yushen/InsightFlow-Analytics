"""Which products sell together, with lift telling real attachment from coincidence."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .metrics import FilterSpec, filter_clause
from .warehouse import query_df

MAX_ITEMS = 200


def association_rules(
    db_path: str | Path,
    filters: FilterSpec,
    *,
    level: str = "stock_code",
    min_pair_orders: int = 8,
    limit: int = 40,
) -> pd.DataFrame:
    """Return item pairs ranked by lift. A lift of 2 means twice as often as chance."""
    if level not in {"stock_code", "category"}:
        raise ValueError(f"不支持的分析层级: {level}")
    where, params = filter_clause(filters)
    lines = query_df(
        db_path,
        f"""
        SELECT DISTINCT invoice_no, {level} AS item, MAX(description) OVER (PARTITION BY {level}) AS name
        FROM v_sales
        WHERE {where}
        """,
        params,
    )
    columns = [
        "antecedent",
        "consequent",
        "antecedent_name",
        "consequent_name",
        "pair_orders",
        "support",
        "confidence",
        "lift",
    ]
    if lines.empty:
        return pd.DataFrame(columns=columns)

    baskets = lines["invoice_no"].astype("category")
    popular = lines["item"].value_counts().head(MAX_ITEMS).index
    subset = lines[lines["item"].isin(popular)]
    items = pd.Categorical(subset["item"], categories=popular)
    orders = pd.Categorical(subset["invoice_no"], categories=baskets.cat.categories)
    matrix = np.zeros((len(baskets.cat.categories), len(popular)), dtype=np.float32)
    matrix[orders.codes, items.codes] = 1.0

    total_orders = float(matrix.shape[0])
    counts = matrix.T @ matrix
    item_orders = np.diag(counts).copy()
    np.fill_diagonal(counts, 0)
    names = lines.drop_duplicates("item").set_index("item")["name"]

    rows: list[dict] = []
    left_index, right_index = np.where(counts >= min_pair_orders)
    for left, right in zip(left_index, right_index, strict=True):
        if left == right:
            continue
        together = float(counts[left, right])
        confidence = together / item_orders[left]
        expected = item_orders[right] / total_orders
        rows.append(
            {
                "antecedent": popular[left],
                "consequent": popular[right],
                "antecedent_name": names.get(popular[left], popular[left]),
                "consequent_name": names.get(popular[right], popular[right]),
                "pair_orders": int(together),
                "support": together / total_orders,
                "confidence": confidence,
                "lift": confidence / expected if expected else 0.0,
            }
        )
    if not rows:
        return pd.DataFrame(columns=columns)
    return (
        pd.DataFrame(rows, columns=columns)
        .sort_values(["lift", "pair_orders"], ascending=False)
        .head(limit)
        .reset_index(drop=True)
    )
