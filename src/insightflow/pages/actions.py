from __future__ import annotations

import pandas as pd
import streamlit as st

from insightflow.action_center import (
    ACTION_STATUSES,
    prepare_action_editor_frame,
    sync_action_register,
    update_action_register,
)
from insightflow.config import DEFAULT_DB_PATH, is_read_only
from insightflow.i18n import t
from insightflow.ui import page_header, sidebar_filters


def _status_label(value: str) -> str:
    return t(f"action_status.{value}", default=value)


def render() -> None:
    page_header(
        t("page.actions.title"),
        t("page.actions.desc"),
        eyebrow="ACTION MANAGEMENT",
    )
    filters = sidebar_filters(DEFAULT_DB_PATH)
    read_only = is_read_only()
    actions = sync_action_register(
        DEFAULT_DB_PATH, filters, persist=not read_only, include_inactive=True
    )
    if actions.empty:
        st.success(t("actions.none"))
        return

    active = actions.loc[actions.get("is_active", 1).astype(bool)]
    cols = st.columns(4)
    cols[0].metric(t("actions.current"), len(active))
    cols[1].metric("P0/P1", int(active["severity"].isin(["P0", "P1"]).sum()))
    cols[2].metric(
        t("actions.in_progress"),
        int(active["status"].isin(["Open", "In Progress", "Blocked"]).sum()),
    )
    cols[3].metric(t("actions.completed"), int((actions["status"] == "Done").sum()))

    if read_only:
        st.info(t("actions.read_only"))

    left, right = st.columns(2)
    with left:
        severity = st.multiselect(
            t("actions.severity"),
            ["P0", "P1", "P2", "P3"],
            default=["P0", "P1", "P2", "P3"],
        )
    with right:
        statuses = st.multiselect(
            t("actions.status"),
            list(ACTION_STATUSES),
            default=["Open", "In Progress", "Blocked"],
            format_func=_status_label,
        )
    with st.expander(t("actions.status") + " · ?", expanded=False):
        st.caption(t("actions.workflow_help"))

    shown = actions[actions["severity"].isin(severity) & actions["status"].isin(statuses)].copy()
    if shown.empty:
        st.info(t("actions.none"))
        return

    visible_columns = [
        "action_id",
        "severity",
        "issue",
        "evidence",
        "recommended_action",
        "owner",
        "due_date",
        "status",
        "resolution_note",
        "confidence",
        "source",
        "is_active",
        "first_seen_at",
        "last_seen_at",
    ]
    visible_columns = [column for column in visible_columns if column in shown.columns]
    editor_frame = prepare_action_editor_frame(shown[visible_columns])
    status_to_display = {status: _status_label(status) for status in ACTION_STATUSES}
    display_to_status = {label: status for status, label in status_to_display.items()}
    if "status" in editor_frame:
        editor_frame["status"] = (
            editor_frame["status"].map(status_to_display).fillna(editor_frame["status"])
        )
    edited = st.data_editor(
        editor_frame,
        use_container_width=True,
        hide_index=True,
        disabled=True
        if read_only
        else [
            column
            for column in visible_columns
            if column not in {"owner", "due_date", "status", "resolution_note"}
        ],
        column_config={
            "action_id": st.column_config.TextColumn("Action ID"),
            "severity": st.column_config.TextColumn(t("actions.severity")),
            "issue": st.column_config.TextColumn(t("actions.issue"), width="large"),
            "evidence": st.column_config.TextColumn(t("actions.evidence"), width="large"),
            "recommended_action": st.column_config.TextColumn(
                t("actions.recommendation"), width="large"
            ),
            "owner": st.column_config.TextColumn(t("actions.owner")),
            "status": st.column_config.SelectboxColumn(
                t("actions.status"),
                options=list(status_to_display.values()),
                required=True,
            ),
            "due_date": st.column_config.DateColumn(
                t("actions.due_date"),
                format="YYYY-MM-DD",
                required=True,
            ),
            "resolution_note": st.column_config.TextColumn(t("actions.note"), width="large"),
            "confidence": st.column_config.ProgressColumn(
                t("actions.confidence"), min_value=0.0, max_value=1.0, format="%.0%%"
            ),
            "source": st.column_config.TextColumn(t("actions.source")),
            "is_active": st.column_config.CheckboxColumn(t("actions.active")),
            "first_seen_at": st.column_config.DatetimeColumn(
                t("actions.first_seen"), format="YYYY-MM-DD HH:mm"
            ),
            "last_seen_at": st.column_config.DatetimeColumn(
                t("actions.last_seen"), format="YYYY-MM-DD HH:mm"
            ),
        },
        key="action_register_editor_v043",
    )

    save_col, download_col = st.columns([1, 2])
    with save_col:
        if st.button(t("actions.save"), type="primary", disabled=read_only):
            save_frame = pd.DataFrame(edited).copy()
            if "status" in save_frame:
                save_frame["status"] = (
                    save_frame["status"].map(display_to_status).fillna(save_frame["status"])
                )
            count = update_action_register(DEFAULT_DB_PATH, save_frame)
            st.success(t("actions.saved", count=count))
            st.rerun()
    with download_col:
        export = pd.DataFrame(edited).copy()
        if "due_date" in export:
            export["due_date"] = pd.to_datetime(export["due_date"], errors="coerce").dt.strftime(
                "%Y-%m-%d"
            )
        st.download_button(
            t("actions.download"),
            data=export.to_csv(index=False).encode("utf-8-sig"),
            file_name="insightflow_action_register.csv",
            mime="text/csv",
        )
    st.caption(t("actions.caption"))
