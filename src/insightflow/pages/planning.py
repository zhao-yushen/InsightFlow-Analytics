from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from insightflow.config import DEFAULT_DB_PATH
from insightflow.forecasting import forecast_metric
from insightflow.i18n import lt, t
from insightflow.metrics import target_status
from insightflow.ui import page_header, sidebar_filters

LABELS = {"revenue": lt("净销售额"), "contribution_profit": lt("贡献利润"), "orders": lt("订单量")}


def render() -> None:
    page_header(
        t("page.planning.title"),
        t("page.planning.desc"),
        eyebrow="PLANNING & FORECASTING",
    )
    filters = sidebar_filters(DEFAULT_DB_PATH)
    month = str(pd.Timestamp(filters.end_date).to_period("M"))
    target = target_status(DEFAULT_DB_PATH, month)

    st.subheader(f"{month} {lt('目标状态')}")
    if target.empty:
        st.info(lt("该月份没有目标记录。"))
    else:
        shown = target.copy()
        shown["attainment"] = shown["attainment"].map(lambda x: f"{x:.1%}")
        st.dataframe(shown, use_container_width=True, hide_index=True)

    st.subheader(lt("未来经营预测"))
    metric = st.selectbox(
        lt("预测指标"), ["revenue", "contribution_profit", "orders"], format_func=LABELS.get
    )
    horizon = st.slider(lt("预测月数"), 1, 6, 3)
    result = forecast_metric(DEFAULT_DB_PATH, metric, horizon=horizon)
    st.caption(f"{lt('自动选择模型：')}{result.selected_model}")

    history = result.history.rename(columns={metric: "actual"})
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=history["month"], y=history["actual"], name=lt("实际值"), mode="lines+markers")
    )
    fig.add_trace(
        go.Scatter(
            x=result.forecast["month"],
            y=result.forecast["forecast"],
            name=lt("预测值"),
            mode="lines+markers",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=list(result.forecast["month"]) + list(result.forecast["month"])[::-1],
            y=list(result.forecast["upper"]) + list(result.forecast["lower"])[::-1],
            fill="toself",
            name=lt("95%预测区间"),
            line={"width": 0},
            opacity=0.2,
        )
    )
    st.plotly_chart(fig, use_container_width=True)

    left, right = st.columns(2)
    with left:
        st.subheader(lt("模型回测排名"))
        board = result.leaderboard.copy()
        board["mape"] = board["mape"].map(lambda x: f"{x:.1%}")
        st.dataframe(board.round(2), use_container_width=True, hide_index=True)
    with right:
        st.subheader(lt("预测结果"))
        st.dataframe(result.forecast.round(2), use_container_width=True, hide_index=True)
        st.caption(lt("模型根据历史滚动回测的MAPE与RMSE自动选择，避免只展示单一预测结果。"))
