from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from insightflow.config import DEFAULT_DB_PATH, INCOMING_DIR, is_read_only
from insightflow.data_contracts import blocking_contract_issues
from insightflow.etl import REQUIRED_COLUMNS, clean_transactions, read_excel_transactions
from insightflow.i18n import t
from insightflow.metrics import date_bounds, filter_option_counts
from insightflow.ui import page_header, sidebar_filters
from insightflow.warehouse import build_warehouse, database_version, query_df
from insightflow.watcher import scan_once


def _read_uploaded_file(name: str, content: bytes) -> pd.DataFrame:
    suffix = Path(name).suffix.lower()
    stream = BytesIO(content)
    if suffix == ".csv":
        return pd.read_csv(stream)
    if suffix in {".xlsx", ".xls"}:
        return read_excel_transactions(stream)
    if suffix == ".parquet":
        return pd.read_parquet(stream)
    raise ValueError(t("data.unsupported", suffix=suffix))


@st.cache_data(show_spinner=False, max_entries=8)
def _prepare_upload(name: str, content: bytes):
    frame = _read_uploaded_file(name, content)
    result = clean_transactions(
        frame,
        source_profile="web_incremental_import",
        transaction_status="Verified",
    )
    return frame, result


def _template_csv() -> bytes:
    sample = pd.DataFrame(
        [
            {
                "invoice_no": "INV-20260801-0001",
                "stock_code": "SKU-0001",
                "description": "Example product",
                "category": "Electronics",
                "quantity": 2,
                "invoice_date": "2026-08-01 10:30:00",
                "unit_price": 29.90,
                "customer_id": "CUST-0001",
                "country": "China",
                "market_region": "Greater China",
                "channel": "Mobile App",
                "unit_cost": 15.20,
                "discount_rate": 0.05,
            }
        ]
    )
    return sample.to_csv(index=False).encode("utf-8-sig")


def render() -> None:
    page_header(
        t("page.data_hub.title"),
        t("page.data_hub.desc"),
        eyebrow="DATA OPERATIONS",
    )
    sidebar_filters(DEFAULT_DB_PATH)
    read_only = is_read_only()

    total = query_df(
        DEFAULT_DB_PATH,
        "SELECT COUNT(*) AS rows, MIN(date) AS min_date, MAX(date) AS max_date FROM fact_transactions",
    ).iloc[0]
    last_run = query_df(
        DEFAULT_DB_PATH,
        "SELECT run_at, source_name, load_mode, inserted_rows, skipped_rows FROM etl_runs ORDER BY run_at DESC LIMIT 1",
    )
    counts = filter_option_counts(DEFAULT_DB_PATH)

    st.subheader(t("data.current_warehouse"))
    cols = st.columns(4)
    cols[0].metric(t("data.rows"), f"{int(total['rows']):,}")
    cols[1].metric(t("data.date_range"), f"{total['min_date']} → {total['max_date']}")
    cols[2].metric(
        t("data.last_run"),
        "—" if last_run.empty else str(last_run.iloc[0]["run_at"])[:19].replace("T", " "),
    )
    cols[3].metric(
        t("data.dimensions"),
        f"{len(counts['regions'])} / {len(counts['countries'])} / {len(counts['categories'])} / {len(counts['channels'])}",
        help="Market region / Country or region / Category / Channel",
    )

    dim_rows = []
    for dimension, values in counts.items():
        dim_rows.append(
            {
                "dimension": dimension,
                t("data.dimension_count"): len(values),
                "top_values": ", ".join(list(values)[:8]),
            }
        )
    st.dataframe(pd.DataFrame(dim_rows), use_container_width=True, hide_index=True)

    st.subheader(t("data.upload"))
    st.caption(t("data.upload_help"))
    uploaded = st.file_uploader(
        t("data.upload"),
        type=["csv", "xlsx", "xls", "parquet"],
        label_visibility="collapsed",
    )
    st.download_button(
        t("data.template"),
        _template_csv(),
        file_name="insightflow_input_template.csv",
        mime="text/csv",
    )

    if uploaded is None:
        st.info(t("data.no_file"))
    else:
        try:
            raw, result = _prepare_upload(uploaded.name, uploaded.getvalue())
        except Exception as exc:
            st.error(t("data.failed", error=str(exc)))
        else:
            missing = [
                column for column in REQUIRED_COLUMNS if column not in result.curated.columns
            ]
            if missing:
                st.error(t("data.missing", columns=", ".join(missing)))
            score = float(result.quality_dimensions["score_100"].mean())
            failures = int((result.contract_issues["severity"] != "PASS").sum())
            blocking = blocking_contract_issues(result.contract_issues)
            preview_cols = st.columns(4)
            preview_cols[0].metric(t("data.file_rows"), f"{len(raw):,}")
            preview_cols[1].metric(t("data.cleaned_rows"), f"{len(result.curated):,}")
            preview_cols[2].metric(t("data.quality_score"), f"{score:.1f}/100")
            preview_cols[3].metric(t("data.contract_issues"), f"{failures:,}")
            st.dataframe(result.curated.head(100), use_container_width=True, hide_index=True)
            if failures:
                st.dataframe(result.contract_issues, use_container_width=True, hide_index=True)
                if not blocking.empty:
                    st.error(
                        "存在P0/P1阻断问题，必须先修复后才能导入。P2为未登记类别警告，可继续导入。"
                    )
                else:
                    st.warning("仅存在P2提示：数据可以导入，但请复核未登记类别。")
            else:
                st.success(t("data.valid"))
            import_mode_label = st.radio(
                t("data.import_mode"),
                [t("data.append"), t("data.replace")],
                horizontal=True,
                key="data_hub_import_mode",
            )
            load_mode = "replace" if import_mode_label == t("data.replace") else "append"
            if load_mode == "replace":
                st.warning(t("data.replace_warning"))
            if read_only:
                st.info(t("data.read_only"))
            if st.button(
                t("data.import"),
                type="primary",
                disabled=read_only or bool(missing) or not blocking.empty,
            ):
                stats = build_warehouse(
                    result,
                    DEFAULT_DB_PATH,
                    load_mode=load_mode,
                    source_name=uploaded.name,
                )
                st.cache_data.clear()
                # Reset the date window so newly imported periods become visible.
                st.session_state.pop("global_analysis_period", None)
                if load_mode == "replace":
                    for key in (
                        "filter_regions",
                        "filter_countries",
                        "filter_categories",
                        "filter_channels",
                    ):
                        st.session_state.pop(key, None)
                st.success(
                    t(
                        "data.imported",
                        inserted=stats["inserted_rows"],
                        skipped=stats["skipped_rows"],
                    )
                )
                st.rerun()

    st.subheader(t("data.live"))
    st.info(t("data.live_help"))
    st.code(
        f"insightflow watch --interval 30\n# Incoming folder: {INCOMING_DIR}", language="powershell"
    )
    live_left, live_right = st.columns(2)
    with live_left:
        if st.button("Scan incoming folder once", disabled=read_only, use_container_width=True):
            results = scan_once(DEFAULT_DB_PATH)
            if not results:
                st.info(f"No supported files found in {INCOMING_DIR}")
            else:
                st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
                st.cache_data.clear()
    with live_right:
        if st.button(t("data.refresh"), use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    st.subheader(t("data.history"))
    history = query_df(
        DEFAULT_DB_PATH,
        "SELECT run_at, source_name, load_mode, inserted_rows, skipped_rows FROM etl_runs ORDER BY run_at DESC LIMIT 50",
    )
    st.dataframe(history, use_container_width=True, hide_index=True)
    st.caption(
        f"Database version: {database_version(DEFAULT_DB_PATH)} · Data bounds: {date_bounds(DEFAULT_DB_PATH)}"
    )
