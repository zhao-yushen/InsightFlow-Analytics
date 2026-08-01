from __future__ import annotations

import plotly.express as px
import streamlit as st

from insightflow.i18n import lt, t
from insightflow.config import DEFAULT_DB_PATH
from insightflow.diagnostics import (
    dimension_change,
    generate_diagnostics,
    monthly_anomalies,
    profit_driver_decomposition,
)
from insightflow.metrics import kpi_summary, previous_period
from insightflow.ui import page_header, sidebar_filters


def render() -> None:
    page_header(
        t("page.diagnostics.title"),
        t("page.diagnostics.desc"),
        eyebrow="ROOT CAUSE ANALYSIS",
    )
    filters = sidebar_filters(DEFAULT_DB_PATH)
    issues, revenue_drivers = generate_diagnostics(DEFAULT_DB_PATH, filters)

    for issue in issues:
        with st.expander(f"{issue.severity}｜{issue.title}", expanded=issue.severity in {"P0", "P1"}):
            st.write(issue.finding)
            st.markdown(f"{lt('**证据：** ')}{issue.evidence}")
            st.markdown(f"{lt('**建议：** ')}{issue.recommendation}")
            st.caption(f"{lt('规则置信度：')}{issue.confidence:.0%}")

    cols = st.columns(2)
    with cols[0]:
        st.subheader(lt("收入变化驱动"))
        st.plotly_chart(
            px.bar(revenue_drivers, x="driver", y="revenue_contribution", text_auto=".2s"),
            use_container_width=True,
        )
    with cols[1]:
        st.subheader(lt("贡献利润变化驱动"))
        profit_drivers = profit_driver_decomposition(
            kpi_summary(DEFAULT_DB_PATH, filters),
            kpi_summary(DEFAULT_DB_PATH, previous_period(filters)),
        )
        st.plotly_chart(
            px.bar(profit_drivers, x="driver", y="profit_contribution", text_auto=".2s"),
            use_container_width=True,
        )

    st.subheader(lt("结构贡献定位"))
    dimension = st.selectbox(lt("维度"), ["country", "category", "channel"], format_func={"country": lt("国家/地区"), "category": lt("品类"), "channel": lt("渠道")}.get)
    change = dimension_change(DEFAULT_DB_PATH, filters, dimension, limit=50)
    metric = st.radio(lt("变化指标"), ["change", "profit_change"], horizontal=True)
    st.plotly_chart(
        px.bar(change.sort_values(metric), x=metric, y=dimension, orientation="h"),
        use_container_width=True,
    )

    st.subheader(lt("历史异常月份"))
    anomalies = monthly_anomalies(DEFAULT_DB_PATH)
    if anomalies.empty:
        st.info(lt("未发现满足阈值的历史异常月份。"))
    else:
        st.dataframe(anomalies.round(2), use_container_width=True, hide_index=True)
