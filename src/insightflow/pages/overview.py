from __future__ import annotations

import pandas as pd
import streamlit as st

from insightflow.config import DEFAULT_DB_PATH
from insightflow.currency import money, symbol
from insightflow.design import COLORS
from insightflow.diagnostics import generate_diagnostics
from insightflow.forecasting import forecast_metric
from insightflow.geography import country_label
from insightflow.i18n import base_period, current_language, t, tr
from insightflow.live import gauge_strip, money_river
from insightflow.metrics import (
    FilterSpec,
    filter_coverage,
    kpi_summary,
    leak_drivers,
    monthly_trend,
    partial_month,
    previous_period,
    quality_score,
    target_status,
)
from insightflow.narrative import (
    LEAK_LABELS,
    overview_story,
    river_payload,
    river_table,
    target_table,
)
from insightflow.pvm import price_volume_mix
from insightflow.ui import (
    currency_code,
    gauge_item,
    note,
    page_header,
    period_meta,
    section_header,
    sidebar_filters,
    signal,
    subhead,
    table_view,
)
from insightflow.viz import forecast_fan, show, trend_lines


def _leak_detail(filters: FilterSpec, leak: str, code: str) -> None:
    """Show which categories and markets drive the outflow picked on the river."""
    chinese, english = next((zh, en) for key, zh, en in LEAK_LABELS if key == leak)
    heading, close = st.columns([5, 1])
    with heading:
        subhead(tr(f"{chinese}来自哪里", f"Where {english.lower()} comes from"))
    with close:
        if st.button(tr("收起", "Close"), key="close_leak_detail", width="stretch"):
            st.session_state.pop("overview_leak", None)
            st.rerun()
    item = tr("名称", "Name")
    amount = tr(f"金额（{code}）", f"Amount ({code})")
    share = tr("占这一项", "Share of this outflow")
    rate = tr("占销售额", "Rate on sales")
    shift = tr(f"比率较{base_period()}", f"Rate on {base_period()}")
    columns = st.columns(2, gap="large")
    for column, dimension, title in (
        (columns[0], "category", tr("按品类", "By category")),
        (columns[1], "country", tr("按市场", "By market")),
    ):
        with column:
            subhead(title)
            frame = leak_drivers(DEFAULT_DB_PATH, filters, leak, dimension)
            if dimension == "country":
                frame["item"] = frame["item"].map(lambda value: country_label(value, current_language()))
            frame = frame.rename(
                columns={
                    "item": item,
                    "amount": amount,
                    "share": share,
                    "rate": rate,
                    "rate_change": shift,
                }
            )
            frame[shift] = frame[shift] * 100
            st.dataframe(
                frame[[item, amount, share, rate, shift]],
                hide_index=True,
                column_config={
                    amount: st.column_config.NumberColumn(format="%,.0f"),
                    share: st.column_config.NumberColumn(format="percent"),
                    rate: st.column_config.NumberColumn(format="percent"),
                    shift: st.column_config.NumberColumn(format="%+.1f pts"),
                },
            )


def render() -> None:
    filters = sidebar_filters(DEFAULT_DB_PATH)
    code = currency_code()
    prefix = symbol(code)
    previous = previous_period(filters)
    current_kpi = kpi_summary(DEFAULT_DB_PATH, filters)
    previous_kpi = kpi_summary(DEFAULT_DB_PATH, previous)
    current_coverage = filter_coverage(DEFAULT_DB_PATH, filters)
    previous_coverage = filter_coverage(DEFAULT_DB_PATH, previous)

    if int(current_coverage["orders"]) == 0:
        page_header(
            t("page.overview.title"),
            tr(
                "当前筛选组合没有有效销售。清空一个维度或扩大日期范围后再看。",
                "No valid sales match these filters. Clear a filter or widen the dates.",
            ),
            meta=period_meta(filters),
        )
        return

    comparable = int(current_coverage["orders"]) >= 5 and int(previous_coverage["orders"]) >= 5
    language = current_language()
    bridge = (
        price_volume_mix(DEFAULT_DB_PATH, filters, language=language) if comparable else None
    )
    page_header(
        t("page.overview.title"),
        overview_story(current_kpi, previous_kpi, bridge, code, comparable=comparable),
        meta=period_meta(filters),
    )

    picked = money_river(
        river_payload(
            current_kpi,
            previous_kpi,
            code,
            comparable=comparable,
            picked=st.session_state.get("overview_leak"),
        ),
        key="overview_river",
    )
    if picked:
        st.session_state["overview_leak"] = picked
    leak = st.session_state.get("overview_leak")
    if leak:
        _leak_detail(filters, leak, code)
    else:
        note(
            tr(
                "点击任意一项流出，查看它来自哪些品类和市场。",
                "Click an outflow to see which categories and markets drive it.",
            )
        )
    table_view(river_table(current_kpi, code), tr("查看资金流明细", "View the money flow as a table"))

    trend = monthly_trend(DEFAULT_DB_PATH, filters.undated())
    recent = trend.tail(12)

    def spark(column: str) -> list[float]:
        return recent[column].fillna(0).astype(float).tolist()

    def metric(label: str, key: str, kind: str, up_is_good: bool = True) -> dict:
        raw = current_kpi[key]
        display = (
            f"{raw:.1%}"
            if kind == "percent"
            else f"{raw:,.0f}"
            if kind == "count"
            else money(raw, code, short=True)
        )
        return gauge_item(
            label,
            raw,
            kind,
            display,
            current=raw,
            previous=previous_kpi[key],
            comparable=comparable,
            up_is_good=up_is_good,
            spark=spark(key) if key in recent.columns else None,
            prefix=prefix,
        )

    gauge_strip(
        [
            metric(tr("净销售额", "Net revenue"), "revenue", "money"),
            metric(tr("贡献利润", "Contribution profit"), "contribution_profit", "money"),
            metric(tr("贡献利润率", "Contribution margin"), "contribution_margin", "percent"),
            metric(tr("订单量", "Orders"), "orders", "count"),
            metric(tr("活跃客户", "Active customers"), "active_customers", "count"),
            metric(tr("退货取消率", "Return rate"), "cancellation_rate", "percent", up_is_good=False),
        ],
        key="overview_gauges",
    )
    if not comparable:
        note(
            tr(
                f"本期或{base_period()}的订单少于 5 笔，因此暂停百分比变化，避免小样本误导。",
                f"Fewer than five orders in this period or {base_period()}, so changes are paused.",
            )
        )

    section_header(
        tr("趋势与信号", "Trend and signals"),
        tr("月度数据不受日期筛选影响", "Monthly history ignores the date filter"),
    )
    left, right = st.columns([1.72, 1], gap="large")
    unfinished = partial_month(DEFAULT_DB_PATH)
    with left:
        with st.container(key="unroll_overview_trend"):
            show(
                trend_lines(
                    trend,
                    "month",
                    {
                        "revenue": (tr("净销售额", "Net revenue"), COLORS["flow"]),
                        "gross_profit": (tr("毛利润", "Gross profit"), "#3D8FE6"),
                        "contribution_profit": (tr("贡献利润", "Contribution profit"), COLORS["profit"]),
                    },
                    money_prefix=prefix,
                    height=360,
                    unfinished=unfinished,
                ),
                key="overview_trend",
            )
        if unfinished:
            note(
                tr(
                    f"{unfinished} 的数据还没到月底，虚线段是天数不足，不代表下跌。",
                    f"{unfinished} is not over yet, so the dotted segment is missing days, not a fall.",
                )
            )
    with right:
        subhead(tr("本期值得处理的问题", "What needs attention"))
        issues, _ = (
            generate_diagnostics(DEFAULT_DB_PATH, filters, language=language)
            if comparable
            else ([], None)
        )
        if not issues:
            note(tr("没有达到阈值的经营异常。", "Nothing crossed an alert threshold."))
        for issue in issues[:5]:
            signal(issue.severity, issue.title, issue.finding)

    section_header(
        tr("前瞻与目标", "Outlook and targets"),
        tr("区间越宽，代表越不确定", "A wider band means less certainty"),
    )
    lower = st.columns([1.45, 1], gap="large")
    with lower[0]:
        try:
            forecast = forecast_metric(
                DEFAULT_DB_PATH, "contribution_profit", horizon=3, filters=filters.undated()
            )
        except ValueError:
            note(tr("至少需要 6 个月数据才能预测。", "Forecasting needs six months of data."))
        else:
            subhead(tr("未来 3 个月贡献利润", "Contribution profit, next 3 months"))
            show(
                forecast_fan(
                    forecast.history,
                    forecast.forecast,
                    "contribution_profit",
                    labels={
                        "actual": tr("实际", "Actual"),
                        "forecast": tr("预测", "Forecast"),
                        "band80": tr("80% 区间", "80% band"),
                        "band95": tr("95% 区间", "95% band"),
                    },
                    money_prefix=prefix,
                    height=320,
                ),
                key="overview_forecast",
            )
            skill = forecast.skill_vs_naive
            note(
                tr(
                    f"回测选中的模型是 {forecast.selected_model}"
                    + (f"，误差比“沿用上月”低 {skill:.0%}。" if skill and skill > 0 else "。"),
                    f"Backtesting chose {forecast.selected_model}"
                    + (f", {skill:.0%} more accurate than repeating last month." if skill and skill > 0 else "."),
                )
            )
    with lower[1]:
        month = str(pd.Timestamp(filters.end_date).to_period("M"))
        subhead(tr(f"{month} 目标", f"{month} targets"))
        targets = target_status(DEFAULT_DB_PATH, month)
        if month == unfinished:
            note(
                tr(
                    "这个月还没结束，金额目标已按已过天数折算。",
                    "This month is still running, so amount targets are prorated by days elapsed.",
                )
            )
        if targets.empty:
            note(tr("这个月没有目标记录。", "No targets recorded for this month."))
        else:
            shown = target_table(targets, code)
            attainment = tr("完成度", "Attainment")
            st.dataframe(
                shown,
                hide_index=True,
                column_config={
                    attainment: st.column_config.ProgressColumn(
                        attainment, min_value=0.0, max_value=1.2, format="percent"
                    )
                },
            )
            note(
                tr(
                    "目标由近三个月均值加规则增幅生成，并非已批准预算。",
                    "Targets are the recent three-month average plus a rule, not an approved budget.",
                )
            )
    st.caption(tr(f"综合数据质量 {quality_score(DEFAULT_DB_PATH):.1f}/100。", f"Data quality {quality_score(DEFAULT_DB_PATH):.1f}/100."))
