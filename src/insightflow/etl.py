from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import DEFAULT_CONTRACT_PATH, DEFAULT_CURRENCY, RETURN_RECOVERY_RATE, env_bool
from .currency import PROFILE_CURRENCY, normalize_code
from .data_contracts import (
    ContractIssue,
    contract_block_message,
    contract_score,
    load_contract,
    row_rejections,
    validate_contract,
)
from .geography import canonical_country, market_region, shipping_multiplier
from .ingest import (
    EXCEL_SUFFIXES,
    SUPPORTED_SUFFIXES,
    canonical_field,
    parse_datetime,
    parse_number,
    parse_rate,
    read_excel_best_sheet,
    read_table,
)

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
    "currency",
]
CANONICAL_COLUMNS = BASE_COLUMNS + OPTIONAL_ECONOMIC_COLUMNS
# A line's economics are Verified only when each of these came from the source. A sale
# line carries no return handling, so that input is only expected on reversal lines.
# Discount is not among them: without a discount column the price is what was paid.
PROFIT_INPUTS = ("unit_cost", "shipping_cost", "payment_fee", "marketing_cost")
INVENTORY_INPUTS = ("supplier", "supplier_lead_days", "inventory_on_hand", "reorder_point")
MONEY_INPUTS = (
    "unit_price",
    "unit_cost",
    "shipping_cost",
    "payment_fee",
    "marketing_cost",
    "return_processing_cost",
)

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


SCHEMA_VERSION = "6.0"
# Above this share of rejected lines the file is more likely mis-mapped than merely messy.
MAX_REJECTED_SHARE = 0.30
DEFAULT_LEAD_DAYS = 14
MAX_DISCOUNT = 0.90
NON_MERCHANDISE = "non_merchandise"

# Postage, fees, adjustments and vouchers sit in sales ledgers beside real products but
# are not sales of goods. Short codes such as M, D or C2 could be real SKUs elsewhere, so
# lines are matched by name, and by code only where the code cannot mean anything else.
_SERVICE_CODES = re.compile(r"^(BANK ?CHARGES|AMAZONFEE|CRUK|ADJUST\d*|TEST\d+|GIFT_\S+)$")
_SERVICE_NAMES = re.compile(
    r"^(POSTAGE|DOTCOM POSTAGE|CARRIAGE|MANUAL|DISCOUNT|SAMPLES?|BANK CHARGES?|AMAZON FEE"
    r"|CRUK COMMISSION|SHIPPING( FEE| COST)?|FREIGHT( CHARGE)?|DELIVERY (FEE|CHARGE)"
    r"|HANDLING (FEE|CHARGE)|ADJUST BAD DEBT|ADJUSTMENT\b.*|THIS IS A TEST.*|.*GIFT VOUCHER.*"
    r"|.*GIFT CARD.*|PADS TO MATCH ALL CUSHIONS|运费|邮费|快递费|手续费|佣金|礼品卡|代金券)$"
)
# Words that describe a product rather than name what it is.
_DESCRIPTIVE_WORDS = frozenset(
    """
    AND THE FOR WITH SET PACK OF ASSORTED COLOUR COLOURS COLOR COLORS DESIGN LARGE SMALL MEDIUM
    MINI JUMBO GIANT BIG LITTLE RED BLUE PINK GREEN WHITE BLACK IVORY CREAM YELLOW ORANGE PURPLE
    GREY GRAY GOLD SILVER BROWN NATURAL VINTAGE RETROSPOT POLKADOT HANGING STRIPE STRIPES SPOTS
    SPOTTY FLORAL ROSE ROSES HEART HEARTS STAR STARS LOVE DOLLY GIRL BOY RETRO ENGLISH ROSE
    REGENCY PAISLEY SKULL SKULLS ANTIQUE WOODEN METAL GLASS CERAMIC ZINC TIN PAPER FELT
    """.split()
)
MIN_PRODUCTS_FOR_FAMILIES = 100
MIN_FAMILY_SHARE = 0.35


@dataclass
class ETLResult:
    curated: pd.DataFrame
    quality_summary: pd.DataFrame
    quality_dimensions: pd.DataFrame
    contract_issues: pd.DataFrame
    metadata: dict[str, Any]

    @property
    def rejected(self) -> pd.DataFrame:
        """Lines kept for audit but left out of every metric."""
        return self.curated.loc[self.curated["reject_reason"].notna()]

    @property
    def problem_rows(self) -> int:
        reasons = self.curated["reject_reason"]
        return int((reasons.notna() & (reasons != NON_MERCHANDISE)).sum())

    @property
    def problem_share(self) -> float:
        return self.problem_rows / max(len(self.curated), 1)

    def rejection_summary(self) -> pd.DataFrame:
        """Rejected lines by reason, with what they were worth, before anything is loaded."""
        rows = self.rejected
        return (
            rows.assign(amount=rows["quantity"] * rows["unit_price"])
            .groupby("reject_reason", as_index=False)
            .agg(rows=("amount", "size"), amount=("amount", "sum"))
            .rename(columns={"reject_reason": "reason"})
            .sort_values("rows", ascending=False)
        )

    def block_reasons(self) -> list[str]:
        """Why this batch must not load even with its problem rows set aside.

        A few bad rows should not stop a feed, so they load set aside and stay auditable.
        INSIGHTFLOW_STRICT_IMPORT restores all-or-nothing for pipelines that want it.
        """
        issues = self.contract_issues
        reasons = [str(item) for item in issues.loc[issues["severity"] == "P0", "message"]]
        if env_bool("INSIGHTFLOW_STRICT_IMPORT") and self.problem_rows:
            reasons.append(contract_block_message(issues))
        if self.problem_share > MAX_REJECTED_SHARE:
            reasons.append(
                f"{self.problem_share:.0%} 的行不符合契约，超过 {MAX_REJECTED_SHARE:.0%} 上限，"
                "更可能是字段映射或文件格式有误"
            )
        return reasons


def _stable_fraction(value: str, salt: str = "") -> float:
    digest = hashlib.sha256(f"{salt}|{value}".encode()).hexdigest()
    return int(digest[:12], 16) / float(16**12 - 1)


def _map_unique(series: pd.Series, function) -> pd.Series:
    """Apply a slow function once per distinct value. Ledgers repeat their keys heavily."""
    return series.map({value: function(value) for value in series.dropna().unique()})


def _stable_fractions(keys: pd.Series, salt: str) -> pd.Series:
    return _map_unique(keys, lambda key: _stable_fraction(key, salt))


def _canonical_name(column: object) -> object:
    return canonical_field(column) or column


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    canonical_names = [_canonical_name(column) for column in df.columns]
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
        "currency": pd.NA,
    }
    for column, default in defaults.items():
        if column not in renamed:
            renamed[column] = default
    return renamed[CANONICAL_COLUMNS]


def service_lines(stock_codes: pd.Series, descriptions: pd.Series) -> pd.Series:
    """Flag postage, fees, adjustments and vouchers, which are not sales of goods."""
    by_code = _map_unique(stock_codes, lambda code: bool(_SERVICE_CODES.match(code)))
    by_name = _map_unique(descriptions, lambda name: bool(_SERVICE_NAMES.match(name)))
    return by_code.astype("boolean").fillna(False) | by_name.astype("boolean").fillna(False)


def _singular(word: str) -> str:
    if word.endswith(("XES", "CHES", "SHES")):
        return word[:-2]
    # The exclusions keep words such as GLASS, CHRISTMAS, CACTUS and TENNIS whole.
    return word[:-1] if word.endswith("S") and word[-2] not in "SAUI" else word


def derive_categories(descriptions: pd.Series, limit: int = 30) -> pd.Series | None:
    """Group products into families by the nouns their names share.

    Only for sources with no category column. Each product joins the family of the last
    common noun in its name, the word English product names usually end on. Returns None
    when names are too few, or too unlike each other, for families to mean anything.
    """
    names = pd.Series(descriptions.dropna().unique(), dtype="string")
    if len(names) < MIN_PRODUCTS_FOR_FAMILIES:
        return None

    def nouns(name: str) -> list[str]:
        words = re.findall(r"[A-Z]{3,}", name)
        return [_singular(word) for word in words if word not in _DESCRIPTIVE_WORDS]

    tokens = {name: nouns(name) for name in names}
    last_words = pd.Series([words[-1] for words in tokens.values() if words], dtype="string")
    if last_words.empty:
        return None
    families = set(last_words.value_counts().head(limit).index)

    def family(name: str) -> str:
        return next((word.title() for word in reversed(tokens[name]) if word in families), "Other")

    labelled = names.map(family)
    if (labelled != "Other").mean() < MIN_FAMILY_SHARE:
        return None
    return descriptions.map(dict(zip(names, labelled, strict=True)))


def _fill_product_economics(work: pd.DataFrame) -> pd.DataFrame:
    """Fill absent economic inputs with documented rules.

    A reversal line undoes an earlier sale, so the shipping, payment and marketing money
    spent on that sale stays spent: rules derive no new costs for it, and only return
    handling is added. Values the source did supply are always kept.

    Only costs are estimated. A missing discount means the price is what was paid, so
    revenue still reconciles to the source file, and stock levels or suppliers that the
    source does not hold stay empty rather than being made up.
    """
    work = work.copy()
    is_cancel = work["quantity"] < 0
    product_keys = work["stock_code"].fillna("UNKNOWN").astype(str)
    median_price_by_product = (
        work.groupby("stock_code")["unit_price"]
        .transform("median")
        .fillna(work["unit_price"].median())
    )
    category_ratio = work["category"].map(CATEGORY_COST_RATIO).fillna(0.50)
    stable_cost_noise = 0.92 + 0.16 * _stable_fractions(product_keys, "cost")
    derived_unit_cost = median_price_by_product * category_ratio * stable_cost_noise
    work["unit_cost"] = pd.to_numeric(work["unit_cost"], errors="coerce").fillna(derived_unit_cost)
    work["unit_cost"] = work["unit_cost"].clip(lower=0.01).round(2)

    work["discount_rate"] = pd.to_numeric(work["discount_rate"], errors="coerce").fillna(0.0)
    work["discount_rate"] = work["discount_rate"].clip(0, MAX_DISCOUNT)

    abs_qty = work["quantity"].abs().fillna(0)
    gross_value = abs_qty * work["unit_price"].fillna(0)
    country_mult = _map_unique(work["country"], shipping_multiplier)
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
        derived_shipping.where(~is_cancel, 0.0)
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
        (discounted_value * payment_rate).where(~is_cancel, 0.0)
    )
    work["marketing_cost"] = pd.to_numeric(work["marketing_cost"], errors="coerce").fillna(
        (gross_value * marketing_rate).where(~is_cancel, 0.0)
    )

    derived_return = 2.0 + 4.5 * _stable_fractions(product_keys, "return")
    work["return_processing_cost"] = pd.to_numeric(
        work["return_processing_cost"], errors="coerce"
    ).fillna(pd.Series(np.where(is_cancel, derived_return, 0.0), index=work.index))

    work["price_elasticity"] = pd.to_numeric(work["price_elasticity"], errors="coerce").fillna(
        work["category"].map(CATEGORY_ELASTICITY).fillna(-1.4)
        + (_stable_fractions(product_keys, "elasticity") - 0.5) * 0.25
    )
    work["supplier"] = work["supplier"].fillna("Unknown").astype("string")
    work["supplier_lead_days"] = pd.to_numeric(work["supplier_lead_days"], errors="coerce").fillna(
        DEFAULT_LEAD_DAYS
    )
    work["inventory_on_hand"] = pd.to_numeric(work["inventory_on_hand"], errors="coerce")
    work["reorder_point"] = pd.to_numeric(work["reorder_point"], errors="coerce")
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
            & (work["discount_rate"].between(0, MAX_DISCOUNT))
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


def _dataset_status(statuses: pd.Series) -> str:
    values = statuses.dropna().unique().tolist()
    return str(values[0]) if len(values) == 1 else "Mixed"


def _convert_currency(
    work: pd.DataFrame, reporting: str, fx_rates: dict[str, float] | None
) -> tuple[pd.DataFrame, list[ContractIssue]]:
    """Express money in the reporting currency; refuse amounts with no stated rate."""
    codes = work["currency"].map(lambda code: normalize_code(code, reporting))
    known = {code.upper(): float(rate) for code, rate in (fx_rates or {}).items()}
    known[reporting] = 1.0
    rates = codes.map(known)
    unknown = rates.isna()
    issues: list[ContractIssue] = []
    if unknown.any():
        listed = ", ".join(sorted(codes[unknown].unique()))
        message = f"{listed} 无法折算为 {reporting}，请提供汇率"
        issues.append(
            ContractIssue("P0", "fx_rate_missing", "currency", int(unknown.sum()), message)
        )
    rate = rates.fillna(1.0)
    for column in MONEY_INPUTS:
        work[column] = work[column] * rate
    work["currency"] = reporting
    work["fx_rate"] = rate
    return work, issues


def clean_transactions(
    df: pd.DataFrame,
    *,
    source_profile: str = "manual_import",
    transaction_status: str | None = None,
    currency: str | None = None,
    fx_rates: dict[str, float] | None = None,
) -> ETLResult:
    transaction_status = transaction_status or (
        "Simulated"
        if source_profile.startswith("demo") or source_profile.startswith("multitable_demo")
        else "Verified"
    )
    reporting_currency = normalize_code(
        currency or PROFILE_CURRENCY.get(source_profile, DEFAULT_CURRENCY)
    )

    raw = normalize_columns(df)
    raw["country"] = _map_unique(raw["country"].fillna("Unknown"), canonical_country)
    known_region = _map_unique(raw["country"], market_region)
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
    category_source = "source"
    if work["category"].eq("Uncategorized").all():
        families = derive_categories(work["description"])
        if families is not None:
            work["category"] = families.fillna("Other").astype("string")
            category_source = "derived"
    work["country"] = work["country"].astype("string")
    work["market_region"] = _map_unique(work["country"], market_region).astype("string")
    work["channel"] = work["channel"].fillna("Unknown").astype("string").str.strip().str.title()
    work["invoice_date"] = parse_datetime(work["invoice_date"])
    work["quantity"] = parse_number(work["quantity"])
    for column in MONEY_INPUTS:
        work[column] = parse_number(work[column])
    work["discount_rate"] = parse_rate(work["discount_rate"])
    customer_raw = work["customer_id"]
    # Spreadsheet readers turn numeric identifiers into 17850.0; keep the original key.
    work["customer_id"] = (
        customer_raw.astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    )
    invalid_customer_tokens = work["customer_id"].str.lower().isin({"", "nan", "none", "<na>"})
    work.loc[customer_raw.isna() | invalid_customer_tokens, "customer_id"] = pd.NA

    invalid_date = work["invoice_date"].isna()
    invalid_quantity = work["quantity"].isna() | (work["quantity"] == 0)
    invalid_price = work["unit_price"].isna() | (work["unit_price"] <= 0)
    missing_customer = work["customer_id"].isna()
    work["is_cancellation"] = (work["quantity"] < 0).fillna(False)
    non_merchandise = service_lines(work["stock_code"], work["description"]).astype(bool)

    work, currency_issues = _convert_currency(work, reporting_currency, fx_rates)

    # The contract judges the values the source actually sent. Rule-based filling and
    # clipping happen afterwards, so they can never hide an out-of-range input.
    contract = load_contract(DEFAULT_CONTRACT_PATH)
    contract_issues = validate_contract(work, contract)
    # Rows the contract refuses stay in the warehouse for audit but out of every metric.
    work["reject_reason"] = row_rejections(work, contract).mask(non_merchandise, NON_MERCHANDISE)
    work["description"] = work["description"].fillna(work["stock_code"])
    if currency_issues:
        extra = pd.DataFrame([issue.__dict__ for issue in currency_issues])
        kept = contract_issues.loc[contract_issues["severity"] != "PASS"]
        contract_issues = pd.concat([extra, kept], ignore_index=True)

    economics_supplied = work[list(PROFIT_INPUTS)].notna().all(axis=1) & (
        work["return_processing_cost"].notna() | ~work["is_cancellation"]
    )
    discount_supplied = work["discount_rate"].notna()
    inventory_supplied = work[list(INVENTORY_INPUTS)].notna().all(axis=1)

    work = _fill_product_economics(work)
    work["source_profile"] = source_profile
    work["transaction_data_status"] = transaction_status
    if transaction_status == "Simulated":
        work["economic_data_status"] = "Simulated"
        work["discount_data_status"] = "Simulated"
        work["inventory_data_status"] = "Simulated"
    else:
        work["economic_data_status"] = np.where(economics_supplied, "Verified", "Estimated")
        work["discount_data_status"] = np.where(discount_supplied, "Verified", "Estimated")
        work["inventory_data_status"] = np.where(inventory_supplied, "Verified", "Missing")
    economic_status = _dataset_status(work["economic_data_status"])
    discount_status = _dataset_status(work["discount_data_status"])
    inventory_status = _dataset_status(work["inventory_data_status"])
    data_mode = (
        transaction_status if transaction_status == economic_status == inventory_status else "Mixed"
    )
    work["data_mode"] = data_mode

    # Signed line economics: a reversal is the mirror image of the sale it undoes, so any
    # SUM over sales and reversals together yields the result after returns.
    recovered = np.where(work["is_cancellation"], RETURN_RECOVERY_RATE, 1.0)
    work["gross_revenue"] = (work["quantity"] * work["unit_price"]).round(2)
    work["discount_amount"] = (work["gross_revenue"] * work["discount_rate"]).round(2)
    work["net_revenue"] = (work["gross_revenue"] - work["discount_amount"]).round(2)
    work["cogs"] = (work["quantity"] * work["unit_cost"] * recovered).round(2)
    work["gross_profit"] = (work["net_revenue"] - work["cogs"]).round(2)
    work["operating_variable_cost"] = (
        work["shipping_cost"]
        + work["payment_fee"]
        + work["marketing_cost"]
        + work["return_processing_cost"]
    ).round(2)
    work["contribution_profit"] = (work["gross_profit"] - work["operating_variable_cost"]).round(2)
    work["return_loss"] = np.where(work["is_cancellation"], -work["contribution_profit"], 0.0)
    work["line_value"] = work["gross_revenue"]
    work["data_valid"] = ~(invalid_date | invalid_quantity | invalid_price) & work[
        "reject_reason"
    ].isna()
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

    quality_rows = [
        ("raw_rows", initial_rows, "原始行数"),
        ("duplicate_rows_removed", int(duplicate_mask.sum()), "完全重复记录"),
        ("invalid_date_rows", int(invalid_date.sum()), "无法解析日期"),
        ("invalid_quantity_rows", int(invalid_quantity.sum()), "数量为空或为零"),
        ("invalid_price_rows", int(invalid_price.sum()), "价格为空、为零或为负"),
        ("missing_customer_rows", int(missing_customer.sum()), "客户编号缺失"),
        ("cancellation_rows", int((work["is_cancellation"] & work["data_valid"]).sum()), "取消/退货行"),
        ("non_merchandise_rows", int(non_merchandise.sum()), "运费、手续费、调整等非商品行"),
        ("rejected_rows", int(work["reject_reason"].notna().sum()), "保留备查但不计入指标的行"),
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
        "schema_version": SCHEMA_VERSION,
        "source_profile": source_profile,
        "data_mode": data_mode,
        "transaction_status": transaction_status,
        "economic_status": economic_status,
        "discount_status": discount_status,
        "inventory_status": inventory_status,
        "category_source": category_source,
        "currency": reporting_currency,
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
        canonical = {_canonical_name(column) for column in preview.columns}
        missing = [column for column in REQUIRED_COLUMNS if column not in canonical]
        if not missing:
            return read_excel_best_sheet(workbook)
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
    if suffix in EXCEL_SUFFIXES:
        return read_excel_transactions(source)
    if suffix in SUPPORTED_SUFFIXES:
        return read_table(source)
    raise ValueError(f"不支持的数据格式: {suffix}")
