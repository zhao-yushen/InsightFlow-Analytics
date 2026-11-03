from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .etl import SCHEMA_VERSION, ETLResult

CURRENCY_UNIT = "CURRENCY"
METRIC_CATALOG = [
    ("net_revenue", "净销售额", "商品毛额减折扣再减退款", CURRENCY_UNIT, "v_ledger", "每日"),
    ("gross_profit", "毛利润", "净销售额减商品成本", CURRENCY_UNIT, "v_ledger", "每日"),
    (
        "contribution_profit",
        "贡献利润",
        "毛利润减物流、支付、营销及退货处理成本",
        CURRENCY_UNIT,
        "v_ledger",
        "每日",
    ),
    ("gross_margin", "毛利率", "毛利润/净销售额", "%", "v_ledger", "每日"),
    ("contribution_margin", "贡献利润率", "贡献利润/净销售额", "%", "v_ledger", "每日"),
    ("orders", "订单量", "有效销售订单去重数", "count", "v_sales", "每日"),
    ("active_customers", "活跃客户", "期间内产生有效购买的客户去重数", "count", "v_sales", "每日"),
    ("repeat_rate", "复购率", "期间内订单数不少于2笔的客户占比", "%", "v_sales", "每日"),
    ("cancellation_rate", "退货取消率", "退货或取消单数/销售订单数", "%", "v_ledger", "每日"),
    (
        "inventory_days",
        "库存可售天数",
        "当前库存/近90日平均日销量",
        "days",
        "inventory_snapshot",
        "每日",
    ),
]

STATUS_CONFIDENCE = {"Verified": 0.95, "Estimated": 0.72, "Simulated": 0.55, "Missing": 0.0}
STATUS_STRENGTH = ["Missing", "Simulated", "Estimated", "Verified"]
STATUS_NOTES = {
    "Verified": "来自导入字段并通过清洗与契约校验",
    "Estimated": "部分成本或经营字段由可追溯规则估算",
    "Simulated": "用于作品演示的模拟数据或参数",
    "Missing": "来源文件没有这项数据，相关分析不可用",
    "Mixed": "仓库内多批数据来源不同，请按批次核对",
}
# Every money aggregate reads the signed ledger, so sales and reversals net to the result
# after returns at any grain. Counts and sale-only amounts stay conditional on sale_valid.
LEDGER_AGGREGATES = """
    COALESCE(SUM(CASE WHEN sale_valid=1 THEN gross_revenue END), 0) AS gross_revenue,
    COALESCE(SUM(CASE WHEN sale_valid=1 THEN discount_amount END), 0) AS discount_amount,
    COALESCE(-SUM(CASE WHEN is_cancellation=1 THEN net_revenue END), 0) AS returns_value,
    COALESCE(SUM(net_revenue), 0) AS revenue,
    COALESCE(SUM(cogs), 0) AS cogs,
    COALESCE(SUM(CASE WHEN sale_valid=1 THEN cogs END), 0) AS sale_cogs,
    COALESCE(-SUM(CASE WHEN is_cancellation=1 THEN cogs END), 0) AS returned_cogs,
    COALESCE(SUM(gross_profit), 0) AS gross_profit,
    COALESCE(SUM(contribution_profit), 0) AS contribution_profit,
    COALESCE(SUM(shipping_cost), 0) AS shipping_cost,
    COALESCE(SUM(payment_fee), 0) AS payment_fee,
    COALESCE(SUM(marketing_cost), 0) AS marketing_cost,
    COALESCE(SUM(return_processing_cost), 0) AS return_processing_cost,
    COALESCE(SUM(return_loss), 0) AS return_loss,
    COUNT(DISTINCT CASE WHEN sale_valid=1 THEN invoice_no END) AS orders,
    COUNT(DISTINCT CASE WHEN sale_valid=1 THEN customer_id END) AS active_customers,
    COUNT(DISTINCT CASE WHEN is_cancellation=1 THEN invoice_no END) AS cancelled_orders,
    COALESCE(SUM(CASE WHEN sale_valid=1 THEN quantity END), 0) AS units
"""


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


def _warehouse_currency(conn: sqlite3.Connection, curated: pd.DataFrame) -> str:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(fact_transactions)").fetchall()}
    if "currency" not in columns:
        return str(curated["currency"].iloc[0])
    row = conn.execute("SELECT currency FROM fact_transactions LIMIT 1").fetchone()
    return str(row[0]) if row and row[0] else str(curated["currency"].iloc[0])


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
    if _warehouse_currency(conn, curated) != str(curated["currency"].iloc[0]):
        conn.execute("DROP TABLE incoming_transactions")
        raise ValueError(
            "这批数据的币种与仓库不同。请选择仓库币种并填写汇率后再导入，避免不同货币直接相加。"
        )
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
        _MODEL_SQL.replace("__AGG__", LEDGER_AGGREGATES)
    )


_MODEL_SQL = """
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
        WITH spellings AS (
            SELECT stock_code, description, COUNT(*) AS lines
            FROM fact_transactions
            WHERE sale_valid = 1 AND description IS NOT NULL
            GROUP BY stock_code, description
        ), names AS (
            -- The name shoppers actually bought under, not warehouse notes on the same code.
            SELECT stock_code, description,
                   ROW_NUMBER() OVER (
                       PARTITION BY stock_code ORDER BY lines DESC, description
                   ) AS position
            FROM spellings
        ), latest_stock AS (
            -- With MAX, SQLite takes bare columns from the row holding the newest date.
            SELECT stock_code, inventory_on_hand, reorder_point, MAX(invoice_date) AS read_at
            FROM fact_transactions
            WHERE inventory_on_hand IS NOT NULL
            GROUP BY stock_code
        )
        SELECT f.stock_code,
               n.description,
               MAX(f.category) AS category,
               AVG(f.unit_price) AS average_unit_price,
               AVG(f.unit_cost) AS average_unit_cost,
               AVG(f.price_elasticity) AS price_elasticity,
               MAX(f.supplier) AS supplier,
               MAX(f.supplier_lead_days) AS supplier_lead_days,
               s.inventory_on_hand,
               s.reorder_point
        FROM fact_transactions f
        LEFT JOIN names n ON n.stock_code = f.stock_code AND n.position = 1
        LEFT JOIN latest_stock s ON s.stock_code = f.stock_code
        WHERE f.sale_valid = 1
        GROUP BY f.stock_code;
        CREATE UNIQUE INDEX idx_dim_product ON dim_product(stock_code);

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

        DROP VIEW IF EXISTS v_ledger;
        CREATE VIEW v_ledger AS
        SELECT * FROM fact_transactions WHERE data_valid = 1;

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
               __AGG__,
               SUM(net_revenue) / NULLIF(COUNT(DISTINCT CASE WHEN sale_valid=1 THEN invoice_no END), 0) AS average_order_value,
               SUM(gross_profit) / NULLIF(SUM(net_revenue), 0) AS gross_margin,
               SUM(contribution_profit) / NULLIF(SUM(net_revenue), 0) AS contribution_margin,
               SUM(CASE WHEN sale_valid=1 THEN discount_amount END)
                   / NULLIF(SUM(CASE WHEN sale_valid=1 THEN gross_revenue END), 0) AS discount_rate,
               COUNT(DISTINCT CASE WHEN is_cancellation=1 THEN invoice_no END) * 1.0
                   / NULLIF(COUNT(DISTINCT CASE WHEN sale_valid=1 THEN invoice_no END), 0) AS cancellation_rate
        FROM v_ledger
        GROUP BY month
        ORDER BY month;

        DROP TABLE IF EXISTS inventory_snapshot;
        CREATE TABLE inventory_snapshot AS
        WITH bounds AS (
            SELECT MAX(date) AS max_date FROM v_sales
        ), demand AS (
            -- Reversals count, so an order placed and cancelled is no demand at all.
            SELECT stock_code,
                   MAX(SUM(CASE WHEN date >= DATE((SELECT max_date FROM bounds), '-89 day') THEN quantity ELSE 0 END), 0) / 90.0 AS avg_daily_units,
                   MAX(SUM(CASE WHEN date >= DATE((SELECT max_date FROM bounds), '-29 day') THEN quantity ELSE 0 END), 0) AS units_30d,
                   MAX(SUM(CASE WHEN date >= DATE((SELECT max_date FROM bounds), '-89 day') THEN quantity ELSE 0 END), 0) AS units_90d
            FROM v_ledger
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
                 WHEN p.inventory_on_hand IS NULL THEN 'Unknown'
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
        CREATE INDEX IF NOT EXISTS idx_fact_valid_date ON fact_transactions(data_valid, date);
        CREATE INDEX IF NOT EXISTS idx_fact_sale_date ON fact_transactions(sale_valid, date);
"""



def _status_shares(conn: sqlite3.Connection, column: str) -> dict[str, float]:
    rows = conn.execute(
        f"""
        SELECT {column}, COUNT(*) FROM fact_transactions
        WHERE {column} IS NOT NULL GROUP BY {column}
        """
    ).fetchall()
    total = sum(count for _, count in rows) or 1
    return {str(status): count / total for status, count in rows}


def _status_of(shares: dict[str, float]) -> str:
    return next(iter(shares)) if len(shares) == 1 else "Mixed"


def _weakest(*shares: dict[str, float]) -> tuple[str, float]:
    """Rate a metric by its weakest input, weighted by how many rows carry each status.

    A derived number is only as trustworthy as its least certain input, and a warehouse
    that is 99% simulated must not read as verified because of one clean batch.
    """
    statuses = [_status_of(share) for share in shares]
    confidence = min(
        sum(STATUS_CONFIDENCE.get(status, 0.6) * weight for status, weight in share.items())
        for share in shares
    )
    if "Mixed" in statuses:
        return "Mixed", round(confidence, 3)
    return min(statuses, key=STATUS_STRENGTH.index), round(confidence, 3)


def _seed_governance(conn: sqlite3.Connection, metadata: dict) -> None:
    """Describe the warehouse as it now stands, not just the batch that was loaded last."""
    transaction = _status_shares(conn, "transaction_data_status")
    economic = _status_shares(conn, "economic_data_status")
    inventory = _status_shares(conn, "inventory_data_status")
    sources = [
        row[0]
        for row in conn.execute(
            "SELECT source_profile, COUNT(*) n FROM fact_transactions GROUP BY 1 ORDER BY n DESC"
        ).fetchall()
    ]
    currency = str(
        conn.execute("SELECT currency FROM fact_transactions LIMIT 1").fetchone()[0]
        or metadata.get("currency", "GBP")
    )

    metric_inputs = {
        "net_revenue": (transaction,),
        "gross_profit": (transaction, economic),
        "contribution_profit": (transaction, economic),
        "gross_margin": (transaction, economic),
        "contribution_margin": (transaction, economic),
        "orders": (transaction,),
        "active_customers": (transaction,),
        "repeat_rate": (transaction,),
        "cancellation_rate": (transaction,),
        "inventory_days": (inventory,),
    }
    catalog = pd.DataFrame(
        METRIC_CATALOG,
        columns=["metric_id", "metric_name", "definition", "unit", "source", "refresh_frequency"],
    )
    catalog["unit"] = catalog["unit"].replace(CURRENCY_UNIT, currency)
    catalog["owner"] = "Business Analytics"
    rated = {metric: _weakest(*inputs) for metric, inputs in metric_inputs.items()}
    catalog["data_status"] = catalog["metric_id"].map(lambda metric: rated[metric][0])
    catalog["confidence"] = catalog["metric_id"].map(lambda metric: rated[metric][1])
    catalog["source_note"] = catalog["data_status"].map(STATUS_NOTES)
    catalog.to_sql("metric_catalog", conn, if_exists="replace", index=False)

    transaction_status = _status_of(transaction)
    economic_status = _status_of(economic)
    inventory_status = _status_of(inventory)
    primary = str(sources[0]) if sources else str(metadata.get("source_profile", "manual_import"))
    profile = pd.DataFrame(
        [
            {
                "profile_id": primary if len(sources) <= 1 else "mixed_sources",
                "profile_name": (
                    primary.replace("_", " ").title()
                    if len(sources) <= 1
                    else f"{len(sources)} 个数据来源"
                ),
                "data_mode": (
                    transaction_status
                    if transaction_status == economic_status == inventory_status
                    else "Mixed"
                ),
                "transaction_status": transaction_status,
                "economic_status": economic_status,
                "inventory_status": inventory_status,
                "contract_id": metadata.get("contract_id", "unknown"),
                "source_note": (
                    "交易、成本与库存状态按行记录；Estimated/Simulated指标不得解释为企业审计值。"
                ),
                "currency": currency,
                "schema_version": SCHEMA_VERSION,
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
            ("fact_transactions", "v_ledger", "warehouse SQL", "销售与退货对冲后的有效账目"),
            ("v_ledger", "v_monthly_kpis", "warehouse SQL", "月度经营指标聚合"),
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

        def anchor(column: str, source: pd.DataFrame = history, month: pd.Series = row) -> float:
            return float(source[column].mean()) if not source.empty else float(month[column] or 0)

        target_rows.extend(
            [
                {
                    "target_period": row["month"],
                    "metric_id": "net_revenue",
                    "target_value": anchor("revenue") * 1.05,
                    "direction": "higher",
                    "owner": "Commercial",
                },
                {
                    "target_period": row["month"],
                    "metric_id": "contribution_profit",
                    "target_value": anchor("contribution_profit") * 1.08,
                    "direction": "higher",
                    "owner": "Finance",
                },
                {
                    "target_period": row["month"],
                    "metric_id": "gross_margin",
                    "target_value": anchor("gross_margin") + 0.01,
                    "direction": "higher",
                    "owner": "Merchandising",
                },
                {
                    "target_period": row["month"],
                    "metric_id": "cancellation_rate",
                    "target_value": anchor("cancellation_rate") * 0.95,
                    "direction": "lower",
                    "owner": "Operations",
                },
            ]
        )
    targets = pd.DataFrame(target_rows)
    targets["target_basis"] = "近三个月均值加规则增幅，并非已批准预算"
    targets.to_sql("business_targets", conn, if_exists="replace", index=False)


def _table_frame(conn: sqlite3.Connection, table: str) -> pd.DataFrame | None:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return pd.read_sql_query(f"SELECT * FROM {table}", conn) if exists else None


def _store_quality(
    conn: sqlite3.Connection,
    result: ETLResult,
    load_mode: str,
    source_name: str,
    skipped: int,
) -> None:
    """Keep the quality tables representative of every loaded batch.

    Counts add up and dimension scores are weighted by rows, so one small clean file can
    neither erase the history of a large warehouse nor flip its score.
    """
    summary = result.quality_summary.copy()
    dimensions = result.quality_dimensions.copy()
    issues = result.contract_issues.copy()
    issues["source_name"] = source_name
    previous_summary = _table_frame(conn, "data_quality_summary")
    previous_dimensions = _table_frame(conn, "data_quality_dimensions")
    previous_issues = _table_frame(conn, "data_contract_issues")
    if load_mode == "append" and previous_summary is not None:
        old_rows = float(
            previous_summary.loc[previous_summary["metric"] == "raw_rows", "value"].sum()
        )
        new_rows = float(summary.loc[summary["metric"] == "raw_rows", "value"].sum())
        merged = previous_summary.merge(
            summary[["metric", "value"]], on="metric", how="outer", suffixes=("", "_new")
        )
        merged["value"] = merged["value"].fillna(0) + merged["value_new"].fillna(0)
        merged.loc[merged["metric"] == "duplicate_rows_removed", "value"] += skipped
        merged["description"] = merged["description"].fillna("")
        summary = merged[["metric", "value", "description"]]
        if previous_dimensions is not None and old_rows + new_rows > 0:
            joined = previous_dimensions.merge(
                dimensions[["dimension", "score", "score_100"]],
                on="dimension",
                how="outer",
                suffixes=("", "_new"),
            )
            for column in ("score", "score_100"):
                joined[column] = (
                    joined[column].fillna(joined[f"{column}_new"]) * old_rows
                    + joined[f"{column}_new"].fillna(joined[column]) * new_rows
                ) / (old_rows + new_rows)
            dimensions = joined[["dimension", "score", "description", "score_100"]]
        if previous_issues is not None:
            combined = pd.concat([previous_issues, issues], ignore_index=True)
            failing = combined.loc[combined["severity"] != "PASS"]
            issues = failing if not failing.empty else combined.tail(1)
    summary.to_sql("data_quality_summary", conn, if_exists="replace", index=False)
    dimensions.to_sql("data_quality_dimensions", conn, if_exists="replace", index=False)
    issues.to_sql("data_contract_issues", conn, if_exists="replace", index=False)


def _forget_replaced_warehouse(conn: sqlite3.Connection, simulated: bool) -> None:
    """A replaced warehouse takes its open findings, and any sample experiments, with it."""
    conn.execute("DROP TABLE IF EXISTS action_register")
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if simulated or not {"experiment_assignments", "experiment_catalog"} <= tables:
        return
    # Experiments a user imported are real and stay; the generated samples never sit
    # beside real customers.
    conn.execute("DELETE FROM experiment_assignments WHERE data_status = 'Simulated'")
    conn.execute(
        """
        DELETE FROM experiment_catalog
        WHERE experiment_id NOT IN (SELECT DISTINCT experiment_id FROM experiment_assignments)
        """
    )


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
        if load_mode == "replace":
            simulated = str(result.metadata.get("transaction_status")) == "Simulated"
            _forget_replaced_warehouse(conn, simulated)
        _store_quality(conn, result, load_mode, source_name, skipped)
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
    clear_query_cache()
    if str(result.metadata.get("transaction_status")) == "Simulated":
        # Sample experiments are invented, so they never sit beside real customers.
        seed_demo_experiments(db_path)
        clear_query_cache()
    return {"inserted_rows": inserted, "skipped_rows": skipped}


def warehouse_schema_version(db_path: str | Path) -> str | None:
    """Return the schema a warehouse was built with, or None for one predating versioning."""
    if not table_exists(db_path, "data_profiles"):
        return None
    frame = query_df(db_path, "SELECT * FROM data_profiles LIMIT 1")
    if frame.empty or "schema_version" not in frame.columns:
        return None
    return str(frame.iloc[0]["schema_version"])


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


@lru_cache(maxsize=128)
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
