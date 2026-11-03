from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from insightflow.config import DEFAULT_DB_PATH
from insightflow.currency import money, symbol
from insightflow.design import COLORS
from insightflow.elasticity import category_price_moves, estimate_elasticities
from insightflow.i18n import t, tr
from insightflow.provenance import dataset_profile
from insightflow.ui import (
    currency_code,
    note,
    page_header,
    period_meta,
    section_header,
    sidebar_filters,
    subhead,
    verdict,
)
from insightflow.viz import show, signed_bars


def _elasticity_chart(table) -> go.Figure:
    """Each category's estimate with its uncertainty, beside the assumption it replaces."""
    data = table.sort_values("elasticity", ascending=False)
    figure = go.Figure()
    figure.add_scatter(
        x=data["prior"],
        y=data["category"],
        mode="markers",
        name=tr("行业假设", "Assumption"),
        marker={"size": 9, "color": COLORS["line"], "symbol": "diamond"},
        hovertemplate=tr("假设 %{x:.2f}", "Assumed %{x:.2f}") + "<extra></extra>",
    )
    figure.add_scatter(
        x=data["elasticity"],
        y=data["category"],
        mode="markers",
        name=tr("数据估计", "Estimate"),
        error_x={
            "type": "data",
            "array": (1.96 * data["standard_error"]).fillna(0),
            "color": COLORS["ink_soft"],
            "thickness": 1,
            "width": 0,
        },
        marker={"size": 10, "color": COLORS["flow"], "line": {"color": COLORS["page"], "width": 2}},
        hovertemplate=tr("估计 %{x:.2f}", "Estimated %{x:.2f}") + "<extra></extra>",
    )
    figure.add_vline(x=-1, line={"color": COLORS["line"], "width": 1})
    figure.update_layout(height=max(320, 34 * len(data) + 70))
    figure.update_xaxes(title=tr("价格弹性：涨价 1% 时订单变化的百分比", "Elasticity: % change in orders per 1% price rise"))
    figure.update_yaxes(showgrid=False)
    return figure


def render() -> None:
    filters = sidebar_filters(DEFAULT_DB_PATH)
    code = currency_code()
    prefix = symbol(code)
    table = estimate_elasticities(DEFAULT_DB_PATH, filters)
    limit = st.session_state.get("pricing_limit", 10)
    moves = category_price_moves(DEFAULT_DB_PATH, filters, max_move=limit / 100)
    if table.empty or moves.empty:
        page_header(
            t("page.pricing.title"),
            tr("当前范围的数据不足以估算价格反应。", "Not enough data to measure price response."),
            meta=period_meta(filters),
        )
        return
    measured = int((table["basis"] == "data").sum())
    robust = moves[moves["robust"]]
    capped = bool(moves["capped"].mean() > 0.6)
    costs_known = str(dataset_profile(DEFAULT_DB_PATH).get("economic_status")) in {
        "Verified",
        "Simulated",
    }

    def span(row) -> str:
        low = money(float(row["profit_change_low"]), code, short=True)
        high = money(float(row["profit_change_high"]), code, short=True)
        return f"{low} ~ {high}"

    if not costs_known:
        lede = tr(
            f"{len(table)} 个品类中有 {measured} 个可由订单数据测出价格反应。成本是估算值，"
            "下面的调价收益只能看方向，不能当作预期利润。",
            f"Price response is measurable for {measured} of {len(table)} categories. Costs are "
            "estimated, so the gains below show direction, not expected profit.",
        )
    elif robust.empty:
        lede = tr(
            f"{len(table)} 个品类中有 {measured} 个可由订单数据测出价格反应，"
            "但没有哪个品类的调价能在弹性的 95% 区间内都赚钱。",
            f"Price response is measurable for {measured} of {len(table)} categories, but no "
            "move stays profitable across the elasticity's 95% interval.",
        )
    else:
        best = robust.iloc[0]
        lede = tr(
            f"{len(table)} 个品类中有 {measured} 个可由订单数据测出价格反应，{len(robust)} 个品类的调价"
            f"稳健。潜力最大的是 {best['category']}：调价 {best['recommended_move']:+.0%}，"
            f"贡献利润预计变化 {span(best)}。",
            f"Price response is measurable for {measured} of {len(table)} categories, and "
            f"{len(robust)} moves hold up. {best['category']} has the largest opportunity: "
            f"{best['recommended_move']:+.0%} for {span(best)} of contribution profit.",
        )
    page_header(t("page.pricing.title"), lede, meta=period_meta(filters))

    section_header(
        tr("顾客对价格有多敏感", "How sensitive customers are to price"),
        tr("线段是 95% 区间；竖线左侧代表涨价会减少总收入", "Bars show 95% intervals; left of the line, a rise cuts revenue"),
    )
    show(_elasticity_chart(table), key="pricing_elasticity")
    note(
        tr(
            "按周统计每个商品在各销售渠道的订单数和实际售价，并扣除商品本身受欢迎程度和季节的影响。"
            "不同渠道和匿名订单常用不同价目表，所以分开跟踪。数据太少时回到行业假设。",
            "Weekly orders and paid prices per product in each sales stream, with popularity and "
            "season removed. Streams often use different price lists, so each is followed on its "
            "own. With thin data the result falls back to the assumption.",
        )
    )

    section_header(tr("每个品类该怎么调", "What to do in each category"))
    st.slider(
        tr("单次调价上限", "Largest single move"),
        3,
        15,
        step=1,
        format="%d%%",
        key="pricing_limit",
        value=limit,
    )
    left, right = st.columns([1, 1.1], gap="large")
    with left:
        subhead(tr("预计贡献利润变化", "Expected profit change"))
        show(
            signed_bars(moves, label="category", value="expected_profit_change", money_prefix=prefix),
            key="pricing_moves",
        )
    with right:
        subhead(tr("调价建议", "Suggested moves"))
        columns = {
            "category": tr("品类", "Category"),
            "current_price": tr("当前均价", "Average price"),
            "unit_variable_cost": tr("单位变动成本", "Unit variable cost"),
            "recommended_move": tr("建议调价", "Suggested move"),
            "profit_change_low": tr("利润区间下限", "Profit, low end"),
            "profit_change_high": tr("利润区间上限", "Profit, high end"),
            "expected_revenue_change": tr("收入变化", "Revenue change"),
        }
        st.dataframe(
            moves[list(columns)].rename(columns=columns),
            hide_index=True,
            column_config={
                columns["current_price"]: st.column_config.NumberColumn(format="%.2f"),
                columns["unit_variable_cost"]: st.column_config.NumberColumn(format="%.2f"),
                columns["recommended_move"]: st.column_config.NumberColumn(format="percent"),
                columns["profit_change_low"]: st.column_config.NumberColumn(format="%,.0f"),
                columns["profit_change_high"]: st.column_config.NumberColumn(format="%,.0f"),
                columns["expected_revenue_change"]: st.column_config.NumberColumn(format="%,.0f"),
            },
        )
    if not costs_known:
        verdict(
            tr("成本是估算值", "Costs are estimated"),
            tr(
                "这份数据没有真实成本，利润变化按规则成本计算，只能看方向。导入成本字段后这里才是可用的金额。",
                "This data has no real costs, so profit changes rest on rule-based costs and show "
                "direction only. Import a cost field to get usable amounts.",
            ),
            "warning",
        )
    if capped:
        verdict(
            tr("先做实验", "Test before rolling out"),
            tr(
                "多数品类都触到了调价上限，说明模型认为价格整体偏低。这个结论只在历史价格附近可靠，全量调价前请先用 A/B 实验验证。",
                "Most categories hit the cap, so the model reads prices as low overall. That is "
                "only reliable near historical prices, so confirm with an A/B test first.",
            ),
            "warning",
        )
    else:
        verdict(
            tr("先做实验", "Test before rolling out"),
            tr(
                "这是基于历史数据的估算，全量调价前请先用 A/B 实验验证。",
                "These are estimates from history. Confirm with an A/B test before a full rollout.",
            ),
            "neutral",
        )
