from __future__ import annotations

import plotly.express as px
import streamlit as st

from insightflow.i18n import lt, t
from insightflow.config import DEFAULT_DB_PATH
from insightflow.metrics import product_profitability
from insightflow.ui import page_header, sidebar_filters


def render() -> None:
    page_header(
        t("page.products.title"),
        t("page.products.desc"),
        eyebrow="PRODUCT PERFORMANCE",
    )
    filters = sidebar_filters(DEFAULT_DB_PATH)
    products = product_profitability(DEFAULT_DB_PATH, filters, limit=200)
    if products.empty:
        st.info(lt("当前筛选条件下没有商品数据。"))
        return

    st.subheader(lt("头部商品收入与利润"))
    top = products.head(25).sort_values("revenue")
    st.plotly_chart(
        px.bar(top, x=["revenue", "contribution_profit"], y="description", orientation="h", barmode="group"),
        use_container_width=True,
    )

    st.subheader(lt("商品效率矩阵"))
    fig2 = px.scatter(
        products,
        x="revenue",
        y="contribution_margin",
        size="orders",
        color="category",
        hover_name="description",
        hover_data=["gross_margin", "discount_rate", "units", "contribution_profit"],
    )
    fig2.add_hline(y=products["contribution_margin"].median(), line_dash="dash")
    fig2.add_vline(x=products["revenue"].median(), line_dash="dash")
    st.plotly_chart(fig2, use_container_width=True)
    st.dataframe(products.round(3), use_container_width=True, hide_index=True)
