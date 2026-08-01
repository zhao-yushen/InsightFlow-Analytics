from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from insightflow.i18n import lt, t
from insightflow.config import DEFAULT_DB_PATH
from insightflow.diagnostics import profit_driver_decomposition
from insightflow.metrics import (
    cost_waterfall,
    kpi_summary,
    previous_period,
    product_profitability,
)
from insightflow.ui import page_header, sidebar_filters


def render() -> None:
    page_header(
        t("page.profit.title"),
        t("page.profit.desc"),
        eyebrow="PROFITABILITY",
    )
    filters = sidebar_filters(DEFAULT_DB_PATH)
    current = kpi_summary(DEFAULT_DB_PATH, filters)
    previous = kpi_summary(DEFAULT_DB_PATH, previous_period(filters))

    metrics = [
        (lt("净销售额"), current["revenue"], previous["revenue"], "£{:,.0f}"),
        (lt("贡献利润"), current["contribution_profit"], previous["contribution_profit"], "£{:,.0f}"),
        (lt("贡献利润率"), current["contribution_margin"], previous["contribution_margin"], "{:.1%}"),
        (lt("毛利润"), current["gross_profit"], previous["gross_profit"], "£{:,.0f}"),
        (lt("毛利率"), current["gross_margin"], previous["gross_margin"], "{:.1%}"),
        (lt("单均利润"), current["profit_per_order"], previous["profit_per_order"], "£{:,.2f}"),
    ]
    for row_metrics in (metrics[:3], metrics[3:]):
        cols = st.columns(3)
        for col, (label, value, prev, fmt) in zip(cols, row_metrics):
            delta = (value - prev) / abs(prev) if prev else None
            col.metric(label, fmt.format(value), "—" if delta is None else f"{delta:+.1%}")

    left, right = st.columns(2)
    with left:
        st.subheader(lt("利润瀑布"))
        waterfall = cost_waterfall(DEFAULT_DB_PATH, filters)
        measures = ["absolute"] + ["relative"] * (len(waterfall) - 2) + ["total"]
        fig = go.Figure(
            go.Waterfall(
                x=waterfall["component"],
                y=waterfall["value"],
                measure=measures,
                connector={"line": {"width": 1}},
            )
        )
        st.plotly_chart(fig, use_container_width=True)
    with right:
        st.subheader(lt("贡献利润变化桥接"))
        bridge = profit_driver_decomposition(current, previous)
        st.plotly_chart(
            px.bar(bridge, x="driver", y="profit_contribution", text_auto=".2s"),
            use_container_width=True,
        )
        st.caption(lt("三个因素贡献之和与贡献利润前后期差额完全对账。"))

    st.subheader(lt("商品收入—利润矩阵"))
    products = product_profitability(DEFAULT_DB_PATH, filters, limit=150)
    if products.empty:
        st.info(lt("当前筛选条件下没有商品数据。"))
        return
    fig2 = px.scatter(
        products,
        x="revenue",
        y="contribution_margin",
        size="orders",
        color="category",
        hover_name="description",
        hover_data=["contribution_profit", "discount_rate", "gross_margin"],
    )
    fig2.add_hline(y=products["contribution_margin"].median(), line_dash="dash")
    fig2.add_vline(x=products["revenue"].median(), line_dash="dash")
    st.plotly_chart(fig2, use_container_width=True)

    st.subheader(lt("高收入低利润商品"))
    low_margin = products[
        (products["revenue"] >= products["revenue"].median())
        & (products["contribution_margin"] < products["contribution_margin"].median())
    ].sort_values("revenue", ascending=False)
    st.dataframe(low_margin.head(30).round(3), use_container_width=True, hide_index=True)
