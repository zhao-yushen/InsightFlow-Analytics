from __future__ import annotations

import pandas as pd
import streamlit as st

from insightflow.ai_assistant import executive_summary
from insightflow.config import DEFAULT_DB_PATH, is_read_only
from insightflow.diagnostics import generate_diagnostics, profit_driver_decomposition
from insightflow.forecasting import forecast_metric
from insightflow.i18n import current_language, t, tr
from insightflow.metrics import (
    inventory_status,
    kpi_summary,
    monthly_trend,
    previous_period,
    quality_dimensions,
    target_status,
)
from insightflow.reporting import (
    build_markdown_report,
    build_word_report_bytes,
    render_html_report,
)
from insightflow.ui import (
    currency_code,
    note,
    page_header,
    period_meta,
    section_header,
    sidebar_filters,
    trust_sentence,
)


def render() -> None:
    filters = sidebar_filters(DEFAULT_DB_PATH)
    code = currency_code()
    kpi = kpi_summary(DEFAULT_DB_PATH, filters)
    issues, drivers = generate_diagnostics(DEFAULT_DB_PATH, filters)
    trend = monthly_trend(DEFAULT_DB_PATH, filters.undated())
    period = f"{filters.start_date} {tr('至', 'to')} {filters.end_date}"
    summary, engine = executive_summary(
        generate_diagnostics(DEFAULT_DB_PATH, filters, language=current_language())[0],
        current_language(),
    )
    month = str(pd.Timestamp(filters.end_date).to_period("M"))
    targets = target_status(DEFAULT_DB_PATH, month)
    try:
        forecast = forecast_metric(
            DEFAULT_DB_PATH, "contribution_profit", horizon=3, filters=filters.undated()
        ).forecast
    except ValueError:
        forecast = pd.DataFrame()
    inventory = inventory_status(DEFAULT_DB_PATH, "Reorder").head(15)
    quality = quality_dimensions(DEFAULT_DB_PATH)
    trust = trust_sentence(DEFAULT_DB_PATH)
    profit_bridge = profit_driver_decomposition(
        kpi, kpi_summary(DEFAULT_DB_PATH, previous_period(filters))
    )
    page_header(t("page.report.title"), summary.split("\n\n")[0], meta=period_meta(filters))

    markdown = build_markdown_report(
        period,
        kpi,
        issues,
        drivers,
        targets=targets,
        forecast=forecast,
        data_profile=trust,
        currency=code,
    )
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
        data_profile=trust,
        currency=code,
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
        data_profile=trust,
        currency=code,
    )

    section_header(tr("下载报告", "Download the report"), f"{tr('摘要来源：', 'Summary by: ')}{engine}")
    columns = st.columns(3)
    with columns[0]:
        st.download_button(
            tr("下载 HTML", "Download HTML"),
            html.encode("utf-8"),
            file_name="insightflow_business_report.html",
            mime="text/html",
            type="primary",
            width="stretch",
        )
    with columns[1]:
        st.download_button(
            tr("下载 Word", "Download Word"),
            docx,
            file_name="insightflow_weekly_report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            width="stretch",
        )
    with columns[2]:
        st.download_button(
            tr("下载 Markdown", "Download Markdown"),
            markdown,
            file_name="insightflow_weekly_report.md",
            mime="text/markdown",
            width="stretch",
        )
    if is_read_only():
        note(tr("只读模式下报告在内存中生成，不写入服务器。", "In read-only mode reports stay in memory."))

    section_header(tr("报告预览", "Report preview"))
    st.markdown(markdown)
