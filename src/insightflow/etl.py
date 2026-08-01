from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import DEFAULT_CONTRACT_PATH
from .data_contracts import contract_score, load_contract, validate_contract
from .geography import canonical_country, market_region, shipping_multiplier

REQUIRED_COLUMNS = [
    "invoice_no",
    "stock_code",
    "description",
    "quantity",
    "invoice_date",
    "unit_price",
    "country",
]
BASE_COLUMNS = [
    "invoice_no",
    "stock_code",
    "description",
    "category",
    "quantity",
    "invoice_date",
    "unit_price",
    "customer_id",
    "country",
    "market_region",
    "channel",
]
OPTIONAL_ECONOMIC_COLUMNS = [
    "discount_rate",
    "unit_cost",
    "shipping_cost",
    "payment_fee",
    "marketing_cost",
    "return_processing_cost",
    "price_elasticity",
    "supplier",
    "supplier_lead_days",
    "inventory_on_hand",
    "reorder_point",
]
CANONICAL_COLUMNS = BASE_COLUMNS + OPTIONAL_ECONOMIC_COLUMNS

COLUMN_ALIASES = {
    "Invoice": "invoice_no",
    "InvoiceNo": "invoice_no",
    "StockCode": "stock_code",
    "Description": "description",
    "Quantity": "quantity",
    "InvoiceDate": "invoice_date",
    "Price": "unit_price",
    "UnitPrice": "unit_price",
    "Customer ID": "customer_id",
    "CustomerID": "customer_id",
    "Country": "country",
    "Category": "category",
    "Channel": "channel",
    "DiscountRate": "discount_rate",
    "UnitCost": "unit_cost",
    "ShippingCost": "shipping_cost",
    "PaymentFee": "payment_fee",
    "MarketingCost": "marketing_cost",
    "ReturnProcessingCost": "return_processing_cost",
}

CATEGORY_COST_RATIO = {
    "Home Decor": 0.48,
    "Kitchen": 0.52,
    "Gifts": 0.44,
    "Stationery": 0.39,
    "Seasonal": 0.56,
    "Wellness": 0.46,
    "Electronics": 0.67,
    "Beauty": 0.43,
    "Apparel": 0.51,
    "Sports & Outdoors": 0.57,
    "Pet Supplies": 0.49,
    "Books & Media": 0.45,
    "Uncategorized": 0.50,
}
CATEGORY_ELASTICITY = {
    "Home Decor": -1.35,
    "Kitchen": -1.15,
    "Gifts": -1.55,
    "Stationery": -1.80,
    "Seasonal": -1.95,
    "Wellness": -1.10,
    "Electronics": -1.25,
    "Beauty": -1.45,
    "Apparel": -1.70,
    "Sports & Outdoors": -1.40,
    "Pet Supplies": -1.05,
    "Books & Media": -1.60,
    "Uncategorized": -1.40,
}


@dataclass
class ETLResult:
    curated: pd.DataFrame
    quality_summary: pd.DataFrame
    quality_dimensions: pd.DataFrame
    contract_issues: pd.DataFrame
    metadata: dict[str, Any]


def _stable_fraction(value: str, salt: str = "") -> float:
    digest = hashlib.sha256(f"{salt}|{value}".encode()).hexdigest()
    return int(digest[:12], 16) / float(16**12 - 1)


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    canonical_names = [COLUMN_ALIASES.get(column, column) for column in df.columns]
    duplicated = pd.Index(canonical_names)[pd.Index(canonical_names).duplicated()].unique().tolist()
    if duplicated:
        raise ValueError(
            "字段别名映射后出现重复列: "
            + ", ".join(map(str, duplicated))
            + "。请删除重复字段或只保留一个标准列名。"
        )
    renamed = df.copy()
    renamed.columns = canonical_names
    missing_required = [c for c in REQUIRED_COLUMNS if c not in renamed.columns]
    if missing_required:
        raise ValueError(f"缺少必要字段: {', '.join(missing_required)}")
    defaults = {
        "customer_id": pd.NA,
        "category": "Uncategorized",
        "market_region": pd.NA,
        "channel": "Unknown",
        "discount_rate": pd.NA,
        "unit_cost": pd.NA,
        "shipping_cost": pd.NA,
        "payment_fee": pd.NA,
        "marketing_cost": pd.NA,
        "return_processing_cost": pd.NA,
        "price_elasticity": pd.NA,
        "supplier": pd.NA,
        "supplier_lead_days": pd.NA,
        "inventory_on_hand": pd.NA,
        "reorder_point": pd.NA,
    }
    for column, default in defaults.items():
        if column not in renamed:
            renamed[column] = default
    return renamed[CANONICAL_COLUMNS]


def _fill_product_economics(work: pd.DataFrame) -> pd.DataFrame:
    work = work.copy()
    product_keys = work["stock_code"].fillna("UNKNOWN").astype(str)
    median_price_by_product = (
        work.groupby("stock_code")["unit_price"]
        .transform("median")
        .fillna(work["unit_price"].median())
    )
    category_ratio = work["category"].map(CATEGORY_COST_RATIO).fillna(0.50)
    stable_cost_noise = product_keys.map(lambda x: 0.92 + 0.16 * _stable_fraction(x, "cost"))
    derived_unit_cost = median_price_by_product * category_ratio * stable_cost_noise
    work["unit_cost"] = pd.to_numeric(work["unit_cost"], errors="coerce").fillna(derived_unit_cost)
    work["unit_cost"] = work["unit_cost"].clip(lower=0.01).round(2)

    channel_discount = (
        work["channel"]
        .map(
            {
                "Web": 0.025,
                "Marketplace": 0.055,
                "Wholesale": 0.085,
                "Mobile App": 0.035,
                "Retail Store": 0.020,
                "Social Commerce": 0.070,
            }
        )
        .fillna(0.03)
    )
    stable_discount = product_keys.map(lambda x: (_stable_fraction(x, "discount") - 0.5) * 0.02)
    work["discount_rate"] = pd.to_numeric(work["discount_rate"], errors="coerce").fillna(
        channel_discount + stable_discount
    )
    work["discount_rate"] = work["discount_rate"].clip(0, 0.35)

    abs_qty = work["quantity"].abs().fillna(0)
    gross_value = abs_qty * work["unit_price"].fillna(0)
    country_mult = work["country"].map(lambda value: shipping_multiplier(value))
    channel_shipping = (
        work["channel"]
        .map(
            {
                "Web": 1.00,
                "Marketplace": 1.08,
                "Wholesale": 0.72,
                "Mobile App": 1.00,
                "Retail Store": 0.45,
                "Social Commerce": 1.12,
            }
        )
        .fillna(1.0)
    )
    derived_shipping = (1.15 + 0.16 * abs_qty) * country_mult * channel_shipping
    work["shipping_cost"] = pd.to_numeric(work["shipping_cost"], errors="coerce").fillna(
        derived_shipping
    )

    payment_rate = (
        work["channel"]
        .map(
            {
                "Web": 0.018,
                "Marketplace": 0.026,
                "Wholesale": 0.008,
                "Mobile App": 0.020,
                "Retail Store": 0.012,
                "Social Commerce": 0.030,
            }
        )
        .fillna(0.02)
    )
    marketing_rate = (
        work["channel"]
        .map(
            {
                "Web": 0.052,
                "Marketplace": 0.036,
                "Wholesale": 0.012,
                "Mobile App": 0.046,
                "Retail Store": 0.028,
                "Social Commerce": 0.080,
            }
        )
        .fillna(0.04)
    )
    discounted_value = gross_value * (1 - work["discount_rate"])
    work["payment_fee"] = pd.to_numeric(work["payment_fee"], errors="coerce").fillna(
        discounted_value * payment_rate
    )
    work["marketing_cost"] = pd.to_numeric(work["marketing_cost"], errors="coerce").fillna(
        gross_value * marketing_rate
    )

    is_cancel = work["invoice_no"].astype("string").str.upper().str.startswith("C", na=False) | (
        work["quantity"] < 0
    )
    derived_return = product_keys.map(lambda x: 2.0 + 4.5 * _stable_fraction(x, "return"))
    work["return_processing_cost"] = pd.to_numeric(
        work["return_processing_cost"], errors="coerce"
    ).fillna(pd.Series(np.where(is_cancel, derived_return, 0.0), index=work.index))

    work["price_elasticity"] = pd.to_numeric(work["price_elasticity"], errors="coerce").fillna(
        work["category"].map(CATEGORY_ELASTICITY).fillna(-1.4)
        + product_keys.map(lambda x: (_stable_fraction(x, "elasticity") - 0.5) * 0.25)
    )
    suppliers = ["Northstar Supply", "BluePeak Trading", "Oakline Goods", "Meridian Wholesale"]
    derived_supplier = product_keys.map(
        lambda x: suppliers[
            min(int(_stable_fraction(x, "supplier") * len(suppliers)), len(suppliers) - 1)
        ]
    )
    work["supplier"] = work["supplier"].fillna(derived_supplier).astype("string")
    work["supplier_lead_days"] = pd.to_numeric(work["supplier_lead_days"], errors="coerce").fillna(
        product_keys.map(lambda x: 7 + int(28 * _stable_fraction(x, "lead")))
    )
    work["inventory_on_hand"] = pd.to_numeric(work["inventory_on_hand"], errors="coerce").fillna(
        product_keys.map(lambda x: 40 + int(1500 * _stable_fraction(x, "inventory")))
    )
    work["reorder_point"] = pd.to_numeric(work["reorder_point"], errors="coerce").fillna(
        work["inventory_on_hand"]
        * product_keys.map(lambda x: 0.14 + 0.18 * _stable_fraction(x, "reorder"))
    )
    for column in (
        "shipping_cost",
        "payment_fee",
        "marketing_cost",
        "return_processing_cost",
    ):
        work[column] = work[column].clip(lower=0).round(2)
    work["supplier_lead_days"] = work["supplier_lead_days"].clip(1, 120).round().astype("Int64")
    work["inventory_on_hand"] = work["inventory_on_hand"].clip(0).round().astype("Int64")
    work["reorder_point"] = work["reorder_point"].clip(0).round().astype("Int64")
    return work


def _quality_dimensions(
    work: pd.DataFrame,
    *,
    initial_rows: int,
    duplicate_rows: int,
    invalid_date: pd.Series,
    invalid_quantity: pd.Series,
    invalid_price: pd.Series,
    missing_customer: pd.Series,
) -> pd.DataFrame:
    denominator = max(initial_rows, 1)
    completeness = 1 - float(missing_customer.sum()) / denominator
    uniqueness = 1 - duplicate_rows / denominator
    validity = 1 - float((invalid_date | invalid_quantity | invalid_price).sum()) / denominator
    consistency = float(
        (
            work["stock_code"].notna()
            & work["description"].notna()
            & (work["discount_rate"].between(0, 0.35))
            & (work["unit_cost"] > 0)
        ).mean()
    )
    max_date = work["invoice_date"].max()
    min_date = work["invoice_date"].min()
    coverage_days = (
        max((max_date - min_date).days, 0) if pd.notna(max_date) and pd.notna(min_date) else 0
    )
    freshness = 1.0 if coverage_days >= 30 else coverage_days / 30
    rows = [
        ("完整性", completeness, "关键客户字段的非空程度"),
        ("唯一性", uniqueness, "完全重复记录控制"),
        ("有效性", validity, "日期、数量和价格的合法程度"),
        ("一致性", consistency, "商品、折扣和成本口径一致性"),
        ("覆盖度", freshness, "数据时间跨度是否足以支持经营分析"),
    ]
    out = pd.DataFrame(rows, columns=["dimension", "score", "description"])
    out["score_100"] = (out["score"].clip(0, 1) * 100).round(1)
    return out


def clean_transactions(
    df: pd.DataFrame,
    *,
    source_profile: str = "manual_import",
    transaction_status: str | None = None,
) -> ETLResult:
    aliased_columns = {COLUMN_ALIASES.get(column, column) for column in df.columns}
    transaction_status = transaction_status or (
        "Simulated"
        if source_profile.startswith("demo") or source_profile.startswith("multitable_demo")
        else "Verified"
    )
    economic_inputs = {
        "discount_rate",
        "unit_cost",
        "shipping_cost",
        "payment_fee",
        "marketing_cost",
        "return_processing_cost",
        "price_elasticity",
    }
    inventory_inputs = {"supplier", "supplier_lead_days", "inventory_on_hand", "reorder_point"}
    if transaction_status == "Simulated":
        economic_status = "Simulated"
        inventory_status = "Simulated"
    else:
        economic_status = "Verified" if economic_inputs.issubset(aliased_columns) else "Estimated"
        inventory_status = "Verified" if inventory_inputs.issubset(aliased_columns) else "Simulated"
    data_mode = (
        transaction_status if transaction_status == economic_status == inventory_status else "Mixed"
    )

    raw = normalize_columns(df)
    raw["country"] = raw["country"].fillna("Unknown").map(canonical_country)
    known_region = raw["country"].map(market_region)
    supplied_region = raw["market_region"].astype("string").str.strip()
    invalid_region = supplied_region.str.lower().isin({"", "nan", "none", "<na>", "unknown"})
    raw["market_region"] = supplied_region.mask(invalid_region, known_region).fillna(known_region)
    initial_rows = len(raw)
    duplicate_mask = raw.duplicated(keep="first")

    work = raw.loc[~duplicate_mask].copy()
    work["invoice_no"] = work["invoice_no"].astype("string").str.strip()
    work["stock_code"] = work["stock_code"].astype("string").str.strip().str.upper()
    work["description"] = work["description"].astype("string").str.strip().str.upper()
    work["category"] = (
        work["category"].fillna("Uncategorized").astype("string").str.strip().str.title()
    )
    work["country"] = work["country"].fillna("Unknown").map(canonical_country).astype("string")
    work["market_region"] = work["country"].map(market_region).astype("string")
    work["channel"] = work["channel"].fillna("Unknown").astype("string").str.strip().str.title()
    work["invoice_date"] = pd.to_datetime(work["invoice_date"], errors="coerce")
    work["quantity"] = pd.to_numeric(work["quantity"], errors="coerce")
    work["unit_price"] = pd.to_numeric(work["unit_price"], errors="coerce")
    customer_raw = work["customer_id"]
    work["customer_id"] = customer_raw.astype("string").str.strip()
    invalid_customer_tokens = work["customer_id"].str.lower().isin({"", "nan", "none", "<na>"})
    work.loc[customer_raw.isna() | invalid_customer_tokens, "customer_id"] = pd.NA

    invalid_date = work["invoice_date"].isna()
    invalid_quantity = work["quantity"].isna() | (work["quantity"] == 0)
    invalid_price = work["unit_price"].isna() | (work["unit_price"] <= 0)
    missing_customer = work["customer_id"].isna()

    work = _fill_product_economics(work)
    work["source_profile"] = source_profile
    work["data_mode"] = data_mode
    work["transaction_data_status"] = transaction_status
    work["economic_data_status"] = economic_status
    work["inventory_data_status"] = inventory_status

    contract = load_contract(DEFAULT_CONTRACT_PATH)
    contract_issues = validate_contract(work, contract)
    work["is_cancellation"] = work["invoice_no"].str.upper().str.startswith("C", na=False) | (
        work["quantity"] < 0
    )
    abs_quantity = work["quantity"].abs()
    sign = np.where(work["quantity"] < 0, -1.0, 1.0)
    work["gross_revenue"] = abs_quantity * work["unit_price"]
    work["discount_amount"] = work["gross_revenue"] * work["discount_rate"]
    work["net_revenue"] = sign * (work["gross_revenue"] - work["discount_amount"])
    work["cogs"] = abs_quantity * work["unit_cost"]
    work["gross_profit"] = work["net_revenue"] - work["cogs"]
    work["operating_variable_cost"] = (
        work["shipping_cost"]
        + work["payment_fee"]
        + work["marketing_cost"]
        + work["return_processing_cost"]
    )
    work["contribution_profit"] = work["gross_profit"] - work["operating_variable_cost"]
    work["return_loss"] = np.where(
        work["is_cancellation"], work["net_revenue"].abs() + work["return_processing_cost"], 0.0
    )
    work["line_value"] = work["gross_revenue"]
    work["data_valid"] = ~(invalid_date | invalid_quantity | invalid_price)
    work["sale_valid"] = work["data_valid"] & ~work["is_cancellation"] & (work["quantity"] > 0)
    work["year"] = work["invoice_date"].dt.year
    work["month"] = work["invoice_date"].dt.to_period("M").astype("string")
    work["date"] = work["invoice_date"].dt.date

    hash_columns = ["invoice_no", "stock_code", "quantity", "invoice_date", "unit_price"]
    work["record_hash"] = (
        pd.util.hash_pandas_object(work[hash_columns].astype("string"), index=False)
        .astype("uint64")
        .astype("string")
    )

    currency_columns = [
        "gross_revenue",
        "discount_amount",
        "net_revenue",
        "cogs",
        "gross_profit",
        "operating_variable_cost",
        "contribution_profit",
        "return_loss",
    ]
    work[currency_columns] = work[currency_columns].round(2)

    quality_rows = [
        ("raw_rows", initial_rows, "原始行数"),
        ("duplicate_rows_removed", int(duplicate_mask.sum()), "完全重复记录"),
        ("invalid_date_rows", int(invalid_date.sum()), "无法解析日期"),
        ("invalid_quantity_rows", int(invalid_quantity.sum()), "数量为空或为零"),
        ("invalid_price_rows", int(invalid_price.sum()), "价格为空、为零或为负"),
        ("missing_customer_rows", int(missing_customer.sum()), "客户编号缺失"),
        ("cancellation_rows", int(work["is_cancellation"].sum()), "取消/退货行"),
        ("curated_rows", len(work), "去重后的标准化记录"),
        ("valid_sales_rows", int(work["sale_valid"].sum()), "有效销售记录"),
    ]
    quality = pd.DataFrame(quality_rows, columns=["metric", "value", "description"])
    dimensions = _quality_dimensions(
        work,
        initial_rows=initial_rows,
        duplicate_rows=int(duplicate_mask.sum()),
        invalid_date=invalid_date,
        invalid_quantity=invalid_quantity,
        invalid_price=invalid_price,
        missing_customer=missing_customer,
    )
    contract_dimension = pd.DataFrame(
        [("契约符合度", contract_score(contract_issues), "必要字段、主键、类型、范围和枚举规则")],
        columns=["dimension", "score_100", "description"],
    )
    contract_dimension["score"] = contract_dimension["score_100"] / 100
    dimensions = pd.concat(
        [dimensions, contract_dimension[["dimension", "score", "description", "score_100"]]],
        ignore_index=True,
    )

    metadata = {
        "raw_rows": initial_rows,
        "curated_rows": len(work),
        "valid_sales_rows": int(work["sale_valid"].sum()),
        "date_min": work["invoice_date"].min(),
        "date_max": work["invoice_date"].max(),
        "quality_score": float(dimensions["score_100"].mean()),
        "schema_version": "4.1",
        "source_profile": source_profile,
        "data_mode": data_mode,
        "transaction_status": transaction_status,
        "economic_status": economic_status,
        "inventory_status": inventory_status,
        "contract_id": contract.get("contract_id", "unknown"),
        "contract_issue_count": int((contract_issues["severity"] != "PASS").sum()),
    }
    return ETLResult(
        curated=work,
        quality_summary=quality,
        quality_dimensions=dimensions,
        contract_issues=contract_issues,
        metadata=metadata,
    )


def read_excel_transactions(source) -> pd.DataFrame:
    """Read the transaction worksheet from an Excel workbook.

    A workbook may also contain dictionaries, profiles, or report tabs. Concatenating
    every sheet corrupts the transaction grain and can create duplicate aliases such as
    ``description`` and ``Description``. Prefer a sheet named ``transactions``; otherwise
    select the first sheet whose headers satisfy the canonical required fields.
    """
    workbook = pd.ExcelFile(source)
    ordered = sorted(
        workbook.sheet_names,
        key=lambda name: (name.strip().lower() != "transactions", workbook.sheet_names.index(name)),
    )
    diagnostics: list[str] = []
    for sheet in ordered:
        preview = pd.read_excel(workbook, sheet_name=sheet, nrows=5)
        canonical = {COLUMN_ALIASES.get(column, column) for column in preview.columns}
        missing = [column for column in REQUIRED_COLUMNS if column not in canonical]
        if not missing:
            return pd.read_excel(workbook, sheet_name=sheet)
        diagnostics.append(f"{sheet}: missing {', '.join(missing)}")
    raise ValueError(
        "Excel中未找到可识别的交易工作表。需要字段: "
        + ", ".join(REQUIRED_COLUMNS)
        + "。工作表检查结果: "
        + "; ".join(diagnostics)
    )


def load_source(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(source)
    if suffix in {".xlsx", ".xls"}:
        return read_excel_transactions(source)
    if suffix == ".parquet":
        return pd.read_parquet(source)
    raise ValueError(f"不支持的数据格式: {suffix}")
