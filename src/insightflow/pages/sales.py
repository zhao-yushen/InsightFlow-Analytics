from __future__ import annotations

import plotly.express as px
import streamlit as st

from insightflow.config import DEFAULT_DB_PATH
from insightflow.diagnostics import dimension_change
from insightflow.i18n import lt, t
from insightflow.metrics import dimension_performance, monthly_trend
from insightflow.ui import page_header, sidebar_filters


def render() -> None:
    page_header(
        t("page.sales.title"),
        t("page.sales.desc"),
        eyebrow="SALES PERFORMANCE",
    )
    filters = sidebar_filters(DEFAULT_DB_PATH)
    trend = monthly_trend(DEFAULT_DB_PATH, filters)

    st.subheader(lt("月度销售趋势"))
    metric_labels = {
        "revenue": lt("净销售额"),
        "orders": lt("订单量"),
        "active_customers": lt("活跃客户"),
        "average_order_value": lt("客单价"),
    }
    metric = st.radio(
        lt("趋势指标"),
        list(metric_labels),
        horizontal=True,
        format_func=metric_labels.get,
    )
    fig = px.line(
        trend,
        x="month",
        y=metric,
        markers=True,
        labels={"month": lt("月份"), metric: metric_labels[metric]},
    )
    fig.update_traces(line={"width": 2.6}, marker={"size": 6})
    st.plotly_chart(fig, use_container_width=True)

    tabs = st.tabs([lt("国家/地区"), lt("品类"), lt("渠道")])
    for tab, dimension in zip(tabs, ["country", "category", "channel"], strict=False):
        with tab:
            perf = dimension_performance(DEFAULT_DB_PATH, filters, dimension, limit=100)
            fig = px.bar(perf.sort_values("revenue"), x="revenue", y=dimension, orientation="h")
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(perf, use_container_width=True, hide_index=True)

    st.subheader(lt("本期相对上期的结构变化"))
    selected_dimension = st.selectbox(
        lt("拆解维度"),
        ["country", "category", "channel"],
        format_func={"country": lt("国家/地区"), "category": lt("品类"), "channel": lt("渠道")}.get,
    )
    change = dimension_change(DEFAULT_DB_PATH, filters, selected_dimension, limit=50)
    fig = px.bar(change.sort_values("change"), x="change", y=selected_dimension, orientation="h")
    st.plotly_chart(fig, use_container_width=True)
