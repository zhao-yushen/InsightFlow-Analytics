"""Price response estimated from the ledger itself, not assumed.

Each category gets a Poisson regression of weekly order counts on net price, with an
effect for every product stream and every week, so seasonal peaks and permanently popular
products cannot pass for price effects. Four choices matter:

- Order counts and a plain average of each line's net price replace units and revenue
  per unit. A wholesale order is both huge and heavily discounted, so quantity-weighted
  prices manufacture a steep "cheap means more sold" slope that is really channel mix.
  On the demo ledger that bias nearly doubled the estimate.
- Each product is followed separately in every sales stream: its channel, and whether
  the buyer is known. Streams often sit on different price lists, so pooling them turns
  a shift between streams into a false price change. On the UCI ledger anonymous web
  orders pay about twice the account price, and pooling flattened -0.60 to -0.16.
- A stream with no sale in a week takes its usual price times the product's price index
  that week, read from the streams that did sell. Promotions move every stream at once,
  and the usual price alone records quiet promotion weeks as full price with no orders,
  which pushed the demo estimates a full point too steep.
- The Poisson form keeps weeks with no sale. Taking logs would drop them and flatten
  the slope, because low-demand weeks disappear from the sample.

Errors are clustered by product, since one product's weeks are not independent draws;
on real data that widens them three to five times. The result is then shrunk toward
the category prior in proportion to its uncertainty: thin or flat-priced data stays
close to the prior, rich data speaks for itself, and every output states which of the
two carried it.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .metrics import FilterSpec, filter_clause
from .warehouse import database_version, query_df

PRIOR_SD = 0.5
MIN_ORDERS = 150
MIN_PRICE_VARIATION = 0.004
MAX_ITERATIONS = 40
SCALE_PASSES = 6
MAX_UNITS = 8000
Z_95 = 1.96


def weekly_price_panel(db_path: str | Path, filters: FilterSpec) -> pd.DataFrame:
    where, params = filter_clause(filters.undated())
    return query_df(
        db_path,
        f"""
        SELECT category, stock_code,
               channel || CASE WHEN customer_id IS NULL THEN ' anonymous' ELSE '' END AS stream,
               STRFTIME('%Y-%W', date) AS week,
               COUNT(DISTINCT invoice_no) AS orders,
               AVG(unit_price * (1 - discount_rate)) AS net_price,
               SUM(net_revenue) AS revenue,
               AVG(price_elasticity) AS prior_elasticity
        FROM v_sales
        WHERE {where}
        GROUP BY category, stock_code, stream, week
        HAVING net_price > 0
        """,
        params,
    )


def _poisson_slope(group: pd.DataFrame) -> tuple[float, float] | None:
    """Fit orders ~ product stream + week + log price and return the slope and its error."""
    keys = ["stock_code", "stream"]
    busiest = group.groupby(keys)["orders"].sum().nlargest(MAX_UNITS)
    if len(busiest) == MAX_UNITS:
        group = group.merge(busiest.index.to_frame(index=False), on=keys)
    orders = group.pivot_table(index=keys, columns="week", values="orders", aggfunc="sum").fillna(0.0)
    prices = group.pivot_table(index=keys, columns="week", values="net_price", aggfunc="mean")
    seen = prices.reindex(index=orders.index, columns=orders.columns).to_numpy(float)
    products = pd.factorize(orders.index.get_level_values("stock_code"))[0]
    # A week without a sale shows no price. Promotions and list changes move a product in
    # every stream at once, so the week's price index, read from the streams that did sell,
    # is applied to this stream's usual price. Using the usual price alone would turn every
    # quiet promotion week into "full price, no orders" and steepen the slope.
    usual = np.nanmedian(seen, axis=1, keepdims=True)
    codes = orders.index.get_level_values("stock_code")
    index = pd.DataFrame(seen / usual, index=codes).groupby(level=0).mean()
    weekly_index = index.reindex(codes).to_numpy(float)
    filled = np.where(np.isnan(seen), usual * weekly_index, seen)
    filled = np.where(np.isnan(filled), usual, filled)
    y = orders.to_numpy(float)
    log_price = np.log(filled)
    log_price = log_price - log_price.mean(axis=1, keepdims=True)
    if float(log_price.std()) < MIN_PRICE_VARIATION:
        return None

    beta = 0.0
    row_scale = np.ones(y.shape[0])
    column_scale = np.ones(y.shape[1])
    within = log_price
    mean = y
    for _ in range(MAX_ITERATIONS):
        rate = np.exp(beta * log_price)
        for _ in range(SCALE_PASSES):
            row_scale = y.sum(axis=1) / np.maximum((rate * column_scale).sum(axis=1), 1e-12)
            column_scale = y.sum(axis=0) / np.maximum(
                (rate * row_scale[:, None]).sum(axis=0), 1e-12
            )
        mean = row_scale[:, None] * column_scale * rate
        weighted = mean * log_price
        row_mean = weighted.sum(axis=1, keepdims=True) / np.maximum(
            mean.sum(axis=1, keepdims=True), 1e-12
        )
        column_mean = weighted.sum(axis=0, keepdims=True) / np.maximum(
            mean.sum(axis=0, keepdims=True), 1e-12
        )
        within = log_price - row_mean - column_mean + weighted.sum() / max(mean.sum(), 1e-12)
        curvature = float((mean * within**2).sum())
        if curvature < 1e-9:
            return None
        step = float(((y - mean) * within).sum()) / curvature
        beta += float(np.clip(step, -1.0, 1.0))
        if abs(step) < 1e-5:
            break
    curvature = float((mean * within**2).sum())
    # Sandwich error: orders vary more than a pure Poisson process would.
    score = (y - mean) * within
    independent = float(np.sqrt((score**2).sum()) / curvature)
    clusters = int(products.max()) + 1
    if clusters < 2:
        return beta, independent
    by_product = np.bincount(products, weights=score.sum(axis=1), minlength=clusters)
    correction = clusters / (clusters - 1)
    clustered = float(np.sqrt(correction * (by_product**2).sum()) / curvature)
    # With few products the clustered form is itself unreliable, so it may only widen.
    return beta, max(clustered, independent)


def _estimate(db_path: str, filters: FilterSpec) -> pd.DataFrame:
    panel = weekly_price_panel(db_path, filters)
    columns = [
        "category",
        "observations",
        "estimate",
        "standard_error",
        "prior",
        "elasticity",
        "data_weight",
        "posterior_sd",
        "basis",
        "revenue",
    ]
    if panel.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict] = []
    for category, group in panel.groupby("category"):
        revenue = float(group["revenue"].sum())
        prior = float(np.average(group["prior_elasticity"], weights=group["orders"]))
        total_orders = int(group["orders"].sum())
        fitted = _poisson_slope(group) if total_orders >= MIN_ORDERS else None
        if fitted is None:
            rows.append(
                {
                    "category": category,
                    "observations": total_orders,
                    "estimate": np.nan,
                    "standard_error": np.nan,
                    "prior": prior,
                    "elasticity": prior,
                    "data_weight": 0.0,
                    "posterior_sd": PRIOR_SD,
                    "basis": "prior",
                    "revenue": revenue,
                }
            )
            continue
        estimate, standard_error = fitted
        data_precision = 1 / max(standard_error**2, 1e-6)
        prior_precision = 1 / PRIOR_SD**2
        weight = data_precision / (data_precision + prior_precision)
        rows.append(
            {
                "category": category,
                "observations": total_orders,
                "estimate": estimate,
                "standard_error": standard_error,
                "prior": prior,
                "elasticity": weight * estimate + (1 - weight) * prior,
                "data_weight": weight,
                "posterior_sd": float(np.sqrt(1 / (data_precision + prior_precision))),
                "basis": "data" if weight >= 0.5 else "prior",
                "revenue": revenue,
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values("revenue", ascending=False)


@lru_cache(maxsize=32)
def _estimate_cached(
    db_path: str, version: tuple[int, int, int, int], filters: FilterSpec
) -> pd.DataFrame:
    del version
    return _estimate(db_path, filters)


def estimate_elasticities(db_path: str | Path, filters: FilterSpec) -> pd.DataFrame:
    """Return one row per category with the estimate, the prior and the blended result."""
    path = str(Path(db_path).resolve())
    return _estimate_cached(path, database_version(path), filters.undated()).copy()


def blended_elasticity(
    db_path: str | Path, filters: FilterSpec, *, default: float = -1.4
) -> float:
    """Revenue-weighted elasticity for the current scope."""
    table = estimate_elasticities(db_path, filters)
    if table.empty or float(table["revenue"].sum()) <= 0:
        return default
    return float(np.average(table["elasticity"], weights=table["revenue"]))


def _margin_change(units, price, cost, move, elasticity):
    """Change in contribution when price moves and demand answers at constant elasticity."""
    return units * (1 + move) ** elasticity * (price * (1 + move) - cost) - units * (price - cost)


def category_price_moves(
    db_path: str | Path,
    filters: FilterSpec,
    *,
    max_move: float = 0.10,
) -> pd.DataFrame:
    """Find each category's profit-maximising price move under constant elasticity.

    For elasticity e below -1 the optimal price is c × e / (1 + e), where c is the unit
    variable cost. Moves are capped at ±max_move because the model is only trustworthy
    close to prices the business has actually charged. At or above -1 the formula has no
    finite answer and the move simply rides the cap, which is why every move also carries
    its profit at both ends of the elasticity's 95% interval. `robust` is true only when
    even the unfavourable end still gains.
    """
    where, params = filter_clause(filters)
    economics = query_df(
        db_path,
        f"""
        SELECT category,
               SUM(quantity) AS units,
               SUM(net_revenue) AS revenue,
               SUM(cogs) + SUM(shipping_cost) + SUM(payment_fee) AS variable_cost,
               SUM(contribution_profit) AS contribution_profit
        FROM v_sales WHERE {where}
        GROUP BY category
        HAVING units > 0 AND revenue > 0
        """,
        params,
    )
    table = estimate_elasticities(db_path, filters)
    if economics.empty or table.empty:
        return pd.DataFrame()
    merged = economics.merge(
        table[["category", "elasticity", "posterior_sd", "basis", "data_weight"]], on="category"
    )
    price = merged["revenue"] / merged["units"]
    unit_cost = merged["variable_cost"] / merged["units"]
    elasticity = merged["elasticity"].to_numpy()
    responsive = elasticity < -1.02
    optimal = np.where(
        responsive,
        unit_cost * elasticity / (1 + np.where(responsive, elasticity, -2.0)),
        price * (1 + max_move),
    )
    move = np.clip(optimal / price - 1, -max_move, max_move)
    new_units = merged["units"] * (1 + move) ** elasticity
    spread = Z_95 * merged["posterior_sd"].to_numpy()
    ends = np.array(
        [
            _margin_change(merged["units"], price, unit_cost, move, elasticity + side * spread)
            for side in (-1, 1)
        ]
    )
    merged["current_price"] = price
    merged["unit_variable_cost"] = unit_cost
    merged["recommended_move"] = move
    merged["expected_profit_change"] = _margin_change(
        merged["units"], price, unit_cost, move, elasticity
    )
    merged["profit_change_low"] = ends.min(axis=0)
    merged["profit_change_high"] = ends.max(axis=0)
    merged["robust"] = merged["profit_change_low"] > 0
    merged["expected_revenue_change"] = new_units * price * (1 + move) - merged["revenue"]
    merged["capped"] = np.abs(optimal / price - 1) > max_move
    return merged.sort_values("expected_profit_change", ascending=False).reset_index(drop=True)
