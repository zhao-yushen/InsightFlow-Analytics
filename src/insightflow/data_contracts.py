from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


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


def _issue(severity: str, rule_id: str, column: str, failed_rows: int, message: str) -> ContractIssue:
    return ContractIssue(severity, rule_id, column, int(failed_rows), message)


def validate_contract(df: pd.DataFrame, contract: dict[str, Any]) -> pd.DataFrame:
    issues: list[ContractIssue] = []
    required = contract.get("required_columns", [])
    missing = [column for column in required if column not in df.columns]
    for column in missing:
        issues.append(_issue("P0", "required_column", column, len(df), f"缺少必要字段 {column}"))

    for column, rule in contract.get("rules", {}).items():
        if column not in df.columns:
            continue
        series = df[column]
        if rule.get("nullable") is False:
            count = int(series.isna().sum())
            if count:
                issues.append(_issue("P1", "not_null", column, count, f"{column}存在空值"))
        if rule.get("non_zero"):
            numeric = pd.to_numeric(series, errors="coerce")
            count = int(numeric.eq(0).sum())
            if count:
                issues.append(_issue("P1", "non_zero", column, count, f"{column}存在零值"))
        if "min" in rule or "min_exclusive" in rule or "max" in rule:
            numeric = pd.to_numeric(series, errors="coerce")
            if "min" in rule:
                count = int(numeric.lt(rule["min"]).sum())
                if count:
                    issues.append(_issue("P1", "min_value", column, count, f"{column}低于最小值{rule['min']}"))
            if "min_exclusive" in rule:
                count = int(numeric.le(rule["min_exclusive"]).sum())
                if count:
                    issues.append(
                        _issue("P1", "min_exclusive", column, count, f"{column}不大于{rule['min_exclusive']}")
                    )
            if "max" in rule:
                count = int(numeric.gt(rule["max"]).sum())
                if count:
                    issues.append(_issue("P1", "max_value", column, count, f"{column}高于最大值{rule['max']}"))
        if rule.get("type") == "datetime":
            parsed = pd.to_datetime(series, errors="coerce")
            count = int(parsed.isna().sum())
            if count:
                issues.append(_issue("P1", "datetime_type", column, count, f"{column}无法解析为日期"))
            if rule.get("not_future"):
                today = pd.Timestamp.now(tz=None).normalize()
                count = int(parsed.gt(today).sum())
                if count:
                    issues.append(_issue("P1", "not_future", column, count, f"{column}包含未来日期"))

    for column, allowed in contract.get("allowed_values", {}).items():
        if column not in df.columns:
            continue
        bad = ~df[column].fillna("Unknown").astype(str).isin(allowed)
        count = int(bad.sum())
        if count:
            issues.append(_issue("P2", "allowed_values", column, count, f"{column}包含未登记类别"))

    key = contract.get("primary_key", [])
    if key and all(column in df.columns for column in key):
        count = int(df.duplicated(key, keep=False).sum())
        if count:
            issues.append(_issue("P1", "primary_key_unique", ",".join(key), count, "业务主键存在重复"))

    if not issues:
        issues.append(_issue("PASS", "contract_pass", "*", 0, "数据通过全部契约检查"))
    return pd.DataFrame([issue.__dict__ for issue in issues])


def contract_score(issues: pd.DataFrame) -> float:
    if issues.empty or set(issues["severity"]) == {"PASS"}:
        return 100.0
    penalty = {"P0": 35.0, "P1": 12.0, "P2": 4.0, "P3": 1.0}
    total = sum(penalty.get(str(row.severity), 0.0) for row in issues.itertuples())
    return max(0.0, 100.0 - total)

BLOCKING_SEVERITIES = frozenset({"P0", "P1"})

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
        f"{row.column}/{row.rule_id}: {int(row.failed_rows)} rows"
        for row in blocking.itertuples()
    )
    return f"数据契约阻止导入（P0/P1）：{details}"

