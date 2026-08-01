from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .etl import ETLResult

METRIC_CATALOG = [
    ("net_revenue", "净销售额", "有效销售毛额减折扣", "GBP", "fact_transactions", "每日"),
    ("gross_profit", "毛利润", "净销售额减商品成本", "GBP", "fact_transactions", "每日"),
    (
        "contribution_profit",
        "贡献利润",
        "毛利润减物流、支付、营销及退货处理成本",
        "GBP",
        "fact_transactions",
        "每日",
    ),
    ("gross_margin", "毛利率", "毛利润/净销售额", "%", "v_sales", "每日"),
    ("contribution_margin", "贡献利润率", "贡献利润/净销售额", "%", "v_sales", "每日"),
    ("orders", "订单量", "有效销售订单去重数", "count", "v_sales", "每日"),
    ("active_customers", "活跃客户", "期间内产生有效购买的客户去重数", "count", "v_sales", "每日"),
    ("repeat_rate", "复购率", "期间内订单数不少于2笔的客户占比", "%", "v_sales", "每日"),
    ("cancellation_rate", "取消率", "取消订单数/全部有效订单数", "%", "fact_transactions", "每日"),
    (
        "inventory_days",
        "库存可售天数",
        "当前库存/近90日平均日销量",
        "days",
        "inventory_snapshot",
        "每日",
    ),
]


def database_version(db_path: str | Path) -> tuple[int, int, int, int]:
    """Return a cache version including SQLite WAL state."""
    path = Path(db_path)
    wal = Path(f"{path}-wal")
    return (
        path.stat().st_mtime_ns if path.exists() else 0,
        path.stat().st_size if path.exists() else 0,
        wal.stat().st_mtime_ns if wal.exists() else 0,
        wal.stat().st_size if wal.exists() else 0,
    )


def clear_query_cache() -> None:
    _query_df_cached.cache_clear()


@contextmanager
def connect(db_path: str | Path):
    """Open a writable SQLite connection and always close it.

    sqlite3.Connection's native context manager commits or rolls back but does not
    close the connection. This wrapper provides transaction handling and deterministic
    cleanup so repeated dashboard queries and tests do not leak file handles.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _prepare_curated(result: ETLResult) -> pd.DataFrame:
    curated = result.curated.copy()
    curated["invoice_date"] = curated["invoice_date"].astype("string")
    curated["date"] = curated["date"].astype("string")
    for col in ("is_cancellation", "data_valid", "sale_valid"):
        curated[col] = curated[col].astype(int)
    for col in curated.columns:
        if str(curated[col].dtype) == "Int64":
            curated[col] = curated[col].astype("float64")
    return curated


def _load_fact(conn: sqlite3.Connection, curated: pd.DataFrame, load_mode: str) -> tuple[int, int]:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='fact_transactions'"
    ).fetchone()
    if load_mode == "replace" or not exists:
        curated.to_sql("fact_transactions", conn, if_exists="replace", index=False)
        return len(curated), 0
    if load_mode != "append":
        raise ValueError("load_mode 仅支持 replace 或 append")

    curated.to_sql("incoming_transactions", conn, if_exists="replace", index=False)
    before = int(conn.execute("SELECT COUNT(*) FROM fact_transactions").fetchone()[0])
    columns = [row[1] for row in conn.execute("PRAGMA table_info(fact_transactions)").fetchall()]
    incoming_columns = [
        row[1] for row in conn.execute("PRAGMA table_info(incoming_transactions)").fetchall()
    ]
    if columns != incoming_columns:
        conn.execute("DROP TABLE incoming_transactions")
        raise ValueError("增量数据Schema与现有仓库不一致，请执行全量重建")
    cols_sql = ",".join(f'"{c}"' for c in columns)
    conn.execute(
        f"""
        INSERT INTO fact_transactions ({cols_sql})
        SELECT {cols_sql}
        FROM incoming_transactions i
        WHERE NOT EXISTS (
            SELECT 1 FROM fact_transactions f WHERE f.record_hash = i.record_hash
        )
        """
    )
    conn.execute("DROP TABLE incoming_transactions")
    after = int(conn.execute("SELECT COUNT(*) FROM fact_transactions").fetchone()[0])
    return after - before, len(curated) - (after - before)


def _refresh_model(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS dim_customer;
        CREATE TABLE dim_customer AS
        SELECT customer_id,
               MIN(date) AS first_purchase_date,
               MAX(date) AS last_purchase_date
        FROM fact_transactions
        WHERE customer_id IS NOT NULL AND sale_valid = 1
        GROUP BY customer_id;

        DROP TABLE IF EXISTS dim_product;
        CREATE TABLE dim_product AS
        SELECT stock_code,
               MAX(description) AS description,
               MAX(category) AS category,
               AVG(unit_price) AS average_unit_price,
               AVG(unit_cost) AS average_unit_cost,
               AVG(price_elasticity) AS price_elasticity,
               MAX(supplier) AS supplier,
               MAX(supplier_lead_days) AS supplier_lead_days,
               MAX(inventory_on_hand) AS inventory_on_hand,
               MAX(reorder_point) AS reorder_point
        FROM fact_transactions
        GROUP BY stock_code;

        DROP TABLE IF EXISTS dim_country;
        CREATE TABLE dim_country AS
        SELECT country, MAX(market_region) AS market_region
        FROM fact_transactions
        GROUP BY country;

        DROP TABLE IF EXISTS dim_date;
        CREATE TABLE dim_date AS
        SELECT DISTINCT date,
               CAST(SUBSTR(date, 1, 4) AS INTEGER) AS year,
               CAST(SUBSTR(date, 6, 2) AS INTEGER) AS month_num,
               SUBSTR(date, 1, 7) AS month,
               CAST(STRFTIME('%w', date) AS INTEGER) AS weekday_num
        FROM fact_transactions
        WHERE date IS NOT NULL;

        DROP VIEW IF EXISTS v_sales;
        CREATE VIEW v_sales AS
        SELECT * FROM fact_transactions WHERE sale_valid = 1;

        DROP VIEW IF EXISTS v_cancellations;
        CREATE VIEW v_cancellations AS
        SELECT * FROM fact_transactions
        WHERE data_valid = 1 AND is_cancellation = 1;

        DROP VIEW IF EXISTS v_order_sales;
        CREATE VIEW v_order_sales AS
        SELECT invoice_no,
               MIN(invoice_date) AS invoice_date,
               MIN(date) AS date,
               MIN(month) AS month,
               MAX(customer_id) AS customer_id,
               MAX(country) AS country,
               MAX(market_region) AS market_region,
               MAX(channel) AS channel,
               SUM(quantity) AS units,
               SUM(gross_revenue) AS gross_revenue,
               SUM(discount_amount) AS discount_amount,
               SUM(net_revenue) AS revenue,
               SUM(cogs) AS cogs,
               SUM(gross_profit) AS gross_profit,
               SUM(shipping_cost) AS shipping_cost,
               SUM(payment_fee) AS payment_fee,
               SUM(marketing_cost) AS marketing_cost,
               SUM(contribution_profit) AS contribution_profit
        FROM v_sales
        GROUP BY invoice_no;

        DROP VIEW IF EXISTS v_monthly_kpis;
        CREATE VIEW v_monthly_kpis AS
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
        GROUP BY month
        ORDER BY month;

        DROP TABLE IF EXISTS inventory_snapshot;
        CREATE TABLE inventory_snapshot AS
        WITH bounds AS (
            SELECT MAX(date) AS max_date FROM v_sales
        ), demand AS (
            SELECT stock_code,
                   SUM(CASE WHEN date >= DATE((SELECT max_date FROM bounds), '-89 day') THEN quantity ELSE 0 END) / 90.0 AS avg_daily_units,
                   SUM(CASE WHEN date >= DATE((SELECT max_date FROM bounds), '-29 day') THEN quantity ELSE 0 END) AS units_30d,
                   SUM(CASE WHEN date >= DATE((SELECT max_date FROM bounds), '-89 day') THEN quantity ELSE 0 END) AS units_90d
            FROM v_sales
            GROUP BY stock_code
        )
        SELECT p.stock_code,
               p.description,
               p.category,
               p.supplier,
               p.supplier_lead_days,
               p.inventory_on_hand,
               p.reorder_point,
               COALESCE(d.avg_daily_units, 0) AS avg_daily_units,
               COALESCE(d.units_30d, 0) AS units_30d,
               COALESCE(d.units_90d, 0) AS units_90d,
               CASE WHEN COALESCE(d.avg_daily_units,0) > 0
                    THEN p.inventory_on_hand / d.avg_daily_units ELSE 999 END AS days_of_supply,
               CASE
                 WHEN COALESCE(d.avg_daily_units,0) > 0
                      AND p.inventory_on_hand / d.avg_daily_units < p.supplier_lead_days + 7 THEN 'Reorder'
                 WHEN COALESCE(d.avg_daily_units,0) > 0
                      AND p.inventory_on_hand / d.avg_daily_units > 120 THEN 'Overstock'
                 ELSE 'Healthy'
               END AS inventory_status,
               p.average_unit_cost * p.inventory_on_hand AS inventory_value
        FROM dim_product p
        LEFT JOIN demand d USING(stock_code);

        CREATE INDEX IF NOT EXISTS idx_fact_date ON fact_transactions(date);
        CREATE INDEX IF NOT EXISTS idx_fact_month ON fact_transactions(month);
        CREATE INDEX IF NOT EXISTS idx_fact_country ON fact_transactions(country);
        CREATE INDEX IF NOT EXISTS idx_fact_region ON fact_transactions(market_region);
        CREATE INDEX IF NOT EXISTS idx_fact_customer ON fact_transactions(customer_id);
        CREATE INDEX IF NOT EXISTS idx_fact_product ON fact_transactions(stock_code);
        CREATE INDEX IF NOT EXISTS idx_fact_record_hash ON fact_transactions(record_hash);
        """
    )


def _seed_governance(conn: sqlite3.Connection, metadata: dict) -> None:
    catalog = pd.DataFrame(
        METRIC_CATALOG,
        columns=["metric_id", "metric_name", "definition", "unit", "source", "refresh_frequency"],
    )
    catalog["owner"] = "Business Analytics"
    transaction_status = str(metadata.get("transaction_status", "Verified"))
    economic_status = str(metadata.get("economic_status", "Estimated"))
    inventory_status = str(metadata.get("inventory_status", "Simulated"))
    status_map = {
        "net_revenue": economic_status if economic_status == "Verified" else transaction_status,
        "gross_profit": economic_status,
        "contribution_profit": economic_status,
        "gross_margin": economic_status,
        "contribution_margin": economic_status,
        "orders": transaction_status,
        "active_customers": transaction_status,
        "repeat_rate": transaction_status,
        "cancellation_rate": transaction_status,
        "inventory_days": inventory_status,
    }
    confidence_map = {"Verified": 0.95, "Estimated": 0.72, "Simulated": 0.55, "Mixed": 0.65}
    catalog["data_status"] = catalog["metric_id"].map(status_map).fillna("Mixed")
    catalog["confidence"] = catalog["data_status"].map(confidence_map).fillna(0.6)
    catalog["source_note"] = catalog["data_status"].map(
        {
            "Verified": "来自导入字段并通过清洗与契约校验",
            "Estimated": "部分成本或经营字段由可追溯规则估算",
            "Simulated": "用于作品演示的模拟数据或参数",
            "Mixed": "由多种来源状态共同构成",
        }
    )
    catalog.to_sql("metric_catalog", conn, if_exists="replace", index=False)

    profile = pd.DataFrame(
        [
            {
                "profile_id": metadata.get("source_profile", "manual_import"),
                "profile_name": metadata.get("source_profile", "manual_import")
                .replace("_", " ")
                .title(),
                "data_mode": metadata.get("data_mode", "Mixed"),
                "transaction_status": transaction_status,
                "economic_status": economic_status,
                "inventory_status": inventory_status,
                "contract_id": metadata.get("contract_id", "unknown"),
                "source_note": (
                    "交易、成本与库存状态分别记录；Estimated/Simulated指标不得解释为企业审计值。"
                ),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ]
    )
    profile.to_sql("data_profiles", conn, if_exists="replace", index=False)

    lineage = pd.DataFrame(
        [
            (
                "raw_transactions",
                "fact_transactions",
                "etl.clean_transactions",
                "清洗、标准化及成本派生",
            ),
            ("fact_transactions", "v_monthly_kpis", "warehouse SQL", "月度经营指标聚合"),
            ("fact_transactions", "inventory_snapshot", "warehouse SQL", "近90日需求与库存覆盖"),
            ("v_monthly_kpis", "forecast_outputs", "forecasting.py", "模型回测与未来预测"),
            ("fact_transactions", "business_reports", "reporting.py", "诊断与报告输出"),
        ],
        columns=["source_object", "target_object", "transformation", "description"],
    )
    lineage.to_sql("data_lineage", conn, if_exists="replace", index=False)

    monthly = pd.read_sql_query("SELECT * FROM v_monthly_kpis ORDER BY month", conn)
    target_rows: list[dict] = []
    for idx, row in monthly.iterrows():
        history = monthly.iloc[max(0, idx - 3) : idx]
        revenue_anchor = (
            float(history["revenue"].mean()) if not history.empty else float(row["revenue"])
        )
        profit_anchor = (
            float(history["contribution_profit"].mean())
            if not history.empty
            else float(row["contribution_profit"])
        )
        target_rows.extend(
            [
                {
                    "target_period": row["month"],
                    "metric_id": "net_revenue",
                    "target_value": revenue_anchor * 1.05,
                    "direction": "higher",
                    "owner": "Commercial",
                },
                {
                    "target_period": row["month"],
                    "metric_id": "contribution_profit",
                    "target_value": profit_anchor * 1.08,
                    "direction": "higher",
                    "owner": "Finance",
                },
                {
                    "target_period": row["month"],
                    "metric_id": "gross_margin",
                    "target_value": 0.42,
                    "direction": "higher",
                    "owner": "Merchandising",
                },
                {
                    "target_period": row["month"],
                    "metric_id": "cancellation_rate",
                    "target_value": 0.04,
                    "direction": "lower",
                    "owner": "Operations",
                },
            ]
        )
    pd.DataFrame(target_rows).to_sql("business_targets", conn, if_exists="replace", index=False)


def build_warehouse(
    result: ETLResult,
    db_path: str | Path,
    *,
    load_mode: str = "replace",
    source_name: str = "manual",
) -> dict[str, int]:
    curated = _prepare_curated(result)

    with connect(db_path) as conn:
        inserted, skipped = _load_fact(conn, curated, load_mode)
        result.quality_summary.to_sql(
            "data_quality_summary", conn, if_exists="replace", index=False
        )
        result.quality_dimensions.to_sql(
            "data_quality_dimensions", conn, if_exists="replace", index=False
        )
        result.contract_issues.to_sql(
            "data_contract_issues", conn, if_exists="replace", index=False
        )
        _refresh_model(conn)
        _seed_governance(conn, result.metadata)

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS etl_runs (
                run_at TEXT NOT NULL,
                source_name TEXT NOT NULL,
                load_mode TEXT NOT NULL,
                inserted_rows INTEGER NOT NULL,
                skipped_rows INTEGER NOT NULL,
                metadata_json TEXT NOT NULL
            )
            """
        )
        metadata = {
            key: (value.isoformat() if hasattr(value, "isoformat") else value)
            for key, value in result.metadata.items()
        }
        conn.execute(
            """
            INSERT INTO etl_runs(run_at, source_name, load_mode, inserted_rows, skipped_rows, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                source_name,
                load_mode,
                inserted,
                skipped,
                json.dumps(metadata, ensure_ascii=False),
            ),
        )
    from .action_center import ensure_action_table
    from .experiments import seed_demo_experiments

    ensure_action_table(db_path)
    seed_demo_experiments(db_path)
    clear_query_cache()
    return {"inserted_rows": inserted, "skipped_rows": skipped}


def table_exists(db_path: str | Path, table: str) -> bool:
    path = Path(db_path).resolve()
    if not path.exists():
        return False
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE (type='table' OR type='view') AND name=?",
            (table,),
        ).fetchone()
    return row is not None


@lru_cache(maxsize=512)
def _query_df_cached(
    db_path: str,
    version: tuple[int, int, int, int],
    sql: str,
    params: tuple,
) -> pd.DataFrame:
    del version  # The value participates in the cache key only.
    path = Path(db_path).resolve()
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as conn:
        conn.execute("PRAGMA query_only = ON")
        return pd.read_sql_query(sql, conn, params=params)


def query_df(db_path: str | Path, sql: str, params: tuple | list | None = None) -> pd.DataFrame:
    path = str(Path(db_path).resolve())
    normalized_params = tuple(params or ())
    return _query_df_cached(path, database_version(path), sql, normalized_params).copy(deep=True)
