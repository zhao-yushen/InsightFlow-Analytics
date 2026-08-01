from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .warehouse import query_df


@dataclass(frozen=True)
class FilterSpec:
    start_date: str | None = None
    end_date: str | None = None
    countries: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()


def _where(filters: FilterSpec, alias: str = "") -> tuple[str, list]:
    prefix = f"{alias}." if alias else ""
    clauses = ["1=1"]
    params: list = []
    if filters.start_date:
        clauses.append(f"{prefix}date >= ?")
        params.append(filters.start_date)
    if filters.end_date:
        clauses.append(f"{prefix}date <= ?")
        params.append(filters.end_date)
    for column, values in (
        ("market_region", filters.regions),
        ("country", filters.countries),
        ("category", filters.categories),
        ("channel", filters.channels),
    ):
        if values:
            placeholders = ",".join("?" for _ in values)
            clauses.append(f"{prefix}{column} IN ({placeholders})")
            params.extend(values)
    return " AND ".join(clauses), params


def available_filters(db_path: str | Path) -> dict[str, list[str]]:
    return {
        "regions": query_df(db_path, "SELECT DISTINCT market_region FROM fact_transactions ORDER BY 1")[
            "market_region"
        ]
        .dropna()
        .tolist(),
        "countries": query_df(db_path, "SELECT DISTINCT country FROM fact_transactions ORDER BY 1")[
            "country"
        ]
        .dropna()
        .tolist(),
        "categories": query_df(db_path, "SELECT DISTINCT category FROM fact_transactions ORDER BY 1")[
            "category"
        ]
        .dropna()
        .tolist(),
        "channels": query_df(db_path, "SELECT DISTINCT channel FROM fact_transactions ORDER BY 1")[
            "channel"
        ]
        .dropna()
        .tolist(),
    }


def filter_option_counts(db_path: str | Path) -> dict[str, dict[str, int]]:
    queries = {
        "regions": "SELECT market_region AS value, COUNT(*) AS rows FROM fact_transactions WHERE market_region IS NOT NULL GROUP BY market_region ORDER BY rows DESC, value",
        "countries": "SELECT country AS value, COUNT(*) AS rows FROM fact_transactions WHERE country IS NOT NULL GROUP BY country ORDER BY rows DESC, value",
        "categories": "SELECT category AS value, COUNT(*) AS rows FROM fact_transactions WHERE category IS NOT NULL GROUP BY category ORDER BY rows DESC, value",
        "channels": "SELECT channel AS value, COUNT(*) AS rows FROM fact_transactions WHERE channel IS NOT NULL GROUP BY channel ORDER BY rows DESC, value",
    }
    output: dict[str, dict[str, int]] = {}
    for key, sql in queries.items():
        frame = query_df(db_path, sql)
        output[key] = {str(row["value"]): int(row["rows"]) for _, row in frame.iterrows()}
    return output


def filter_dimension_counts(
    db_path: str | Path,
    filters: FilterSpec,
    dimension: str,
) -> dict[str, int]:
    """Return option counts under all active filters except the target dimension.

    This enables cascading filters: market region narrows countries, countries narrow
    categories, and categories narrow channels. Counts are therefore meaningful for
    the currently selected date range instead of being global warehouse totals.
    """
    allowed = {
        "market_region": "regions",
        "country": "countries",
        "category": "categories",
        "channel": "channels",
    }
    if dimension not in allowed:
        raise ValueError(f"Unsupported filter dimension: {dimension}")
    scoped = FilterSpec(
        start_date=filters.start_date,
        end_date=filters.end_date,
        regions=() if dimension == "market_region" else filters.regions,
        countries=() if dimension == "country" else filters.countries,
        categories=() if dimension == "category" else filters.categories,
        channels=() if dimension == "channel" else filters.channels,
    )
    where, params = _where(scoped)
    frame = query_df(
        db_path,
        f"""
        SELECT {dimension} AS value, COUNT(*) AS rows
        FROM fact_transactions
        WHERE {where} AND data_valid=1 AND {dimension} IS NOT NULL
        GROUP BY {dimension}
        ORDER BY rows DESC, value
        """,
        params,
    )
    return {str(row["value"]): int(row["rows"]) for _, row in frame.iterrows()}


def filter_coverage(db_path: str | Path, filters: FilterSpec) -> dict[str, object]:
    """Summarize how much valid sales data survives the current filter intersection."""
    where, params = _where(filters)
    frame = query_df(
        db_path,
        f"""
        SELECT COUNT(*) AS rows,
               COUNT(DISTINCT invoice_no) AS orders,
               COUNT(DISTINCT customer_id) AS customers,
               MIN(date) AS min_date,
               MAX(date) AS max_date
        FROM v_sales
        WHERE {where}
        """,
        params,
    )
    row = frame.iloc[0]
    return {
        "rows": int(row["rows"] or 0),
        "orders": int(row["orders"] or 0),
        "customers": int(row["customers"] or 0),
        "min_date": None if pd.isna(row["min_date"]) else str(row["min_date"]),
        "max_date": None if pd.isna(row["max_date"]) else str(row["max_date"]),
    }


def date_bounds(db_path: str | Path) -> tuple[str, str]:
    df = query_df(db_path, "SELECT MIN(date) AS min_date, MAX(date) AS max_date FROM fact_transactions")
    return str(df.loc[0, "min_date"]), str(df.loc[0, "max_date"])


def kpi_summary(db_path: str | Path, filters: FilterSpec) -> dict[str, float]:
    where, params = _where(filters)
    sales = query_df(
        db_path,
        f"""
        SELECT COALESCE(SUM(gross_revenue), 0) AS gross_revenue,
               COALESCE(SUM(discount_amount), 0) AS discount_amount,
               COALESCE(SUM(net_revenue), 0) AS revenue,
               COALESCE(SUM(cogs), 0) AS cogs,
               COALESCE(SUM(gross_profit), 0) AS gross_profit,
               COALESCE(SUM(contribution_profit), 0) AS contribution_profit,
               COALESCE(SUM(shipping_cost), 0) AS shipping_cost,
               COALESCE(SUM(payment_fee), 0) AS payment_fee,
               COALESCE(SUM(marketing_cost), 0) AS marketing_cost,
               COUNT(DISTINCT invoice_no) AS orders,
               COUNT(DISTINCT customer_id) AS active_customers,
               COALESCE(SUM(quantity), 0) AS units
        FROM v_sales
        WHERE {where}
        """,
        params,
    ).iloc[0]

    cancellations = query_df(
        db_path,
        f"""
        SELECT COUNT(DISTINCT CASE WHEN is_cancellation=1 AND data_valid=1 THEN invoice_no END) AS cancelled_orders,
               COUNT(DISTINCT CASE WHEN data_valid=1 THEN invoice_no END) AS all_orders,
               COALESCE(SUM(CASE WHEN is_cancellation=1 AND data_valid=1 THEN return_loss ELSE 0 END),0) AS return_loss
        FROM fact_transactions
        WHERE {where}
        """,
        params,
    ).iloc[0]

    repeat = query_df(
        db_path,
        f"""
        WITH customer_orders AS (
            SELECT customer_id, COUNT(DISTINCT invoice_no) AS orders
            FROM v_sales
            WHERE {where} AND customer_id IS NOT NULL
            GROUP BY customer_id
        )
        SELECT COALESCE(AVG(CASE WHEN orders >= 2 THEN 1.0 ELSE 0.0 END), 0) AS repeat_rate
        FROM customer_orders
        """,
        params,
    ).iloc[0, 0]

    orders = float(sales["orders"] or 0)
    customers = float(sales["active_customers"] or 0)
    revenue = float(sales["revenue"] or 0)
    gross_revenue = float(sales["gross_revenue"] or 0)
    gross_profit = float(sales["gross_profit"] or 0)
    contribution_profit = float(sales["contribution_profit"] or 0)
    all_orders = float(cancellations["all_orders"] or 0)
    return {
        "gross_revenue": gross_revenue,
        "discount_amount": float(sales["discount_amount"] or 0),
        "discount_rate": float(sales["discount_amount"] or 0) / gross_revenue if gross_revenue else 0.0,
        "revenue": revenue,
        "cogs": float(sales["cogs"] or 0),
        "gross_profit": gross_profit,
        "gross_margin": gross_profit / revenue if revenue else 0.0,
        "contribution_profit": contribution_profit,
        "contribution_margin": contribution_profit / revenue if revenue else 0.0,
        "shipping_cost": float(sales["shipping_cost"] or 0),
        "payment_fee": float(sales["payment_fee"] or 0),
        "marketing_cost": float(sales["marketing_cost"] or 0),
        "return_loss": float(cancellations["return_loss"] or 0),
        "orders": orders,
        "active_customers": customers,
        "units": float(sales["units"] or 0),
        "average_order_value": revenue / orders if orders else 0.0,
        "profit_per_order": contribution_profit / orders if orders else 0.0,
        "profit_per_customer": contribution_profit / customers if customers else 0.0,
        "purchase_frequency": orders / customers if customers else 0.0,
        "repeat_rate": float(repeat or 0),
        "cancellation_rate": float(cancellations["cancelled_orders"] or 0) / all_orders if all_orders else 0.0,
    }


def monthly_trend(db_path: str | Path, filters: FilterSpec) -> pd.DataFrame:
    where, params = _where(filters)
    return query_df(
        db_path,
        f"""
        SELECT month,
               SUM(gross_revenue) AS gross_revenue,
               SUM(discount_amount) AS discount_amount,
               SUM(net_revenue) AS revenue,
               SUM(cogs) AS cogs,
               SUM(gross_profit) AS gross_profit,
               SUM(contribution_profit) AS contribution_profit,
               SUM(shipping_cost) AS shipping_cost,
               SUM(payment_fee) AS payment_fee,
               SUM(marketing_cost) AS marketing_cost,
               COUNT(DISTINCT invoice_no) AS orders,
               COUNT(DISTINCT customer_id) AS active_customers,
               SUM(quantity) AS units,
               SUM(net_revenue) / NULLIF(COUNT(DISTINCT invoice_no), 0) AS average_order_value,
               SUM(gross_profit) / NULLIF(SUM(net_revenue), 0) AS gross_margin,
               SUM(contribution_profit) / NULLIF(SUM(net_revenue), 0) AS contribution_margin,
               SUM(discount_amount) / NULLIF(SUM(gross_revenue), 0) AS discount_rate
        FROM v_sales
        WHERE {where}
        GROUP BY month
        ORDER BY month
        """,
        params,
    )


def dimension_performance(
    db_path: str | Path,
    filters: FilterSpec,
    dimension: str,
    limit: int = 20,
) -> pd.DataFrame:
    allowed = {"country", "category", "channel", "stock_code", "description", "supplier"}
    if dimension not in allowed:
        raise ValueError(f"不允许的维度: {dimension}")
    where, params = _where(filters)
    return query_df(
        db_path,
        f"""
        SELECT {dimension},
               SUM(gross_revenue) AS gross_revenue,
               SUM(discount_amount) AS discount_amount,
               SUM(net_revenue) AS revenue,
               SUM(cogs) AS cogs,
               SUM(gross_profit) AS gross_profit,
               SUM(contribution_profit) AS contribution_profit,
               SUM(gross_profit) / NULLIF(SUM(net_revenue),0) AS gross_margin,
               SUM(contribution_profit) / NULLIF(SUM(net_revenue),0) AS contribution_margin,
               COUNT(DISTINCT invoice_no) AS orders,
               COUNT(DISTINCT customer_id) AS customers,
               SUM(quantity) AS units,
               SUM(net_revenue) / NULLIF(COUNT(DISTINCT invoice_no), 0) AS average_order_value
        FROM v_sales
        WHERE {where}
        GROUP BY {dimension}
        ORDER BY revenue DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def product_profitability(db_path: str | Path, filters: FilterSpec, limit: int = 100) -> pd.DataFrame:
    where, params = _where(filters)
    return query_df(
        db_path,
        f"""
        SELECT stock_code,
               MAX(description) AS description,
               MAX(category) AS category,
               SUM(net_revenue) AS revenue,
               SUM(gross_profit) AS gross_profit,
               SUM(contribution_profit) AS contribution_profit,
               SUM(gross_profit) / NULLIF(SUM(net_revenue),0) AS gross_margin,
               SUM(contribution_profit) / NULLIF(SUM(net_revenue),0) AS contribution_margin,
               SUM(discount_amount) / NULLIF(SUM(gross_revenue),0) AS discount_rate,
               SUM(quantity) AS units,
               COUNT(DISTINCT invoice_no) AS orders
        FROM v_sales
        WHERE {where}
        GROUP BY stock_code
        ORDER BY revenue DESC
        LIMIT ?
        """,
        [*params, limit],
    )


def cost_waterfall(db_path: str | Path, filters: FilterSpec) -> pd.DataFrame:
    kpi = kpi_summary(db_path, filters)
    return pd.DataFrame(
        [
            ("商品毛额", kpi["gross_revenue"]),
            ("折扣", -kpi["discount_amount"]),
            ("商品成本", -kpi["cogs"]),
            ("物流成本", -kpi["shipping_cost"]),
            ("支付手续费", -kpi["payment_fee"]),
            ("营销费用", -kpi["marketing_cost"]),
            ("贡献利润", kpi["contribution_profit"]),
        ],
        columns=["component", "value"],
    )


def rfm_segments(db_path: str | Path, filters: FilterSpec) -> pd.DataFrame:
    where, params = _where(filters)
    data = query_df(
        db_path,
        f"""
        SELECT customer_id,
               MAX(date) AS last_purchase_date,
               COUNT(DISTINCT invoice_no) AS frequency,
               SUM(net_revenue) AS monetary,
               SUM(contribution_profit) AS contribution_profit,
               AVG(discount_rate) AS avg_discount_rate,
               AVG(net_revenue) AS avg_line_revenue
        FROM v_sales
        WHERE {where} AND customer_id IS NOT NULL
        GROUP BY customer_id
        """,
        params,
    )
    if data.empty:
        return data
    max_date = pd.to_datetime(data["last_purchase_date"]).max()
    data["recency"] = (max_date - pd.to_datetime(data["last_purchase_date"])).dt.days

    def robust_score(series: pd.Series, high_is_good: bool) -> pd.Series:
        ranked = series.rank(method="first")
        bins = min(5, max(1, series.nunique()))
        if bins == 1:
            score = pd.Series(3, index=series.index)
        else:
            score = pd.qcut(ranked, q=bins, labels=False, duplicates="drop") + 1
            if bins < 5:
                score = np.ceil(score * (5 / bins)).astype(int)
        return (6 - score) if not high_is_good else score

    data["r_score"] = robust_score(data["recency"], high_is_good=False)
    data["f_score"] = robust_score(data["frequency"], high_is_good=True)
    data["m_score"] = robust_score(data["monetary"], high_is_good=True)
    data["rfm_score"] = data[["r_score", "f_score", "m_score"]].sum(axis=1)

    conditions = [
        (data["r_score"] >= 4) & (data["f_score"] >= 4) & (data["m_score"] >= 4),
        (data["r_score"] >= 3) & (data["f_score"] >= 4),
        (data["r_score"] >= 4) & (data["f_score"] <= 2),
        (data["r_score"] <= 2) & (data["f_score"] >= 3),
        (data["r_score"] <= 2) & (data["f_score"] <= 2),
    ]
    labels = ["Champions", "Loyal", "Potential", "At Risk", "Hibernating"]
    data["segment"] = np.select(conditions, labels, default="Developing")
    return data.sort_values("monetary", ascending=False)


def customer_value_risk(db_path: str | Path, filters: FilterSpec) -> pd.DataFrame:
    data = rfm_segments(db_path, filters)
    if data.empty:
        return data
    recency_scale = max(float(data["recency"].quantile(0.90)), 1.0)
    frequency_scale = max(float(data["frequency"].quantile(0.90)), 1.0)
    profit_scale = max(float(data["contribution_profit"].abs().quantile(0.90)), 1.0)
    recency_risk = (data["recency"] / recency_scale).clip(0, 1)
    low_frequency = (1 - data["frequency"] / frequency_scale).clip(0, 1)
    discount_dependency = (data["avg_discount_rate"] / 0.20).clip(0, 1)
    negative_profit = (-data["contribution_profit"] / profit_scale).clip(0, 1)
    data["churn_risk"] = (
        0.50 * recency_risk + 0.25 * low_frequency + 0.15 * discount_dependency + 0.10 * negative_profit
    ).clip(0, 1)
    expected_months = (12 * (1 - data["churn_risk"])).clip(1, 12)
    monthly_profit = data["contribution_profit"] / max(
        (pd.Timestamp(filters.end_date) - pd.Timestamp(filters.start_date)).days / 30.4 if filters.end_date and filters.start_date else 3,
        1,
    )
    data["predicted_clv"] = monthly_profit * expected_months
    data["expected_profit_at_risk"] = data["predicted_clv"].clip(lower=0) * data["churn_risk"]
    data["recommended_action"] = np.select(
        [
            (data["churn_risk"] >= 0.70) & (data["predicted_clv"] > data["predicted_clv"].median()),
            data["churn_risk"] >= 0.70,
            (data["churn_risk"] >= 0.45) & (data["segment"].isin(["Champions", "Loyal"])),
        ],
        ["高价值定向召回", "低成本自动触达", "忠诚度与交叉销售"],
        default="常规培育",
    )
    return data.sort_values("expected_profit_at_risk", ascending=False)


def cohort_retention(db_path: str | Path, filters: FilterSpec) -> pd.DataFrame:
    where, params = _where(filters)
    sales = query_df(
        db_path,
        f"""
        SELECT customer_id, invoice_no, date, month
        FROM v_sales
        WHERE {where} AND customer_id IS NOT NULL
        GROUP BY customer_id, invoice_no, date, month
        """,
        params,
    )
    if sales.empty:
        return pd.DataFrame()
    sales["order_month"] = pd.to_datetime(sales["month"] + "-01")
    sales["cohort_month"] = sales.groupby("customer_id")["order_month"].transform("min")
    sales["cohort_index"] = (
        (sales["order_month"].dt.year - sales["cohort_month"].dt.year) * 12
        + sales["order_month"].dt.month
        - sales["cohort_month"].dt.month
    )
    cohort = (
        sales.groupby(["cohort_month", "cohort_index"])["customer_id"]
        .nunique()
        .reset_index(name="customers")
    )
    base = cohort.loc[cohort["cohort_index"] == 0, ["cohort_month", "customers"]].rename(
        columns={"customers": "cohort_size"}
    )
    cohort = cohort.merge(base, on="cohort_month", how="left")
    cohort["retention_rate"] = cohort["customers"] / cohort["cohort_size"]
    pivot = cohort.pivot(index="cohort_month", columns="cohort_index", values="retention_rate")
    # pivot.index is a DatetimeIndex, not a Series. DatetimeIndex exposes
    # strftime directly; the .dt accessor is only for Series-like objects.
    pivot.index = pd.to_datetime(pivot.index, errors="coerce").strftime("%Y-%m")
    return pivot.sort_index()


def inventory_status(db_path: str | Path, status: str | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM inventory_snapshot"
    params: list = []
    if status:
        sql += " WHERE inventory_status = ?"
        params.append(status)
    sql += " ORDER BY CASE inventory_status WHEN 'Reorder' THEN 1 WHEN 'Overstock' THEN 2 ELSE 3 END, days_of_supply"
    return query_df(db_path, sql, params)


def inventory_kpis(db_path: str | Path) -> dict[str, float]:
    row = query_df(
        db_path,
        """
        SELECT COUNT(*) AS sku_count,
               SUM(CASE WHEN inventory_status='Reorder' THEN 1 ELSE 0 END) AS reorder_skus,
               SUM(CASE WHEN inventory_status='Overstock' THEN 1 ELSE 0 END) AS overstock_skus,
               SUM(inventory_value) AS inventory_value,
               AVG(CASE WHEN days_of_supply < 999 THEN days_of_supply END) AS avg_days_of_supply
        FROM inventory_snapshot
        """,
    ).iloc[0]
    return {k: float(row[k] or 0) for k in row.index}


def quality_summary(db_path: str | Path) -> pd.DataFrame:
    return query_df(db_path, "SELECT * FROM data_quality_summary")


def quality_dimensions(db_path: str | Path) -> pd.DataFrame:
    return query_df(db_path, "SELECT * FROM data_quality_dimensions")


def quality_score(db_path: str | Path) -> float:
    df = quality_dimensions(db_path)
    return float(df["score_100"].mean()) if not df.empty else 0.0


def metric_catalog(db_path: str | Path) -> pd.DataFrame:
    return query_df(db_path, "SELECT * FROM metric_catalog ORDER BY metric_id")


def data_lineage(db_path: str | Path) -> pd.DataFrame:
    return query_df(db_path, "SELECT * FROM data_lineage")


def target_status(db_path: str | Path, month: str | None = None) -> pd.DataFrame:
    if month is None:
        month = str(query_df(db_path, "SELECT MAX(month) month FROM v_monthly_kpis").iloc[0, 0])
    actual = query_df(db_path, "SELECT * FROM v_monthly_kpis WHERE month=?", (month,))
    targets = query_df(db_path, "SELECT * FROM business_targets WHERE target_period=?", (month,))
    if actual.empty or targets.empty:
        return pd.DataFrame()
    row = actual.iloc[0]
    actual_map = {
        "net_revenue": float(row["revenue"]),
        "contribution_profit": float(row["contribution_profit"]),
        "gross_margin": float(row["gross_margin"]),
        "cancellation_rate": float(
            query_df(
                db_path,
                """
                SELECT COUNT(DISTINCT CASE WHEN is_cancellation=1 AND data_valid=1 THEN invoice_no END) * 1.0 /
                       NULLIF(COUNT(DISTINCT CASE WHEN data_valid=1 THEN invoice_no END),0) rate
                FROM fact_transactions WHERE month=?
                """,
                (month,),
            ).iloc[0, 0]
            or 0
        ),
    }
    out = targets.copy()
    out["actual_value"] = out["metric_id"].map(actual_map)
    out["attainment"] = np.where(
        out["direction"].eq("higher"),
        out["actual_value"] / out["target_value"].replace(0, np.nan),
        out["target_value"] / out["actual_value"].replace(0, np.nan),
    )
    out["status"] = np.select(
        [out["attainment"] >= 1.0, out["attainment"] >= 0.9],
        ["On Track", "At Risk"],
        default="Off Track",
    )
    return out


def previous_period(filters: FilterSpec) -> FilterSpec:
    if not filters.start_date or not filters.end_date:
        raise ValueError("比较期间需要开始和结束日期")
    start = pd.Timestamp(filters.start_date)
    end = pd.Timestamp(filters.end_date)
    days = (end - start).days + 1
    prev_end = start - pd.Timedelta(days=1)
    prev_start = prev_end - pd.Timedelta(days=days - 1)
    return FilterSpec(
        start_date=prev_start.date().isoformat(),
        end_date=prev_end.date().isoformat(),
        countries=filters.countries,
        categories=filters.categories,
        channels=filters.channels,
        regions=filters.regions,
    )


def percent_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / abs(previous)
