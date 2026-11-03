"""Tolerant readers and column mapping for real-world business exports.

Spreadsheets arrive with GBK encodings, Chinese headers, thousands separators and
Excel serial dates. Everything here turns such files into the canonical transaction
shape before the ETL layer applies its contract, so a messy file is either understood
or rejected with a precise reason. Nothing is guessed silently: every automatic
mapping carries a confidence the Data Hub shows to the user.
"""

from __future__ import annotations

import csv
import difflib
import hashlib
import io
import json
import re
import unicodedata
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "big5", "shift_jis", "cp1252", "latin-1")
TABULAR_SUFFIXES = {".csv", ".tsv", ".txt"}
EXCEL_SUFFIXES = {".xlsx", ".xls", ".xlsm"}
SUPPORTED_SUFFIXES = TABULAR_SUFFIXES | EXCEL_SUFFIXES | {".parquet", ".json", ".jsonl"}

# Canonical field -> names seen in ERP, marketplace and spreadsheet exports.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "invoice_no": (
        "invoice", "invoice no", "invoice number", "order", "order id", "order no",
        "order number", "transaction id", "receipt", "receipt no", "bill no",
        "订单号", "订单编号", "订单id", "单号", "发票号", "交易号", "交易编号", "流水号",
    ),
    "stock_code": (
        "stock code", "sku", "sku code", "sku id", "item code", "item id", "product id",
        "product code", "asin", "barcode", "goods id",
        "商品编码", "商品编号", "商品id", "货号", "物料编码", "条码", "款号",
    ),
    "description": (
        "description", "product", "product name", "item", "item name", "title", "goods name",
        "商品名称", "商品名", "产品名称", "品名", "商品", "商品标题", "产品",
    ),
    "category": (
        "category", "product category", "department", "item category",
        "品类", "类目", "分类", "商品类目", "商品分类", "产品类别", "一级类目",
    ),
    "quantity": (
        "quantity", "qty", "units", "count", "pcs", "amount sold",
        "数量", "销量", "件数", "销售数量", "购买数量", "商品数量",
    ),
    "invoice_date": (
        "invoice date", "order date", "date", "transaction date", "purchase date",
        "created at", "created", "timestamp", "datetime", "order time",
        "日期", "订单日期", "下单时间", "下单日期", "交易时间", "付款时间", "销售日期", "创建时间",
    ),
    "unit_price": (
        "unit price", "price", "sale price", "selling price", "unit sale price",
        "单价", "售价", "销售单价", "商品单价", "成交单价", "实付单价",
    ),
    "line_amount": (
        "line total", "line amount", "total", "amount", "sales", "revenue", "gmv",
        "order amount", "net sales", "extended price", "subtotal",
        "金额", "销售额", "总价", "小计", "实付金额", "成交金额", "订单金额", "行金额",
    ),
    "customer_id": (
        "customer", "customer id", "customer no", "client id", "buyer id", "member id",
        "user id", "account id", "buyer",
        "客户", "客户编号", "客户id", "会员id", "用户id", "买家id", "买家", "会员编号",
    ),
    "country": (
        "country", "country name", "nation", "market", "destination", "ship country",
        "国家", "国家地区", "地区", "市场", "销售国家", "收货国家", "目的国",
    ),
    "market_region": ("region", "market region", "sales region", "大区", "区域", "市场区域"),
    "channel": (
        "channel", "sales channel", "platform", "source", "store", "marketplace",
        "渠道", "销售渠道", "平台", "店铺", "来源", "销售平台",
    ),
    "discount_rate": ("discount", "discount rate", "discount pct", "折扣", "折扣率", "优惠率"),
    "discount_amount_input": ("discount amount", "coupon", "折扣金额", "优惠金额", "优惠券"),
    "unit_cost": (
        "unit cost", "cost", "cogs", "cost price", "purchase price", "unit cogs",
        "成本", "单位成本", "成本价", "采购价", "进价", "采购单价",
    ),
    "shipping_cost": (
        "shipping", "shipping cost", "freight", "freight value", "delivery cost", "logistics cost",
        "运费", "物流费", "物流成本", "快递费", "配送费",
    ),
    "payment_fee": (
        "payment fee", "transaction fee", "processing fee", "commission", "platform fee",
        "手续费", "支付手续费", "佣金", "平台费", "交易手续费",
    ),
    "marketing_cost": (
        "marketing", "marketing cost", "ad spend", "ads", "advertising", "advertising cost",
        "营销费", "营销费用", "广告费", "推广费", "投放费用",
    ),
    "return_processing_cost": ("return cost", "return fee", "return processing cost", "退货费", "退货成本"),
    "price_elasticity": ("elasticity", "price elasticity", "价格弹性"),
    "supplier": ("supplier", "vendor", "manufacturer", "供应商", "厂商", "厂家"),
    "supplier_lead_days": ("lead time", "lead days", "supplier lead days", "交期", "采购周期", "到货周期"),
    "inventory_on_hand": ("inventory", "stock", "on hand", "stock on hand", "库存", "现有库存", "可用库存"),
    "reorder_point": ("reorder point", "rop", "safety stock", "补货点", "安全库存"),
    "currency": ("currency", "currency code", "币种", "货币"),
    "order_status": ("status", "order status", "订单状态", "状态"),
}
REQUIRED_FIELDS = ("invoice_no", "stock_code", "quantity", "invoice_date", "unit_price", "country")
CANCELLED_STATUSES = {
    "cancelled", "canceled", "refunded", "returned", "unavailable", "void",
    "已取消", "取消", "已退款", "退款", "已退货", "退货",
}


def normalize_header(text: object) -> str:
    value = unicodedata.normalize("NFKC", str(text)).casefold()
    return re.sub(r"[\s_\-./\\()（）:：#]+", "", value)


_ALIAS_INDEX: dict[str, str] = {}
for _field, _names in FIELD_ALIASES.items():
    _ALIAS_INDEX[normalize_header(_field)] = _field
    for _name in _names:
        _ALIAS_INDEX[normalize_header(_name)] = _field


def canonical_field(column: object) -> str | None:
    """Return the canonical field an exact header variant stands for."""
    return _ALIAS_INDEX.get(normalize_header(column))


def decode_bytes(content: bytes) -> tuple[str, str]:
    """Decode a text export, preferring strict encodings so GBK never reads as mojibake."""
    for encoding in ENCODINGS:
        try:
            return content.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace"), "utf-8-replace"


def _sniff_separator(text: str) -> str:
    sample = "\n".join(text.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
    except csv.Error:
        counts = {sep: sample.count(sep) for sep in (",", "\t", ";", "|")}
        return max(counts, key=counts.get)


def read_delimited(content: bytes) -> pd.DataFrame:
    text, _ = decode_bytes(content)
    return pd.read_csv(io.StringIO(text), sep=_sniff_separator(text), low_memory=False)


def read_excel_best_sheet(source) -> pd.DataFrame:
    """Read the ledger from a workbook, joining sheets that share its layout.

    Exports often split one ledger across sheets by year, so stopping at the first match
    would silently lose data. A sheet literally named transactions always wins, and
    sheets with a different layout, such as dictionaries, are left out.
    """
    workbook = pd.ExcelFile(source)
    for name in workbook.sheet_names:
        if name.strip().lower() == "transactions":
            return pd.read_excel(workbook, sheet_name=name)
    previews = {name: pd.read_excel(workbook, sheet_name=name, nrows=5) for name in workbook.sheet_names}

    def score(name: str) -> int:
        return sum(canonical_field(column) in REQUIRED_FIELDS for column in previews[name].columns)

    best = max(workbook.sheet_names, key=score)
    layout = list(previews[best].columns)
    same = [name for name in workbook.sheet_names if list(previews[name].columns) == layout]
    frames = [pd.read_excel(workbook, sheet_name=name) for name in same]
    return pd.concat(frames, ignore_index=True)


def read_table(source: str | Path | bytes, name: str | None = None) -> pd.DataFrame:
    """Read a file path or uploaded bytes into a raw DataFrame."""
    if isinstance(source, bytes):
        filename, content = name or "upload.csv", source
    else:
        path = Path(source)
        filename, content = path.name, path.read_bytes()
    suffix = Path(filename).suffix.lower()
    if suffix in TABULAR_SUFFIXES:
        return read_delimited(content)
    if suffix in EXCEL_SUFFIXES:
        return read_excel_best_sheet(io.BytesIO(content))
    if suffix == ".parquet":
        return pd.read_parquet(io.BytesIO(content))
    if suffix == ".jsonl":
        return pd.read_json(io.BytesIO(content), lines=True)
    if suffix == ".json":
        payload = json.loads(decode_bytes(content)[0])
        if isinstance(payload, dict):
            payload = next((v for v in payload.values() if isinstance(v, list)), [payload])
        return pd.json_normalize(payload)
    raise ValueError(f"不支持的数据格式: {suffix}")


_NUMERIC_TOKEN = re.compile(r"[-+]?\d[\d.,]*(?:[eE][-+]?\d+)?")


def _parse_number_text(text: str) -> float:
    value = unicodedata.normalize("NFKC", text).replace("\u2212", "-").strip()
    match = _NUMERIC_TOKEN.search(value)
    if match is None:
        return np.nan
    token = match.group()
    # Accounting exports write negatives as (12.00) or 12.00-.
    negative = (value.startswith("(") and value.endswith(")")) or value.endswith("-")
    if "," in token and "." in token:
        # The right-most separator is the decimal mark: 1.299,50 versus 1,299.50.
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif "," in token:
        head, _, tail = token.rpartition(",")
        token = token.replace(",", "") if len(tail) == 3 and head else token.replace(",", ".")
    elif token.count(".") > 1:
        token = token.replace(".", "")
    try:
        number = float(token)
    except ValueError:
        return np.nan
    number = -abs(number) if negative else number
    return number / 100 if "%" in value else number


def parse_number(series: pd.Series) -> pd.Series:
    """Coerce money-like text such as ¥1,299.00, 1.299,50 or (12.00) to floats."""
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    text = series.astype("string").str.strip()
    # Plain numbers take the fast path, so only messy cells pay for the slower parser.
    parsed = pd.to_numeric(text, errors="coerce").astype("float64")
    messy = parsed.isna() & text.notna()
    if messy.any():
        unique = text[messy].drop_duplicates()
        lookup = {str(item): _parse_number_text(str(item)) for item in unique}
        parsed.loc[messy] = text[messy].map(lookup).astype("float64")
    return parsed


def parse_rate(series: pd.Series) -> pd.Series:
    """Read a discount as a fraction. A column written in whole percents (5, 10) is rescaled."""
    numeric = parse_number(series)
    valid = numeric.dropna()
    if not valid.empty and valid.abs().max() > 1 and valid.abs().max() <= 100:
        return numeric / 100
    return numeric


def _parse_numeric_dates(numeric: pd.Series) -> pd.Series:
    """Read the numeric forms exports use: Excel serials, 20250301, and Unix timestamps."""
    out = pd.Series(pd.NaT, index=numeric.index, dtype="datetime64[ns]")
    serial = numeric.between(20000, 80000)
    compact = numeric.between(19000101, 21001231)
    seconds = numeric.between(1e9, 4e9)
    milliseconds = numeric.between(1e12, 4e12)
    if serial.any():
        out.loc[serial] = pd.to_datetime(numeric[serial], unit="D", origin="1899-12-30")
    if compact.any():
        text = numeric[compact].astype("int64").astype("string")
        out.loc[compact] = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    if seconds.any():
        out.loc[seconds] = pd.to_datetime(numeric[seconds], unit="s")
    if milliseconds.any():
        out.loc[milliseconds] = pd.to_datetime(numeric[milliseconds], unit="ms")
    return out


def parse_datetime(series: pd.Series) -> pd.Series:
    """Parse ISO text, Chinese dates and Excel serial numbers into timestamps."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    if pd.api.types.is_numeric_dtype(series):
        return _parse_numeric_dates(pd.to_numeric(series, errors="coerce"))
    text = series.astype("string").str.strip()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        parsed = pd.to_datetime(text, errors="coerce")
    if isinstance(parsed.dtype, pd.DatetimeTZDtype):
        parsed = parsed.dt.tz_localize(None)
    unresolved = parsed.isna() & text.notna()
    if unresolved.any():
        localized = (
            text[unresolved]
            .str.replace("年", "-", regex=False)
            .str.replace("月", "-", regex=False)
            .str.replace("日", " ", regex=False)
            .str.replace("时", ":", regex=False)
            .str.replace("分", "", regex=False)
            .str.strip()
        )
        retry = pd.to_datetime(localized, errors="coerce", format="mixed", utc=True)
        parsed.loc[unresolved] = retry.dt.tz_localize(None)
    return parsed


@dataclass(frozen=True)
class MappingSuggestion:
    field: str
    column: str
    confidence: float
    reason: str


def _value_profile(series: pd.Series) -> dict[str, float]:
    sample = series.dropna().head(200)
    if sample.empty:
        return {"date": 0.0, "number": 0.0, "integer": 0.0, "negative": 0.0, "unique": 0.0}
    numeric = parse_number(sample)
    is_text = not pd.api.types.is_numeric_dtype(sample)
    dates = parse_datetime(sample.astype("string")) if is_text else pd.Series(dtype="datetime64[ns]")
    numbers = numeric.dropna()
    return {
        "date": float(dates.notna().mean()) if is_text else 0.0,
        "number": float(numeric.notna().mean()),
        "integer": float((numbers == numbers.round()).mean()) if not numbers.empty else 0.0,
        "negative": float((numbers < 0).mean()) if not numbers.empty else 0.0,
        "unique": float(sample.nunique() / max(len(sample), 1)),
    }


def suggest_mapping(frame: pd.DataFrame) -> dict[str, MappingSuggestion]:
    """Match source columns to canonical fields by header first, then by value shape."""
    suggestions: dict[str, MappingSuggestion] = {}
    used: set[str] = set()

    def take(field: str, column: str, confidence: float, reason: str) -> None:
        if field not in suggestions and column not in used:
            suggestions[field] = MappingSuggestion(field, column, confidence, reason)
            used.add(column)

    for column in frame.columns:
        field = canonical_field(column)
        if field:
            take(field, str(column), 1.0, "header")

    names = list(_ALIAS_INDEX)
    for column in frame.columns:
        if str(column) in used:
            continue
        key = normalize_header(column)
        if len(key) < 2:
            continue
        close = difflib.get_close_matches(key, names, n=1, cutoff=0.82)
        if close:
            ratio = difflib.SequenceMatcher(None, key, close[0]).ratio()
            take(_ALIAS_INDEX[close[0]], str(column), round(ratio * 0.9, 2), "similar name")

    remaining = [str(column) for column in frame.columns if str(column) not in used]
    profiles = {column: _value_profile(frame[column]) for column in remaining}
    if "invoice_date" not in suggestions:
        dated = [c for c in remaining if profiles[c]["date"] >= 0.9]
        if dated:
            take("invoice_date", dated[0], 0.7, "values look like dates")
    if "quantity" not in suggestions:
        counts = [
            c
            for c in remaining
            if profiles[c]["number"] >= 0.95 and profiles[c]["integer"] >= 0.98 and c not in used
        ]
        if counts:
            take("quantity", counts[0], 0.45, "whole numbers")
    return suggestions


def _stable_id(prefix: str, *columns: pd.Series) -> pd.Series:
    joined = columns[0].astype("string").fillna("")
    for column in columns[1:]:
        joined = joined + "|" + column.astype("string").fillna("")
    digest = joined.map(lambda text: hashlib.sha256(str(text).encode()).hexdigest()[:12].upper())
    return prefix + digest


def apply_mapping(
    frame: pd.DataFrame,
    mapping: dict[str, str],
    *,
    default_country: str | None = None,
    default_channel: str | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Rename mapped columns and derive absent required fields, noting each derivation."""
    out = pd.DataFrame(index=frame.index)
    notes: list[str] = []
    for field, column in mapping.items():
        if column in frame.columns:
            out[field] = frame[column]

    if "quantity" in out:
        out["quantity"] = parse_number(out["quantity"])
    else:
        out["quantity"] = 1
        notes.append("未提供数量，按每行 1 件处理。")
    if "unit_price" in out:
        out["unit_price"] = parse_number(out["unit_price"])
    elif "line_amount" in out:
        amount = parse_number(out["line_amount"])
        out["unit_price"] = (amount / out["quantity"].abs().replace(0, np.nan)).abs()
        notes.append("未提供单价，已由行金额 ÷ 数量推算。")
    if "invoice_date" in out:
        out["invoice_date"] = parse_datetime(out["invoice_date"])
    if "discount_amount_input" in out and "discount_rate" not in out and "unit_price" in out:
        gross = (out["unit_price"] * out["quantity"].abs()).replace(0, np.nan)
        out["discount_rate"] = parse_number(out["discount_amount_input"]).abs() / gross
        notes.append("未提供折扣率，已由折扣金额 ÷ 商品毛额推算。")
    if "discount_rate" in out:
        out["discount_rate"] = parse_rate(out["discount_rate"])
    for column in (
        "unit_cost",
        "shipping_cost",
        "payment_fee",
        "marketing_cost",
        "return_processing_cost",
    ):
        if column in out:
            out[column] = parse_number(out[column])
    out = out.drop(columns=[c for c in ("line_amount", "discount_amount_input") if c in out])

    if "stock_code" not in out and "description" in out:
        out["stock_code"] = out["description"].astype("string").str.strip().str.upper()
        notes.append("未提供商品编码，已用商品名称代替。")
    if "description" not in out and "stock_code" in out:
        out["description"] = out["stock_code"]
        notes.append("未提供商品名称，已用商品编码代替。")
    if "invoice_no" not in out and "invoice_date" in out:
        customer = out["customer_id"] if "customer_id" in out else pd.Series("", index=out.index)
        out["invoice_no"] = _stable_id("AUTO-", out["invoice_date"], customer)
        notes.append("未提供订单号，已按下单时间与客户生成。")
    if "country" not in out:
        out["country"] = default_country or "Unknown"
        notes.append(f"未提供国家，统一按 {default_country or 'Unknown'} 处理。")
    if "channel" not in out and default_channel:
        out["channel"] = default_channel
    if "order_status" in out:
        status = out["order_status"].astype("string").str.strip().str.casefold()
        cancelled = status.isin(CANCELLED_STATUSES).fillna(False).astype(bool)
        out = reverse_cancelled(out.drop(columns="order_status"), cancelled)
        if cancelled.any():
            notes.append(f"{int(cancelled.sum())} 行订单状态为取消或退款，已按销售加对冲记录入账。")
    return out, notes


def reverse_cancelled(frame: pd.DataFrame, cancelled: pd.Series) -> pd.DataFrame:
    """Keep a cancelled order's sale and add the line that undoes it.

    The ledger then nets to zero while the cancellation still counts toward the
    cancellation rate, the same shape a return takes in a sales ledger.
    """
    if not cancelled.any():
        return frame
    reversal = frame.loc[cancelled].copy()
    reversal["invoice_no"] = "C" + reversal["invoice_no"].astype(str)
    reversal["quantity"] = -pd.to_numeric(reversal["quantity"], errors="coerce").abs()
    return pd.concat([frame, reversal], ignore_index=True)


def missing_required(mapping: dict[str, str]) -> list[str]:
    """Report required fields that cannot be derived from the current mapping."""
    gaps: list[str] = []
    if "invoice_date" not in mapping:
        gaps.append("invoice_date")
    if "unit_price" not in mapping and "line_amount" not in mapping:
        gaps.append("unit_price")
    if "stock_code" not in mapping and "description" not in mapping:
        gaps.append("stock_code")
    return gaps


def auto_canonicalize(frame: pd.DataFrame, **defaults) -> tuple[pd.DataFrame, list[str]]:
    """Map a frame without user review, for the CLI and the watched folder."""
    suggested = suggest_mapping(frame)
    mapping = {field: item.column for field, item in suggested.items() if item.confidence >= 0.8}
    gaps = missing_required(mapping)
    if gaps:
        raise ValueError("无法识别必要字段: " + ", ".join(gaps))
    return apply_mapping(frame, mapping, **defaults)
