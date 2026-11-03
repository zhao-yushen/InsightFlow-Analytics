from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

BLOCKING_SEVERITIES = frozenset({"P0", "P1"})
REJECTION_LABELS = {
    "non_merchandise": ("运费、手续费、调整等非商品行", "Postage, fees and adjustments"),
    "invoice_no/not_null": ("缺少订单号", "No order number"),
    "stock_code/not_null": ("缺少商品编码", "No product code"),
    "quantity/not_null": ("缺少数量", "No quantity"),
    "quantity/non_zero": ("数量为零", "Zero quantity"),
    "invoice_date/not_null": ("缺少或无法识别日期", "Missing or unreadable date"),
    "invoice_date/not_future": ("日期在未来", "Date in the future"),
    "unit_price/not_null": ("缺少单价", "No unit price"),
    "unit_price/min_exclusive": ("单价为零或负数", "Zero or negative price"),
    "discount_rate/min_value": ("折扣为负", "Negative discount"),
    "discount_rate/max_value": ("折扣超过 90%", "Discount above 90%"),
    "unit_cost/min_exclusive": ("成本为零或负数", "Zero or negative cost"),
    "shipping_cost/min_value": ("运费为负", "Negative shipping cost"),
    "payment_fee/min_value": ("手续费为负", "Negative payment fee"),
    "marketing_cost/min_value": ("营销费为负", "Negative marketing cost"),
    "return_processing_cost/min_value": ("退货费为负", "Negative return cost"),
    "primary_key_unique": ("重复的订单行", "Duplicate order line"),
}


@dataclass(frozen=True)
class ContractIssue:
    severity: str
    rule_id: str
    column: str
    failed_rows: int
    message: str


def load_contract(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _rule_failures(df: pd.DataFrame, contract: dict[str, Any]) -> list[tuple[ContractIssue, pd.Series]]:
    """Run every row-level rule once, so counts and rejected rows can never disagree."""
    failures: list[tuple[ContractIssue, pd.Series]] = []

    def record(mask: pd.Series, severity: str, rule_id: str, column: str, message: str) -> None:
        count = int(mask.sum())
        if count:
            failures.append((ContractIssue(severity, rule_id, column, count, message), mask))

    for column, rule in contract.get("rules", {}).items():
        if column not in df.columns:
            continue
        series = df[column]
        severity = rule.get("severity", "P1")
        if rule.get("nullable") is False:
            record(series.isna(), severity, "not_null", column, f"{column}存在空值")
        if rule.get("non_zero"):
            numeric = pd.to_numeric(series, errors="coerce")
            record(numeric.eq(0), severity, "non_zero", column, f"{column}存在零值")
        if "min" in rule or "min_exclusive" in rule or "max" in rule:
            numeric = pd.to_numeric(series, errors="coerce")
            if "min" in rule:
                message = f"{column}低于最小值{rule['min']}"
                record(numeric.lt(rule["min"]), severity, "min_value", column, message)
            if "min_exclusive" in rule:
                message = f"{column}不大于{rule['min_exclusive']}"
                record(numeric.le(rule["min_exclusive"]), severity, "min_exclusive", column, message)
            if "max" in rule:
                message = f"{column}高于最大值{rule['max']}"
                record(numeric.gt(rule["max"]), severity, "max_value", column, message)
        if rule.get("type") == "datetime":
            parsed = pd.to_datetime(series, errors="coerce")
            unreadable = parsed.isna() & series.notna()
            record(unreadable, severity, "datetime_type", column, f"{column}无法解析为日期")
            if rule.get("not_future"):
                today = pd.Timestamp.now(tz=None).normalize()
                record(parsed.gt(today), severity, "not_future", column, f"{column}包含未来日期")

    key = contract.get("primary_key", [])
    if key and all(column in df.columns for column in key):
        record(
            df.duplicated(key, keep="first"),
            "P1",
            "primary_key_unique",
            ",".join(key),
            "业务主键存在重复",
        )
    return failures


def validate_contract(df: pd.DataFrame, contract: dict[str, Any]) -> pd.DataFrame:
    issues: list[ContractIssue] = []
    required = contract.get("required_columns", [])
    for column in required:
        if column not in df.columns:
            issues.append(ContractIssue("P0", "required_column", column, len(df), f"缺少必要字段 {column}"))

    issues.extend(issue for issue, _ in _rule_failures(df, contract))

    for column, allowed in contract.get("allowed_values", {}).items():
        if column not in df.columns:
            continue
        count = int((~df[column].fillna("Unknown").astype(str).isin(allowed)).sum())
        if count:
            issues.append(ContractIssue("P2", "allowed_values", column, count, f"{column}包含未登记类别"))

    if not issues:
        issues.append(ContractIssue("PASS", "contract_pass", "*", 0, "数据通过全部契约检查"))
    return pd.DataFrame([issue.__dict__ for issue in issues])


def row_rejections(df: pd.DataFrame, contract: dict[str, Any]) -> pd.Series:
    """Name the first P0/P1 rule each row breaks, or leave it empty when the row is sound."""
    reasons = pd.Series(pd.NA, index=df.index, dtype="string")
    for issue, mask in _rule_failures(df, contract):
        if issue.severity in BLOCKING_SEVERITIES:
            label = issue.rule_id if issue.rule_id == "primary_key_unique" else f"{issue.column}/{issue.rule_id}"
            reasons = reasons.mask(reasons.isna() & mask, label)
    return reasons


def contract_score(issues: pd.DataFrame) -> float:
    if issues.empty or set(issues["severity"]) == {"PASS"}:
        return 100.0
    penalty = {"P0": 35.0, "P1": 12.0, "P2": 4.0, "P3": 1.0}
    total = sum(penalty.get(str(row.severity), 0.0) for row in issues.itertuples())
    return max(0.0, 100.0 - total)


def blocking_contract_issues(issues: pd.DataFrame) -> pd.DataFrame:
    """Return issues that must be corrected before an operational import."""
    if issues.empty or "severity" not in issues:
        return issues.iloc[0:0].copy()
    return issues.loc[issues["severity"].isin(BLOCKING_SEVERITIES)].copy()


def contract_block_message(issues: pd.DataFrame) -> str:
    blocking = blocking_contract_issues(issues)
    if blocking.empty:
        return ""
    details = "; ".join(
        f"{row.column}/{row.rule_id}: {int(row.failed_rows)} rows" for row in blocking.itertuples()
    )
    return f"数据契约阻止导入（P0/P1）：{details}"
