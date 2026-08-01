from __future__ import annotations

import pandas as pd
import streamlit as st

from insightflow.ai_assistant import executive_summary
from insightflow.config import DEFAULT_DB_PATH, is_read_only
from insightflow.diagnostics import generate_diagnostics, profit_driver_decomposition
from insightflow.forecasting import forecast_metric
from insightflow.i18n import lt, t
from insightflow.metrics import (
    inventory_status,
    kpi_summary,
    monthly_trend,
    previous_period,
    quality_dimensions,
    target_status,
)
from insightflow.provenance import STATUS_LABELS, dataset_profile
from insightflow.reporting import (
    build_markdown_report,
    build_word_report_bytes,
    render_html_report,
)
from insightflow.ui import page_header, sidebar_filters


def render() -> None:
    page_header(
        t("page.report.title"),
        t("page.report.desc"),
        eyebrow="EXECUTIVE REPORTING",
    )
    filters = sidebar_filters(DEFAULT_DB_PATH)
    kpi = kpi_summary(DEFAULT_DB_PATH, filters)
    issues, drivers = generate_diagnostics(DEFAULT_DB_PATH, filters)
    trend = monthly_trend(DEFAULT_DB_PATH, filters)
    period = f"{filters.start_date}{lt(' 至 ')}{filters.end_date}"
    summary, engine = executive_summary(issues)
    month = str(pd.Timestamp(filters.end_date).to_period("M"))
    targets = target_status(DEFAULT_DB_PATH, month)
    forecast = forecast_metric(DEFAULT_DB_PATH, "contribution_profit", horizon=3).forecast
    inventory = inventory_status(DEFAULT_DB_PATH, "Reorder").head(15)
    quality = quality_dimensions(DEFAULT_DB_PATH)
    profile = dataset_profile(DEFAULT_DB_PATH)
    profile_text = (
        f"{lt('交易：')}{STATUS_LABELS.get(str(profile.get('transaction_status', 'Mixed')), lt('混合'))}"
        f"{lt('；成本：')}{STATUS_LABELS.get(str(profile.get('economic_status', 'Mixed')), lt('混合'))}"
        f"{lt('；库存：')}{STATUS_LABELS.get(str(profile.get('inventory_status', 'Mixed')), lt('混合'))}"
    )
    profit_bridge = profit_driver_decomposition(
        kpi,
        kpi_summary(DEFAULT_DB_PATH, previous_period(filters)),
    )

    if is_read_only():
        st.info(lt("只读模式下报告在内存中生成，不会写入服务器磁盘。"))
    st.subheader(lt("管理层摘要"))
    st.caption(f"{lt('生成方式：')}{engine}")
    st.write(summary)

    markdown = build_markdown_report(
        period,
        kpi,
        issues,
        drivers,
        targets=targets,
        forecast=forecast,
        data_profile=profile_text,
    )
    st.subheader(lt("报告预览"))
    st.markdown(markdown)

    html = render_html_report(
        period,
        kpi,
        issues,
        drivers,
        trend,
        profit_table=profit_bridge,
        targets=targets,
        forecast=forecast,
        inventory=inventory,
        quality=quality,
        data_profile=profile_text,
    )
    docx = build_word_report_bytes(
        period,
        kpi,
        issues,
        drivers,
        targets=targets,
        forecast=forecast,
        inventory=inventory,
        quality=quality,
        data_profile=profile_text,
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button(
            lt("下载 Markdown"),
            markdown,
            file_name="insightflow_weekly_report.md",
            mime="text/markdown",
        )
    with col2:
        st.download_button(
            lt("下载 HTML"),
            html.encode("utf-8"),
            file_name="insightflow_business_report.html",
            mime="text/html",
        )
    with col3:
        st.download_button(
            lt("下载 Word"),
            docx,
            file_name="insightflow_weekly_report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
