from __future__ import annotations

from pathlib import Path

import pandas as pd

from .warehouse import query_df, table_exists

STATUS_LABELS = {
    "Verified": "真实/已核验",
    "Estimated": "估算",
    "Simulated": "模拟",
    "Mixed": "混合",
}
STATUS_ICONS = {"Verified": "✅", "Estimated": "🧮", "Simulated": "🧪", "Mixed": "🔀"}


def dataset_profile(db_path: str | Path) -> dict[str, str | float]:
    if not table_exists(db_path, "data_profiles"):
        return {
            "profile_id": "legacy",
            "profile_name": "Legacy dataset",
            "data_mode": "Mixed",
            "transaction_status": "Verified",
            "economic_status": "Estimated",
            "inventory_status": "Simulated",
            "source_note": "旧仓库未记录完整来源标签",
        }
    frame = query_df(db_path, "SELECT * FROM data_profiles ORDER BY created_at DESC LIMIT 1")
    return frame.iloc[0].to_dict() if not frame.empty else {}


def metric_trust(db_path: str | Path, metric_id: str) -> dict[str, str | float]:
    if not table_exists(db_path, "metric_catalog"):
        return {"data_status": "Mixed", "confidence": 0.5, "source_note": "未登记"}
    frame = query_df(
        db_path,
        "SELECT data_status, confidence, source_note FROM metric_catalog WHERE metric_id=?",
        (metric_id,),
    )
    if frame.empty:
        return {"data_status": "Mixed", "confidence": 0.5, "source_note": "未登记"}
    return frame.iloc[0].to_dict()


def trust_label(status: str) -> str:
    return f"{STATUS_ICONS.get(status, 'ℹ️')} {STATUS_LABELS.get(status, status)}"


def metric_trust_table(db_path: str | Path) -> pd.DataFrame:
    if not table_exists(db_path, "metric_catalog"):
        return pd.DataFrame()
    return query_df(
        db_path,
        """
        SELECT metric_id, metric_name, definition, unit, data_status, confidence, source_note, owner
        FROM metric_catalog ORDER BY metric_id
        """,
    )
