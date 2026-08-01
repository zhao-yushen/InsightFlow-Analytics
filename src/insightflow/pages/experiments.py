from __future__ import annotations

import plotly.express as px
import streamlit as st

from insightflow.i18n import lt, t
from insightflow.config import DEFAULT_DB_PATH
from insightflow.experiments import analyze_experiment, experiment_catalog
from insightflow.ui import page_header, sidebar_filters


def render() -> None:
    page_header(
        t("page.experiments.title"),
        t("page.experiments.desc"),
        eyebrow="EXPERIMENTATION",
    )
    sidebar_filters(DEFAULT_DB_PATH)
    catalog = experiment_catalog(DEFAULT_DB_PATH)
    if catalog.empty:
        st.info(lt("没有可用实验。"))
        return
    label_map = dict(zip(catalog["experiment_id"], catalog["experiment_name"], strict=False))
    selected = st.selectbox(
        lt("选择实验"),
        catalog["experiment_id"].tolist(),
        format_func=lambda value: f"{label_map[value]}（{value}）",
    )
    summary, metrics, balance = analyze_experiment(DEFAULT_DB_PATH, selected)
    st.caption(lt("实验结果为可重复生成的模拟数据，用于展示实验设计、利润护栏和不确定性判断。"))
    cols = st.columns(5)
    cols[0].metric(lt("样本量"), f"{summary.sample_size:,}")
    cols[1].metric(lt("单客利润提升"), f"£{summary.lift:,.2f}")
    cols[2].metric(lt("95%区间"), f"£{summary.confidence_low:,.2f}～£{summary.confidence_high:,.2f}")
    cols[3].metric(lt("改善概率"), f"{summary.probability_positive:.1%}")
    cols[4].metric(lt("利润护栏"), summary.guardrail_status)
    if "不建议" in summary.decision or "not recommend" in summary.decision.lower():
        st.error(summary.decision)
    elif "建议推广" in summary.decision or "recommend" in summary.decision.lower():
        st.success(summary.decision)
    else:
        st.warning(summary.decision)

    left, right = st.columns([1.4, 1])
    with left:
        chart = metrics.melt(
            id_vars=["metric"],
            value_vars=["control_mean", "treatment_mean"],
            var_name="group",
            value_name="mean",
        )
        st.plotly_chart(px.bar(chart, x="metric", y="mean", color="group", barmode="group"), use_container_width=True)
    with right:
        st.subheader(lt("随机分组与护栏"))
        st.dataframe(balance.round(4), use_container_width=True, hide_index=True)
    st.subheader(lt("指标效应与Bootstrap区间"))
    st.dataframe(metrics.round(4), use_container_width=True, hide_index=True)
    st.markdown(lt("**判断原则：** 订单、转化和收入提升不能替代利润判断；当收入改善但贡献利润下降时，系统会阻止全量推广。"))
