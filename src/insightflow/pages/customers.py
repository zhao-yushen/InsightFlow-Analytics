from __future__ import annotations

import plotly.express as px
import streamlit as st

from insightflow.config import DEFAULT_DB_PATH
from insightflow.i18n import lt, t
from insightflow.metrics import cohort_retention, customer_value_risk, rfm_segments
from insightflow.ui import page_header, sidebar_filters


def render() -> None:
    page_header(
        t("page.customers.title"),
        t("page.customers.desc"),
        eyebrow="CUSTOMER INTELLIGENCE",
    )
    filters = sidebar_filters(DEFAULT_DB_PATH)
    rfm = rfm_segments(DEFAULT_DB_PATH, filters)
    if rfm.empty:
        st.info(lt("当前筛选条件下没有可分析客户。"))
        return

    segment = (
        rfm.groupby("segment", as_index=False)
        .agg(
            customers=("customer_id", "nunique"),
            revenue=("monetary", "sum"),
            contribution_profit=("contribution_profit", "sum"),
            avg_frequency=("frequency", "mean"),
        )
        .sort_values("revenue", ascending=False)
    )
    left, right = st.columns(2)
    with left:
        st.subheader(lt("RFM客户分层"))
        st.plotly_chart(
            px.treemap(segment, path=["segment"], values="contribution_profit", color="customers"),
            use_container_width=True,
        )
    with right:
        st.subheader(lt("客户数、收入与利润贡献"))
        st.dataframe(segment.round(2), use_container_width=True, hide_index=True)

    value = customer_value_risk(DEFAULT_DB_PATH, filters)
    st.subheader(lt("高价值客户流失风险"))
    fig = px.scatter(
        value.head(500),
        x="predicted_clv",
        y="churn_risk",
        size="expected_profit_at_risk",
        color="segment",
        hover_name="customer_id",
        hover_data=["recency", "frequency", "contribution_profit", "recommended_action"],
    )
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(
        value[
            [
                "customer_id",
                "segment",
                "recency",
                "frequency",
                "contribution_profit",
                "predicted_clv",
                "churn_risk",
                "expected_profit_at_risk",
                "recommended_action",
            ]
        ]
        .head(100)
        .round(3),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader(lt("客户队列留存"))
    retention = cohort_retention(DEFAULT_DB_PATH, filters)
    if retention.empty:
        st.info(lt("数据不足以计算队列留存。"))
    else:
        shown = retention.tail(12).iloc[:, :12]
        fig2 = px.imshow(shown, text_auto=".0%", aspect="auto", zmin=0, zmax=1)
        fig2.update_layout(xaxis_title=lt("首次购买后月份"), yaxis_title=lt("首购月份"))
        st.plotly_chart(fig2, use_container_width=True)
