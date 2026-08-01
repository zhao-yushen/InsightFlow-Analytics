from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .config import is_read_only
from .diagnostics import generate_diagnostics
from .metrics import FilterSpec, inventory_status, target_status
from .warehouse import connect, query_df

ACTION_STATUSES = ("Open", "In Progress", "Blocked", "Done", "Dismissed")
EDITABLE_ACTION_COLUMNS = ("owner", "due_date", "status", "resolution_note")


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


def _detected_actions(db_path: str | Path, filters: FilterSpec) -> pd.DataFrame:
    issues, _ = generate_diagnostics(db_path, filters)
    rows: list[dict] = []
    owner_map = {
        "利润": "Finance",
        "收入": "Commercial",
        "取消": "Operations",
        "复购": "CRM",
        "库存": "Supply Chain",
        "数据": "Data Analytics",
    }
    today = date.today()
    for issue in issues:
        owner = next(
            (value for key, value in owner_map.items() if key in issue.title), "Business Analytics"
        )
        due_days = 3 if issue.severity in {"P0", "P1"} else 10
        fingerprint = _fingerprint("diagnostic_engine", issue.title, issue.evidence)
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
            issue = f"目标风险：{row['metric_id']}"
            evidence = (
                f"期间{row['target_period']}，实际值{row['actual_value']:.3f}，"
                f"目标值{row['target_value']:.3f}，完成度{row['attainment']:.1%}"
            )
            fingerprint = _fingerprint("target_monitor", issue, row["target_period"])
            rows.append(
                {
                    "action_id": f"TGT-{fingerprint[:10].upper()}",
                    "issue_fingerprint": fingerprint,
                    "severity": "P1" if row["status"] == "Off Track" else "P2",
                    "issue": issue,
                    "evidence": evidence,
                    "recommended_action": "复核目标缺口并制定当期纠偏方案",
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
            issue = f"补货风险：{row['stock_code']}"
            evidence = (
                f"可售{row['days_of_supply']:.1f}天，供应提前期{row['supplier_lead_days']:.0f}天"
            )
            fingerprint = _fingerprint("inventory_monitor", row["stock_code"])
            rows.append(
                {
                    "action_id": f"INV-{fingerprint[:10].upper()}",
                    "issue_fingerprint": fingerprint,
                    "severity": "P1",
                    "issue": issue,
                    "evidence": evidence,
                    "recommended_action": "确认在途采购并计算安全库存缺口",
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
) -> pd.DataFrame:
    """Synchronize current diagnostic findings while preserving human workflow state."""
    detected = _detected_actions(db_path, filters)
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
    where = "" if include_inactive else "WHERE is_active=1 OR status NOT IN ('Done','Dismissed')"
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
            resolved_at = now if status in {"Done", "Dismissed"} else None
            cursor = conn.execute(
                """
                UPDATE action_register
                SET owner=?, due_date=?, status=?, resolution_note=?, resolved_at=?
                WHERE action_id=?
                """,
                (
                    str(row.get("owner", "Business Analytics")).strip(),
                    due_date,
                    status,
                    str(row.get("resolution_note", "") or "").strip(),
                    resolved_at,
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
