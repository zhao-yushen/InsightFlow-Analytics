from __future__ import annotations

import streamlit as st

from insightflow.config import DEFAULT_DB_PATH
from insightflow.currency import symbol
from insightflow.diagnostics import (
    dimension_change,
    generate_diagnostics,
    monthly_anomalies,
    profit_driver_decomposition,
)
from insightflow.i18n import current_language, t, tr
from insightflow.metrics import kpi_summary, previous_period
from insightflow.ui import (
    currency_code,
    note,
    page_header,
    period_meta,
    section_header,
    sidebar_filters,
    signal,
    subhead,
    table_view,
)
from insightflow.viz import show, signed_bars


def render() -> None:
    filters = sidebar_filters(DEFAULT_DB_PATH)
    prefix = symbol(currency_code())
    language = current_language()
    issues, revenue_drivers = generate_diagnostics(DEFAULT_DB_PATH, filters, language=language)
    urgent = [issue for issue in issues if issue.severity in {"P0", "P1"}]
    page_header(
        t("page.diagnostics.title"),
        (
            tr(f"发现 {len(issues)} 个信号，其中 {len(urgent)} 个需要优先处理。", f"{len(issues)} signals found, {len(urgent)} needing priority attention.")
            if issues
            else tr("样本太小或没有信号达到阈值。", "The sample is too small or nothing crossed a threshold.")
        ),
        meta=period_meta(filters),
    )

    for issue in issues:
        signal(
            issue.severity,
            issue.title,
            f"{issue.finding} {tr('证据：', 'Evidence: ')}{issue.evidence} "
            f"{tr('建议：', 'Next step: ')}{issue.recommendation}",
        )

    section_header(tr("变化由什么驱动", "What drove the change"), tr("逐项加总等于实际变化", "Each set adds up to the actual change"))
    left, right = st.columns(2, gap="large")
    with left:
        subhead(tr("净销售额", "Net revenue"))
        show(
            signed_bars(revenue_drivers, label="driver", value="revenue_contribution", money_prefix=prefix),
            key="diagnostics_revenue",
        )
    with right:
        subhead(tr("贡献利润", "Contribution profit"))
        drivers = profit_driver_decomposition(
            kpi_summary(DEFAULT_DB_PATH, filters),
            kpi_summary(DEFAULT_DB_PATH, previous_period(filters)),
            language=language,
        )
        show(
            signed_bars(drivers, label="driver", value="profit_contribution", money_prefix=prefix),
            key="diagnostics_profit",
        )

    section_header(tr("问题出在哪里", "Where it happened"))
    labels = {
        "country": tr("国家/地区", "Market"),
        "category": tr("品类", "Category"),
        "channel": tr("渠道", "Channel"),
    }
    metrics = {"change": tr("净销售额变化", "Net revenue change"), "profit_change": tr("贡献利润变化", "Profit change")}
    controls = st.columns(2)
    with controls[0]:
        dimension = st.segmented_control(
            tr("维度", "Dimension"),
            list(labels),
            default="country",
            format_func=labels.get,
            key="diagnostics_dimension",
        )
    with controls[1]:
        metric = st.segmented_control(
            tr("指标", "Metric"),
            list(metrics),
            default="change",
            format_func=metrics.get,
            key="diagnostics_metric",
        )
    chosen = dimension or "country"
    change = dimension_change(DEFAULT_DB_PATH, filters, chosen, limit=16)
    show(signed_bars(change, label=chosen, value=metric or "change", money_prefix=prefix), key="diagnostics_where")
    table_view(change.round(2))

    section_header(tr("历史异常月份", "Unusual months"), tr("用中位数偏差识别，不受极端值影响", "Median-based, so extremes cannot hide"))
    anomalies = monthly_anomalies(DEFAULT_DB_PATH, filters.undated())
    if anomalies.empty:
        note(tr("没有月份超过异常阈值。", "No month crossed the anomaly threshold."))
    else:
        columns = [
            "month",
            "revenue",
            "contribution_profit",
            "cancellation_rate",
            "revenue_robust_z",
            "contribution_profit_robust_z",
            "cancellation_rate_robust_z",
        ]
        st.dataframe(anomalies[columns].round(3), hide_index=True)
