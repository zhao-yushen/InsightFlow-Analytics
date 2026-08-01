from __future__ import annotations

import plotly.express as px
import streamlit as st

from insightflow.config import DEFAULT_DB_PATH
from insightflow.decision_lab import (
    ScenarioInputs,
    UncertaintyInputs,
    compare_scenarios,
    monte_carlo_scenario,
)
from insightflow.i18n import current_language, lt, t
from insightflow.ui import page_header, render_trust_banner, sidebar_filters


def _scenario_inputs() -> ScenarioInputs:
    pp_format = "%.1f个百分点" if current_language() == "zh-CN" else "%.1f pp"
    col1, col2, col3 = st.columns(3)
    with col1:
        price = st.slider(lt("价格调整"), -15.0, 15.0, 0.0, 0.5, format="%.1f%%")
        discount = st.slider(lt("折扣变化"), -10.0, 10.0, 0.0, 0.5, format=pp_format)
    with col2:
        marketing = st.slider(lt("营销预算变化"), -50.0, 100.0, 0.0, 5.0, format="%.0f%%")
        unit_cost = st.slider(lt("单位采购成本变化"), -15.0, 20.0, 0.0, 0.5, format="%.1f%%")
    with col3:
        shipping = st.slider(lt("物流成本变化"), -20.0, 30.0, 0.0, 1.0, format="%.0f%%")
        cancellation = st.slider(lt("取消率变化"), -5.0, 8.0, 0.0, 0.5, format=pp_format)
    return ScenarioInputs(
        name="User Scenario",
        price_change_pct=price,
        discount_change_pp=discount,
        marketing_change_pct=marketing,
        unit_cost_change_pct=unit_cost,
        shipping_cost_change_pct=shipping,
        cancellation_change_pp=cancellation,
    )


def render() -> None:
    page_header(
        t("page.decision_lab.title"),
        t("page.decision_lab.desc"),
        eyebrow="DECISION SCIENCE",
    )
    filters = sidebar_filters(DEFAULT_DB_PATH)
    render_trust_banner(DEFAULT_DB_PATH)
    st.caption(lt("点估计用于比较方向；概率模拟用于展示参数不确定性、亏损概率和关键敏感因素。"))
    scenario = _scenario_inputs()

    deterministic_tab, uncertainty_tab = st.tabs([lt("方案点估计"), lt("Monte Carlo风险模拟")])
    with deterministic_tab:
        presets = [
            ScenarioInputs(
                name="Profit Protection",
                price_change_pct=2,
                discount_change_pp=-1.5,
                unit_cost_change_pct=-3,
            ),
            ScenarioInputs(name="Growth Push", discount_change_pp=3, marketing_change_pct=25),
            ScenarioInputs(
                name="Operations Fix", shipping_cost_change_pct=-8, cancellation_change_pp=-1.5
            ),
            scenario,
        ]
        comparison = compare_scenarios(DEFAULT_DB_PATH, filters, presets)
        fig = px.scatter(
            comparison,
            x="revenue_change",
            y="contribution_profit_change",
            size="orders",
            color="scenario",
            hover_data=[
                "gross_margin",
                "contribution_margin",
                "discount_rate",
                "cancellation_rate",
            ],
        )
        fig.add_hline(y=0, line_dash="dash")
        fig.add_vline(x=0, line_dash="dash")
        st.plotly_chart(fig, use_container_width=True)
        columns = [
            "scenario",
            "recommended",
            "revenue",
            "revenue_change",
            "contribution_profit",
            "contribution_profit_change",
            "gross_margin",
            "contribution_margin",
            "orders",
            "discount_rate",
            "cancellation_rate",
            "elasticity",
        ]
        st.dataframe(comparison[columns].round(3), use_container_width=True, hide_index=True)
        best = comparison.loc[comparison["recommended"]].iloc[0]
        st.success(
            f"{lt('点估计下贡献利润最高的是 ')}{best['scenario']}"
            f"{lt('：净销售额变化 £')}{best['revenue_change']:,.0f}"
            f"{lt('，贡献利润变化 £')}{best['contribution_profit_change']:,.0f}."
        )

    with uncertainty_tab:
        cols = st.columns(4)
        with cols[0]:
            elasticity_sd = st.number_input(lt("价格弹性标准差"), 0.05, 0.80, 0.22, 0.01)
        with cols[1]:
            demand_sd = st.number_input(lt("基础需求波动"), 0.005, 0.20, 0.035, 0.005)
        with cols[2]:
            cost_sd = st.number_input(lt("采购成本冲击"), 0.005, 0.20, 0.025, 0.005)
        with cols[3]:
            simulations = st.select_slider(
                lt("模拟次数"), options=[1000, 2500, 5000, 10000], value=5000
            )
        uncertainty = UncertaintyInputs(
            elasticity_sd=elasticity_sd,
            baseline_demand_sd=demand_sd,
            cost_shock_sd=cost_sd,
            simulations=simulations,
        )
        summary, samples, sensitivity = monte_carlo_scenario(
            DEFAULT_DB_PATH,
            filters,
            scenario,
            uncertainty,
        )
        row = summary.iloc[0]
        top = st.columns(5)
        top[0].metric(lt("利润变化中位数"), f"£{row['median_profit_change']:,.0f}")
        top[1].metric(lt("90%区间下界"), f"£{row['p05_profit_change']:,.0f}")
        top[2].metric(lt("90%区间上界"), f"£{row['p95_profit_change']:,.0f}")
        top[3].metric(lt("利润改善概率"), f"{row['probability_profit_improves']:.1%}")
        top[4].metric(lt("增收但减利概率"), f"{row['probability_revenue_up_profit_down']:.1%}")

        left, right = st.columns([1.5, 1])
        with left:
            st.plotly_chart(
                px.histogram(samples, x="contribution_profit_change", nbins=60, marginal="box"),
                use_container_width=True,
            )
        with right:
            st.plotly_chart(
                px.bar(
                    sensitivity.sort_values("rank_correlation"),
                    x="rank_correlation",
                    y="driver",
                    orientation="h",
                ),
                use_container_width=True,
            )
        if row["probability_profit_improves"] >= 0.75:
            st.success(lt("在当前不确定性设定下，该方案具有较高的利润改善概率。"))
        elif row["probability_profit_improves"] >= 0.50:
            st.warning(lt("方案方向可行，但结果对关键参数较敏感，建议缩小范围或先做实验。"))
        else:
            st.error(lt("方案改善利润的概率不足50%，不建议直接全量执行。"))
        st.caption(lt("模拟结果取决于用户可见的参数分布；它表达风险范围，不是确定预测。"))
