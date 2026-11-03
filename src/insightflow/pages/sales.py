from __future__ import annotations

import streamlit as st

from insightflow.config import DEFAULT_DB_PATH
from insightflow.currency import money, symbol
from insightflow.design import COLORS
from insightflow.diagnostics import dimension_change
from insightflow.geography import country_label
from insightflow.i18n import base_period, current_language, t, tr
from insightflow.metrics import (
    dimension_performance,
    monthly_trend,
    partial_month,
    weekday_pattern,
)
from insightflow.ui import (
    currency_code,
    note,
    page_header,
    period_meta,
    section_header,
    sidebar_filters,
    subhead,
    table_view,
)
from insightflow.viz import heatmap, ranked_bars, show, signed_bars, trend_lines


def _dimension_labels() -> dict[str, str]:
    return {
        "country": tr("国家/地区", "Market"),
        "category": tr("品类", "Category"),
        "channel": tr("渠道", "Channel"),
    }


def render() -> None:
    filters = sidebar_filters(DEFAULT_DB_PATH)
    code = currency_code()
    prefix = symbol(code)
    trend = monthly_trend(DEFAULT_DB_PATH, filters.undated())
    labels = _dimension_labels()
    change = dimension_change(DEFAULT_DB_PATH, filters, "country", limit=50)
    if change.empty:
        page_header(
            t("page.sales.title"),
            tr("当前筛选条件下没有销售。", "No sales under the current filters."),
            meta=period_meta(filters),
        )
        return
    top = change.iloc[0]
    market = country_label(top["country"], current_language())
    page_header(
        t("page.sales.title"),
        tr(
            f"变化最大的市场是{market}，净销售额变化 {money(top['change'], code, short=True)}。",
            f"{market} moved most, with net revenue changing by "
            f"{money(top['change'], code, short=True)}.",
        ),
        meta=period_meta(filters),
    )

    metrics = {
        "revenue": (tr("净销售额", "Net revenue"), prefix),
        "orders": (tr("订单量", "Orders"), ""),
        "active_customers": (tr("活跃客户", "Active customers"), ""),
        "average_order_value": (tr("客单价", "Average order value"), prefix),
    }
    section_header(tr("月度趋势", "Monthly trend"))
    selected = st.segmented_control(
        tr("指标", "Metric"),
        list(metrics),
        default="revenue",
        format_func=lambda key: metrics[key][0],
        label_visibility="collapsed",
        key="sales_metric",
    )
    metric = selected or "revenue"
    label, unit = metrics[metric]
    with st.container(key="unroll_sales_trend"):
        show(
            trend_lines(
                trend,
                "month",
                {metric: (label, COLORS["flow"])},
                money_prefix=unit,
                height=320,
                unfinished=partial_month(DEFAULT_DB_PATH),
            ),
            key="sales_trend",
        )

    section_header(tr("销售结构", "Where sales come from"))
    tabs = st.tabs(list(labels.values()))
    for tab, dimension in zip(tabs, labels, strict=True):
        with tab:
            performance = dimension_performance(DEFAULT_DB_PATH, filters, dimension, limit=100)
            shown = performance.head(16)
            left, right = st.columns([1, 1], gap="large")
            with left:
                subhead(tr("净销售额", "Net revenue"))
                show(
                    ranked_bars(shown, label=dimension, value="revenue", money_prefix=prefix),
                    key=f"sales_bars_{dimension}",
                )
            with right:
                subhead(tr("贡献利润率", "Contribution margin"))
                show(
                    ranked_bars(
                        shown,
                        label=dimension,
                        value="contribution_margin",
                        percent=True,
                        color=COLORS["profit"],
                    ),
                    key=f"sales_margin_{dimension}",
                )
            table_view(
                performance[
                    [dimension, "revenue", "orders", "customers", "average_order_value", "contribution_margin"]
                ].round(3)
            )

    section_header(
        tr(f"相对{base_period()}的变化", f"Change on {base_period()}"),
        tr("同长度的两个周期对比", "Two periods of equal length"),
    )
    dimension = st.segmented_control(
        tr("维度", "Dimension"),
        list(labels),
        default="country",
        format_func=labels.get,
        label_visibility="collapsed",
        key="sales_change_dimension",
    )
    moved = dimension_change(DEFAULT_DB_PATH, filters, dimension or "country", limit=16)
    show(
        signed_bars(moved, label=dimension or "country", value="change", money_prefix=prefix),
        key="sales_change",
    )

    section_header(tr("销售节奏", "Sales rhythm"), tr("按星期和月份的净销售额", "Net revenue by weekday and month"))
    rhythm = weekday_pattern(DEFAULT_DB_PATH, filters.undated())
    if rhythm.empty:
        note(tr("数据不足。", "Not enough data."))
    else:
        days = {
            0: tr("周日", "Sun"),
            1: tr("周一", "Mon"),
            2: tr("周二", "Tue"),
            3: tr("周三", "Wed"),
            4: tr("周四", "Thu"),
            5: tr("周五", "Fri"),
            6: tr("周六", "Sat"),
        }
        grid = rhythm.tail(12).rename(columns=days)
        show(
            heatmap(
                grid,
                x_label=tr("星期", "Weekday"),
                y_label=tr("月份", "Month"),
                percent=False,
                height=360,
            ),
            key="sales_rhythm",
        )
