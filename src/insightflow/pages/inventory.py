from __future__ import annotations

import plotly.express as px
import streamlit as st

from insightflow.config import DEFAULT_DB_PATH
from insightflow.i18n import lt, t
from insightflow.metrics import inventory_kpis, inventory_status
from insightflow.ui import page_header, sidebar_filters


def render() -> None:
    page_header(
        t("page.inventory.title"),
        t("page.inventory.desc"),
        eyebrow="OPERATIONS CONTROL",
    )
    sidebar_filters(DEFAULT_DB_PATH)
    kpi = inventory_kpis(DEFAULT_DB_PATH)
    cols = st.columns(5)
    cols[0].metric(lt("SKU数量"), f"{kpi['sku_count']:,.0f}")
    cols[1].metric(lt("需补货SKU"), f"{kpi['reorder_skus']:,.0f}")
    cols[2].metric(lt("滞销风险SKU"), f"{kpi['overstock_skus']:,.0f}")
    cols[3].metric(lt("库存价值"), f"£{kpi['inventory_value']:,.0f}")
    cols[4].metric(lt("平均可售天数"), f"{kpi['avg_days_of_supply']:.1f}")

    data = inventory_status(DEFAULT_DB_PATH)
    st.subheader(lt("库存覆盖与需求"))
    chart_data = data[data["days_of_supply"] < 300].copy()
    st.plotly_chart(
        px.scatter(
            chart_data,
            x="days_of_supply",
            y="units_30d",
            size="inventory_value",
            color="inventory_status",
            hover_name="description",
            hover_data=["supplier", "supplier_lead_days", "inventory_on_hand"],
        ),
        use_container_width=True,
    )

    tabs = st.tabs([lt("补货预警"), lt("滞销风险"), lt("全部库存")])
    with tabs[0]:
        st.dataframe(
            inventory_status(DEFAULT_DB_PATH, "Reorder").round(2),
            use_container_width=True,
            hide_index=True,
        )
    with tabs[1]:
        st.dataframe(
            inventory_status(DEFAULT_DB_PATH, "Overstock").round(2),
            use_container_width=True,
            hide_index=True,
        )
    with tabs[2]:
        st.dataframe(data.round(2), use_container_width=True, hide_index=True)
