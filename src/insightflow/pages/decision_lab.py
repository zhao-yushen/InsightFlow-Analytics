from __future__ import annotations

import streamlit as st

from insightflow.config import DEFAULT_DB_PATH
from insightflow.currency import money, symbol
from insightflow.decision_lab import (
    ScenarioInputs,
    UncertaintyInputs,
    compare_scenarios,
    monte_carlo_scenario,
)
from insightflow.i18n import current_language, t, tr
from insightflow.live import gauge_strip, simulation_drop
from insightflow.narrative import simulation_payload
from insightflow.optimizer import Guardrails, efficient_frontier, recommend_plan, search_plans
from insightflow.ui import (
    currency_code,
    gauge_item,
    note,
    page_header,
    period_meta,
    section_header,
    sidebar_filters,
    subhead,
    table_view,
    verdict,
)
from insightflow.viz import frontier, show, signed_bars

DRIVER_LABELS = {
    "elasticity": ("价格弹性", "Price elasticity"),
    "marketing_response": ("营销响应", "Marketing response"),
    "baseline_demand_factor": ("基础需求", "Baseline demand"),
    "cost_shock": ("采购成本", "Purchase cost"),
    "shipping_shock": ("物流成本", "Shipping cost"),
}


def _scenario_inputs() -> ScenarioInputs:
    points = "%.1f 个百分点" if current_language() == "zh-CN" else "%.1f pts"
    columns = st.columns(3, gap="large")
    with columns[0]:
        price = st.slider(tr("价格调整", "Price change"), -15.0, 15.0, 0.0, 0.5, format="%.1f%%")
        discount = st.slider(tr("折扣变化", "Discount change"), -10.0, 10.0, 0.0, 0.5, format=points)
    with columns[1]:
        marketing = st.slider(tr("营销预算", "Marketing budget"), -50.0, 100.0, 0.0, 5.0, format="%.0f%%")
        unit_cost = st.slider(tr("采购成本", "Purchase cost"), -15.0, 20.0, 0.0, 0.5, format="%.1f%%")
    with columns[2]:
        shipping = st.slider(tr("物流成本", "Shipping cost"), -20.0, 30.0, 0.0, 1.0, format="%.0f%%")
        cancellation = st.slider(tr("退货取消率", "Return rate"), -5.0, 8.0, 0.0, 0.5, format=points)
    return ScenarioInputs(
        name=tr("你的方案", "Your plan"),
        price_change_pct=price,
        discount_change_pp=discount,
        marketing_change_pct=marketing,
        unit_cost_change_pct=unit_cost,
        shipping_cost_change_pct=shipping,
        cancellation_change_pp=cancellation,
    )


def _simulation_tab(filters, scenario: ScenarioInputs, code: str) -> None:
    prefix = symbol(code)
    controls = st.columns(4)
    with controls[0]:
        elasticity_sd = st.number_input(tr("价格弹性不确定性", "Elasticity uncertainty"), 0.05, 0.80, 0.22, 0.01)
    with controls[1]:
        demand_sd = st.number_input(tr("需求波动", "Demand volatility"), 0.005, 0.20, 0.035, 0.005, format="%.3f")
    with controls[2]:
        cost_sd = st.number_input(tr("成本波动", "Cost volatility"), 0.005, 0.20, 0.025, 0.005, format="%.3f")
    with controls[3]:
        simulations = st.select_slider(tr("模拟次数", "Simulations"), options=[1000, 2500, 5000, 10000], value=5000)
    uncertainty = UncertaintyInputs(
        elasticity_sd=elasticity_sd,
        baseline_demand_sd=demand_sd,
        cost_shock_sd=cost_sd,
        simulations=simulations,
    )
    summary, samples, sensitivity = monte_carlo_scenario(DEFAULT_DB_PATH, filters, scenario, uncertainty)
    row = summary.iloc[0]
    gauge_strip(
        [
            gauge_item(tr("利润变化中位数", "Median profit change"), row["median_profit_change"], "money", money(row["median_profit_change"], code, short=True), prefix=prefix, note_text=""),
            gauge_item(tr("较差情形（5%）", "Bad case (5%)"), row["p05_profit_change"], "money", money(row["p05_profit_change"], code, short=True), prefix=prefix, note_text=""),
            gauge_item(tr("较好情形（95%）", "Good case (95%)"), row["p95_profit_change"], "money", money(row["p95_profit_change"], code, short=True), prefix=prefix, note_text=""),
            gauge_item(tr("利润改善概率", "Chance profit improves"), row["probability_profit_improves"], "percent", f"{row['probability_profit_improves']:.1%}", note_text=""),
            gauge_item(tr("增收但减利概率", "Revenue up, profit down"), row["probability_revenue_up_profit_down"], "percent", f"{row['probability_revenue_up_profit_down']:.1%}", note_text=""),
        ],
        key="simulation_gauges",
    )
    left, right = st.columns([1.7, 1], gap="large")
    with left:
        subhead(tr("每个点是一种可能的结果", "Each dot is one possible outcome"))
        signature = f"{scenario}|{uncertainty}|{filters}"
        simulation_drop(
            simulation_payload(samples["contribution_profit_change"], row, code, signature=signature),
            key="simulation_drop",
        )
    with right:
        subhead(tr("结果最受什么影响", "What moves the result most"))
        shown = sensitivity.copy()
        shown["driver"] = shown["driver"].map(lambda key: tr(*DRIVER_LABELS.get(key, (key, key))))
        show(
            signed_bars(
                shown,
                label="driver",
                value="rank_correlation",
                decimals=".2f",
                tick_format=".1f",
                height=300,
            ),
            key="simulation_sensitivity",
        )
        note(tr("条形越长，这个因素对利润结果的影响越大。", "A longer bar means this factor moves the result more."))
    probability = float(row["probability_profit_improves"])
    if not any(
        (
            scenario.price_change_pct,
            scenario.discount_change_pp,
            scenario.marketing_change_pct,
            scenario.unit_cost_change_pct,
            scenario.shipping_cost_change_pct,
            scenario.cancellation_change_pp,
        )
    ):
        note(tr("移动上方滑块，看看方案如何改变结果。", "Move the sliders above to test a plan."))
    elif probability >= 0.75:
        verdict(
            tr("可以推进", "Worth pursuing"),
            tr(f"有 {probability:.0%} 的把握改善利润。", f"A {probability:.0%} chance of improving profit."),
            "good",
        )
    elif probability >= 0.5:
        verdict(
            tr("先做小范围测试", "Pilot first"),
            tr("方向向好，但对关键参数敏感。", "The direction is good but sensitive to key assumptions."),
            "warning",
        )
    else:
        verdict(
            tr("不建议全量执行", "Not for a full rollout"),
            tr(f"改善利润的概率只有 {probability:.0%}。", f"Only a {probability:.0%} chance of improving profit."),
            "bad",
        )
    note(
        tr(
            "结果取决于上面列出的假设，表达的是风险范围，不是确定预测。",
            "Results depend on the assumptions shown here. They describe a range of risk, not a prediction.",
        )
    )


def _comparison_tab(filters, scenario: ScenarioInputs, code: str) -> None:
    prefix = symbol(code)
    presets = [
        ScenarioInputs(name=tr("保利润", "Protect profit"), price_change_pct=2, discount_change_pp=-1.5, unit_cost_change_pct=-3),
        ScenarioInputs(name=tr("冲增长", "Push growth"), discount_change_pp=3, marketing_change_pct=25),
        ScenarioInputs(name=tr("降运营成本", "Cut operating cost"), shipping_cost_change_pct=-8, cancellation_change_pp=-1.5),
        scenario,
    ]
    comparison = compare_scenarios(DEFAULT_DB_PATH, filters, presets)
    comparison = comparison[comparison["scenario"] != "Baseline"]
    left, right = st.columns(2, gap="large")
    with left:
        subhead(tr("贡献利润变化", "Contribution profit change"))
        show(signed_bars(comparison, label="scenario", value="contribution_profit_change", money_prefix=prefix), key="comparison_profit")
    with right:
        subhead(tr("净销售额变化", "Net revenue change"))
        show(signed_bars(comparison, label="scenario", value="revenue_change", money_prefix=prefix), key="comparison_revenue")
    best = comparison.sort_values("contribution_profit", ascending=False).iloc[0]
    verdict(
        str(best["scenario"]),
        tr(
            f"点估计下利润最高：贡献利润变化 {money(best['contribution_profit_change'], code, short=True)}，"
            f"净销售额变化 {money(best['revenue_change'], code, short=True)}。",
            f"Highest point estimate: contribution profit {money(best['contribution_profit_change'], code, short=True)}, "
            f"net revenue {money(best['revenue_change'], code, short=True)}.",
        ),
        "neutral",
    )
    table_view(
        comparison[
            ["scenario", "revenue", "revenue_change", "contribution_profit", "contribution_profit_change", "gross_margin", "contribution_margin", "elasticity"]
        ].round(3)
    )


def _optimizer_tab(filters, code: str) -> None:
    prefix = symbol(code)
    note(
        tr(
            "一次评估 245 个价格、折扣和营销组合。所有方案面对同一批模拟未来，差异只来自方案本身。",
            "245 combinations of price, discount and marketing, all facing the same simulated "
            "futures, so differences come from the plan alone.",
        )
    )
    controls = st.columns(2, gap="large")
    with controls[0]:
        probability = st.slider(tr("最低利润改善概率", "Minimum chance of improving profit"), 50, 95, 70, 5, format="%d%%")
    with controls[1]:
        drop = st.slider(tr("可接受的收入下降", "Acceptable revenue drop"), 0, 15, 5, 1, format="%d%%")
    plans = search_plans(
        DEFAULT_DB_PATH,
        filters,
        guardrails=Guardrails(max_revenue_drop_pct=float(drop), min_probability=probability / 100),
    )
    edge = efficient_frontier(plans)
    chosen = recommend_plan(plans)
    if chosen is None:
        verdict(
            tr("没有方案满足条件", "No plan clears these limits"),
            tr("放宽概率或收入下限后再试。", "Relax the probability or revenue limit and try again."),
            "warning",
        )
    else:
        at_edge = (
            abs(chosen["price_change_pct"]) == 6
            or abs(chosen["discount_change_pp"]) == 3
            or abs(chosen["marketing_change_pct"]) == 30
        )
        verdict(
            tr(
                f"价格 {chosen['price_change_pct']:+.0f}%，折扣 {chosen['discount_change_pp']:+.0f} 个百分点，营销 {chosen['marketing_change_pct']:+.0f}%",
                f"Price {chosen['price_change_pct']:+.0f}%, discount {chosen['discount_change_pp']:+.0f} pts, marketing {chosen['marketing_change_pct']:+.0f}%",
            ),
            tr(
                f"利润变化中位数 {money(chosen['median_profit_change'], code, short=True)}，"
                f"较差情形 {money(chosen['p05_profit_change'], code, short=True)}，"
                f"改善概率 {chosen['probability_profit_improves']:.0%}。"
                + ("推荐方案落在搜索边界，说明模型希望走得更远，请先小范围验证。" if at_edge else ""),
                f"Median profit change {money(chosen['median_profit_change'], code, short=True)}, bad case "
                f"{money(chosen['p05_profit_change'], code, short=True)}, "
                f"{chosen['probability_profit_improves']:.0%} chance of improving."
                + (" The plan sits at the edge of the search range, so pilot it first." if at_edge else ""),
            ),
            "good",
        )
    subhead(tr("收益与风险", "Return against risk"))
    show(
        frontier(
            plans,
            edge,
            chosen,
            labels={
                "x": tr("较差情形的利润变化（5%）", "Bad-case profit change (5%)"),
                "y": tr("利润变化中位数", "Median profit change"),
                "passed": tr("满足条件", "Within limits"),
                "failed": tr("未满足", "Outside limits"),
                "frontier": tr("最优边界", "Best available"),
                "chosen": tr("推荐方案", "Recommended"),
            },
            money_prefix=prefix,
        ),
        key="optimizer_frontier",
    )
    note(
        tr(
            "越靠右上越好：向右代表坏情况也不太差，向上代表通常结果更好。",
            "Up and to the right is better: right means the bad case is milder, up means the "
            "typical result is stronger.",
        )
    )
    table_view(plans.head(25).round(3), tr("查看前 25 个方案", "View the top 25 plans"))


def render() -> None:
    filters = sidebar_filters(DEFAULT_DB_PATH)
    code = currency_code()
    page_header(
        t("page.decision_lab.title"),
        tr(
            "先模拟再决定：调整方案，查看数千种可能的结果，或让系统搜索风险最合适的方案。",
            "Simulate before deciding: adjust a plan, see thousands of possible outcomes, or let "
            "the system search for the best risk-adjusted plan.",
        ),
        meta=period_meta(filters),
    )
    section_header(tr("你的方案", "Your plan"), tr("相对当前筛选周期的调整", "Changes against the current period"))
    scenario = _scenario_inputs()
    simulate, compare, optimize = st.tabs(
        [tr("风险模拟", "Risk simulation"), tr("方案对比", "Plan comparison"), tr("自动寻优", "Plan search")]
    )
    with simulate:
        _simulation_tab(filters, scenario, code)
    with compare:
        _comparison_tab(filters, scenario, code)
    with optimize:
        _optimizer_tab(filters, code)
