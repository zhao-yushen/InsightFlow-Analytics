from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .config import is_read_only
from .currency import money, warehouse_currency
from .diagnostics import TARGET_LABELS, _chooser, generate_diagnostics
from .metrics import FilterSpec, inventory_status, target_status
from .warehouse import connect, query_df

ACTION_STATUSES = ("Open", "In Progress", "Blocked", "Done", "Dismissed")
EDITABLE_ACTION_COLUMNS = ("owner", "due_date", "status", "resolution_note")
ISSUE_OWNERS = {
    "revenue_drop": "Commercial",
    "revenue_growth": "Commercial",
    "concentration": "Commercial",
    "profit_pressure": "Finance",
    "margin_floor": "Finance",
    "target_gap": "Finance",
    "returns_rising": "Operations",
    "repeat_low": "CRM",
    "reorder_risk": "Supply Chain",
    "quality_low": "Data Analytics",
}


def _fingerprint(*parts: object) -> str:
    normalized = "|".join(str(part).strip().lower() for part in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def ensure_action_table(db_path: str | Path) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS action_register (
                action_id TEXT PRIMARY KEY,
                issue_fingerprint TEXT NOT NULL UNIQUE,
                severity TEXT NOT NULL,
                issue TEXT NOT NULL,
                evidence TEXT NOT NULL,
                recommended_action TEXT NOT NULL,
                owner TEXT NOT NULL,
                due_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Open',
                confidence REAL NOT NULL,
                source TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                resolved_at TEXT,
                resolution_note TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_action_status ON action_register(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_action_active ON action_register(is_active)")


def _scope_key(filters: FilterSpec) -> tuple[tuple[str, ...], ...]:
    """Identify an issue's business scope; the date window and live figures are not part of it."""
    return tuple(
        tuple(sorted(values))
        for values in (filters.regions, filters.countries, filters.categories, filters.channels)
    )


def _detected_actions(
    db_path: str | Path, filters: FilterSpec, language: str = "zh-CN"
) -> pd.DataFrame:
    say = _chooser(language)
    code = warehouse_currency(db_path)
    issues, _ = generate_diagnostics(db_path, filters, language=language)
    scope = _scope_key(filters)
    rows: list[dict] = []
    today = date.today()
    for issue in issues:
        owner = ISSUE_OWNERS.get(issue.code, "Business Analytics")
        due_days = 3 if issue.severity in {"P0", "P1"} else 10
        # The code stays out of the display text and live numbers stay out of the identity:
        # the same problem seen over another period or in another language updates one action.
        fingerprint = _fingerprint("diagnostic_engine", issue.code, scope)
        rows.append(
            {
                "action_id": f"ACT-{fingerprint[:10].upper()}",
                "issue_fingerprint": fingerprint,
                "severity": issue.severity,
                "issue": issue.title,
                "evidence": issue.evidence,
                "recommended_action": issue.recommendation,
                "owner": owner,
                "due_date": (today + timedelta(days=due_days)).isoformat(),
                "status": "Open",
                "confidence": issue.confidence,
                "source": "diagnostic_engine",
                "resolution_note": "",
            }
        )

    target_month = str(pd.Timestamp(filters.end_date).to_period("M")) if filters.end_date else None
    targets = target_status(db_path, target_month)
    if not targets.empty:
        for _, row in targets.loc[targets["status"] != "On Track"].iterrows():
            metric_id = str(row["metric_id"])
            name = say(*TARGET_LABELS.get(metric_id, (metric_id, metric_id)))
            rate = metric_id in {"gross_margin", "cancellation_rate"}
            actual = (
                f"{row['actual_value']:.1%}" if rate else money(float(row["actual_value"]), code)
            )
            goal = (
                f"{row['target_value']:.1%}" if rate else money(float(row["target_value"]), code)
            )
            fingerprint = _fingerprint("target_monitor", metric_id, row["target_period"], scope)
            rows.append(
                {
                    "action_id": f"TGT-{fingerprint[:10].upper()}",
                    "issue_fingerprint": fingerprint,
                    "severity": "P1" if row["status"] == "Off Track" else "P2",
                    "issue": say(f"目标风险：{name}", f"Target at risk: {name}"),
                    "evidence": say(
                        f"{row['target_period']} 实际 {actual}，目标 {goal}，"
                        f"完成度 {row['attainment']:.1%}",
                        f"{row['target_period']}: {actual} against {goal}, "
                        f"{row['attainment']:.1%} attained",
                    ),
                    "recommended_action": say(
                        "复核目标缺口并制定当期纠偏方案",
                        "Review the gap and agree a correction for this period",
                    ),
                    "owner": row["owner"],
                    "due_date": (today + timedelta(days=5)).isoformat(),
                    "status": "Open",
                    "confidence": 0.95,
                    "source": "target_monitor",
                    "resolution_note": "",
                }
            )

    reorder = inventory_status(db_path, "Reorder")
    if not reorder.empty:
        for _, row in reorder.head(5).iterrows():
            fingerprint = _fingerprint("inventory_monitor", row["stock_code"])
            rows.append(
                {
                    "action_id": f"INV-{fingerprint[:10].upper()}",
                    "issue_fingerprint": fingerprint,
                    "severity": "P1",
                    "issue": say(
                        f"补货风险：{row['stock_code']}", f"Reorder risk: {row['stock_code']}"
                    ),
                    "evidence": say(
                        f"可售 {row['days_of_supply']:.1f} 天，"
                        f"供应提前期 {row['supplier_lead_days']:.0f} 天",
                        f"{row['days_of_supply']:.1f} days of cover against a "
                        f"{row['supplier_lead_days']:.0f}-day lead time",
                    ),
                    "recommended_action": say(
                        "确认在途采购并计算安全库存缺口",
                        "Confirm purchase orders in transit and size the safety-stock gap",
                    ),
                    "owner": "Supply Chain",
                    "due_date": (today + timedelta(days=3)).isoformat(),
                    "status": "Open",
                    "confidence": 0.90,
                    "source": "inventory_monitor",
                    "resolution_note": "",
                }
            )
    return pd.DataFrame(rows)


def sync_action_register(
    db_path: str | Path,
    filters: FilterSpec,
    *,
    persist: bool | None = None,
    include_inactive: bool = False,
    language: str = "zh-CN",
) -> pd.DataFrame:
    """Synchronize current diagnostic findings while preserving human workflow state."""
    detected = _detected_actions(db_path, filters, language)
    persist = (not is_read_only()) if persist is None else persist
    if not persist:
        if detected.empty:
            return detected
        detected = detected.assign(is_active=1, first_seen_at="", last_seen_at="", resolved_at=None)
        return _sort_actions(detected)

    ensure_action_table(db_path)
    now = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as conn:
        conn.execute("UPDATE action_register SET is_active=0")
        for row in detected.to_dict("records"):
            existing = conn.execute(
                "SELECT action_id FROM action_register WHERE issue_fingerprint=?",
                (row["issue_fingerprint"],),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE action_register
                    SET severity=?, issue=?, evidence=?, recommended_action=?, confidence=?,
                        source=?, is_active=1, last_seen_at=?
                    WHERE issue_fingerprint=?
                    """,
                    (
                        row["severity"],
                        row["issue"],
                        row["evidence"],
                        row["recommended_action"],
                        float(row["confidence"]),
                        row["source"],
                        now,
                        row["issue_fingerprint"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO action_register(
                        action_id, issue_fingerprint, severity, issue, evidence,
                        recommended_action, owner, due_date, status, confidence,
                        source, is_active, first_seen_at, last_seen_at, resolution_note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        row["action_id"],
                        row["issue_fingerprint"],
                        row["severity"],
                        row["issue"],
                        row["evidence"],
                        row["recommended_action"],
                        row["owner"],
                        row["due_date"],
                        row["status"],
                        float(row["confidence"]),
                        row["source"],
                        now,
                        now,
                        row["resolution_note"],
                    ),
                )
    where = "" if include_inactive else "WHERE is_active=1 OR status IN ('In Progress','Blocked')"
    return _sort_actions(query_df(db_path, f"SELECT * FROM action_register {where}"))


def prepare_action_editor_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert persisted SQLite text fields to Streamlit-editable physical dtypes."""
    prepared = frame.copy()
    if "due_date" in prepared:
        prepared["due_date"] = pd.to_datetime(prepared["due_date"], errors="coerce")
    for column in ("first_seen_at", "last_seen_at", "resolved_at"):
        if column in prepared:
            prepared[column] = pd.to_datetime(prepared[column], errors="coerce", utc=True)
    if "confidence" in prepared:
        prepared["confidence"] = pd.to_numeric(prepared["confidence"], errors="coerce").fillna(0.0)
    if "is_active" in prepared:
        prepared["is_active"] = prepared["is_active"].fillna(0).astype(bool)
    return prepared


def update_action_register(db_path: str | Path, edited: pd.DataFrame) -> int:
    if is_read_only():
        raise PermissionError("当前为只读模式，不能更新行动状态。")
    if edited.empty:
        return 0
    ensure_action_table(db_path)
    updated = 0
    now = datetime.now(timezone.utc).isoformat()
    with connect(db_path) as conn:
        for row in edited.to_dict("records"):
            action_id = str(row.get("action_id", "")).strip()
            if not action_id:
                continue
            status = str(row.get("status", "Open"))
            if status not in ACTION_STATUSES:
                raise ValueError(f"未知行动状态：{status}")
            due_date = pd.Timestamp(row.get("due_date")).date().isoformat()
            closed = status in {"Done", "Dismissed"}
            cursor = conn.execute(
                """
                UPDATE action_register
                SET owner=?, due_date=?, status=?, resolution_note=?,
                    resolved_at=CASE WHEN ? THEN COALESCE(resolved_at, ?) END
                WHERE action_id=?
                """,
                (
                    str(row.get("owner", "Business Analytics")).strip(),
                    due_date,
                    status,
                    str(row.get("resolution_note", "") or "").strip(),
                    closed,
                    now,
                    action_id,
                ),
            )
            updated += cursor.rowcount
    return updated


def build_action_register(db_path: str | Path, filters: FilterSpec) -> pd.DataFrame:
    return sync_action_register(db_path, filters)


def _sort_actions(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    priority = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    status_order = {"Open": 0, "In Progress": 1, "Blocked": 2, "Done": 3, "Dismissed": 4}
    out = frame.copy()
    out["priority_order"] = out["severity"].map(priority).fillna(9)
    out["status_order"] = out.get("status", "Open").map(status_order).fillna(9)
    return out.sort_values(["status_order", "priority_order", "due_date", "action_id"]).drop(
        columns=["priority_order", "status_order"]
    )
