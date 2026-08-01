from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from insightflow.config import DEFAULT_DB_PATH
from insightflow.diagnostics import generate_diagnostics
from insightflow.forecasting import forecast_metric
from insightflow.i18n import lt, t
from insightflow.metrics import (
    filter_coverage,
    kpi_summary,
    monthly_trend,
    percent_change,
    previous_period,
    quality_score,
    target_status,
)
from insightflow.ui import (
    page_header,
    render_issue_card,
    render_trust_banner,
    section_header,
    sidebar_filters,
)


def _metric(
    label: str,
    value: str,
    current: float,
    previous: float,
    *,
    comparison_enabled: bool = True,
) -> None:
    delta = percent_change(current, previous) if comparison_enabled else None
    st.metric(
        label,
        value,
        "样本不足" if not comparison_enabled else ("—" if delta is None else f"{delta:+.1%}"),
    )


def render() -> None:
    filters = sidebar_filters(DEFAULT_DB_PATH)
    page_header(
        t("page.overview.title"),
        t("page.overview.desc"),
        eyebrow="EXECUTIVE COCKPIT",
        chip=f"{filters.start_date}  →  {filters.end_date}",
    )
    render_trust_banner(DEFAULT_DB_PATH)

    previous = previous_period(filters)
    current_kpi = kpi_summary(DEFAULT_DB_PATH, filters)
    previous_kpi = kpi_summary(DEFAULT_DB_PATH, previous)
    current_coverage = filter_coverage(DEFAULT_DB_PATH, filters)
    previous_coverage = filter_coverage(DEFAULT_DB_PATH, previous)

    if int(current_coverage["orders"]) == 0:
        st.warning(
            lt(
                "当前筛选组合没有有效销售数据。请清空某个维度、扩大日期范围，或检查市场区域与国家是否匹配。"
            )
        )
        st.caption(lt("筛选采用交集逻辑：市场区域、国家、品类和渠道必须同时满足。"))
        return

    comparison_enabled = (
        int(current_coverage["orders"]) >= 5 and int(previous_coverage["orders"]) >= 5
    )
    if not comparison_enabled:
        st.warning(
            lt(
                "当前或上一比较周期的订单少于5笔。系统保留绝对值，但暂停百分比变化与异常结论，避免小样本误导。"
            )
        )

    section_header(lt("核心经营指标"), lt("相较上一等长周期"))
    top = st.columns(5)
    with top[0]:
        _metric(
            lt("净销售额"),
            f"£{current_kpi['revenue']:,.0f}",
            current_kpi["revenue"],
            previous_kpi["revenue"],
            comparison_enabled=comparison_enabled,
        )
    with top[1]:
        _metric(
            "贡献利润",
            f"£{current_kpi['contribution_profit']:,.0f}",
            current_kpi["contribution_profit"],
            previous_kpi["contribution_profit"],
            comparison_enabled=comparison_enabled,
        )
    with top[2]:
        _metric(
            "贡献利润率",
            f"{current_kpi['contribution_margin']:.1%}",
            current_kpi["contribution_margin"],
            previous_kpi["contribution_margin"],
            comparison_enabled=comparison_enabled,
        )
    with top[3]:
        _metric(
            lt("订单量"),
            f"{current_kpi['orders']:,.0f}",
            current_kpi["orders"],
            previous_kpi["orders"],
            comparison_enabled=comparison_enabled,
        )
    with top[4]:
        _metric(
            "活跃客户",
            f"{current_kpi['active_customers']:,.0f}",
            current_kpi["active_customers"],
            previous_kpi["active_customers"],
            comparison_enabled=comparison_enabled,
        )

    secondary = st.columns(3)
    with secondary[0]:
        _metric(
            lt("毛利率"),
            f"{current_kpi['gross_margin']:.1%}",
            current_kpi["gross_margin"],
            previous_kpi["gross_margin"],
            comparison_enabled=comparison_enabled,
        )
    with secondary[1]:
        _metric(
            lt("复购率"),
            f"{current_kpi['repeat_rate']:.1%}",
            current_kpi["repeat_rate"],
            previous_kpi["repeat_rate"],
            comparison_enabled=comparison_enabled,
        )
    with secondary[2]:
        st.metric(lt("数据质量"), f"{quality_score(DEFAULT_DB_PATH):.1f}/100", lt("可信度中心"))

    trend = monthly_trend(DEFAULT_DB_PATH, filters)
    section_header(lt("趋势与经营提示"), lt("连续变化优先于单点读数"))
    left, right = st.columns([1.72, 1], gap="large")
    with left:
        with st.container(border=True):
            st.markdown(f"#### {lt('收入与利润趋势')}")
            fig = px.line(
                trend,
                x="month",
                y=["revenue", "gross_profit", "contribution_profit"],
                markers=True,
                labels={"month": lt("月份"), "value": lt("金额"), "variable": lt("指标")},
            )
            fig.update_traces(line={"width": 2.5}, marker={"size": 6})
            fig.update_layout(height=390, hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
    with right:
        with st.container(border=True):
            st.markdown(f"#### {lt('本期高优先级提示')}")
            issues, _ = (
                generate_diagnostics(DEFAULT_DB_PATH, filters)
                if comparison_enabled
                else ([], pd.DataFrame())
            )
            if not issues:
                st.success(lt("当前没有高优先级经营异常。"))
            for issue in issues[:5]:
                render_issue_card(issue.severity, issue.title, issue.finding)

    forecast = forecast_metric(DEFAULT_DB_PATH, "contribution_profit", horizon=3)
    target_month = str(pd.Timestamp(filters.end_date).to_period("M"))
    targets = target_status(DEFAULT_DB_PATH, target_month)
    section_header(lt("前瞻与目标"), lt("预测区间表达不确定性，不代表确定结果"))
    lower = st.columns([1.45, 1], gap="large")
    with lower[0]:
        with st.container(border=True):
            st.markdown(f"#### {lt('未来3个月贡献利润')}")
            shown = forecast.forecast.copy()
            fig = px.line(
                shown,
                x="month",
                y=["forecast", "lower", "upper"],
                markers=True,
                labels={"month": lt("月份"), "value": lt("贡献利润"), "variable": lt("区间")},
            )
            fig.update_traces(line={"width": 2.3})
            fig.update_layout(height=330, hovermode="x unified")
            st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
            st.caption(f"{lt('回测优选模型：')}{forecast.selected_model}")
    with lower[1]:
        with st.container(border=True):
            st.markdown(f"#### {target_month} {lt('目标状态')}")
            if targets.empty:
                st.info(lt("当前月份没有目标记录。"))
            else:
                shown_targets = targets[
                    ["metric_id", "actual_value", "target_value", "attainment", "status", "owner"]
                ].copy()
                shown_targets["attainment"] = shown_targets["attainment"].map(
                    lambda value: f"{value:.1%}"
                )
                st.dataframe(shown_targets.round(2), use_container_width=True, hide_index=True)
