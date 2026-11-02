from __future__ import annotations

import streamlit as st

from insightflow.config import DEFAULT_DB_PATH
from insightflow.currency import money, symbol
from insightflow.i18n import current_language, t, tr
from insightflow.live import gauge_strip
from insightflow.metrics import (
    cost_waterfall,
    kpi_summary,
    monthly_trend,
    previous_period,
    product_profitability,
)
from insightflow.pvm import price_volume_mix
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
)
from insightflow.viz import bridge, cash_waterfall, quadrant, show

COMPONENT_EN = {
    "商品毛额": "Gross sales",
    "折扣": "Discounts",
    "退款": "Refunds",
    "商品成本": "Product cost",
    "物流成本": "Shipping",
    "支付手续费": "Payment fees",
    "营销费用": "Marketing",
    "退货处理": "Return handling",
    "贡献利润": "Contribution profit",
}

def render() -> None:
    filters = sidebar_filters(DEFAULT_DB_PATH)
    code = currency_code()
    prefix = symbol(code)
    current = kpi_summary(DEFAULT_DB_PATH, filters)
    previous = kpi_summary(DEFAULT_DB_PATH, previous_period(filters))
    steps = price_volume_mix(DEFAULT_DB_PATH, filters, language=current_language())
    worst = steps.sort_values("impact").iloc[0]
    change = current["contribution_profit"] - previous["contribution_profit"]
    page_header(
        t("page.profit.title"),
        tr(
            f"贡献利润较上期变化 {money(change, code, short=True)}，"
            f"最大的拖累是{worst['label']}（{money(worst['impact'], code, short=True)}）。",
            f"Contribution profit moved by {money(change, code, short=True)}; the largest drag was "
            f"{worst['label']} ({money(worst['impact'], code, short=True)}).",
        ),
        meta=period_meta(filters),
    )

    recent = monthly_trend(DEFAULT_DB_PATH, filters.undated()).tail(12)

    def item(label: str, key: str, kind: str, up_is_good: bool = True) -> dict:
        value = current[key]
        display = (
            f"{value:.1%}"
            if kind == "percent"
            else money(value, code, decimals=2)
            if key == "profit_per_order"
            else money(value, code, short=True)
        )
        spark = recent[key].fillna(0).tolist() if key in recent.columns else None
        return gauge_item(
            label,
            value,
            kind,
            display,
            current=value,
            previous=previous[key],
            up_is_good=up_is_good,
            spark=spark,
            prefix=prefix,
        )

    gauge_strip(
        [
            item(tr("贡献利润", "Contribution profit"), "contribution_profit", "money"),
            item(tr("贡献利润率", "Contribution margin"), "contribution_margin", "percent"),
            item(tr("毛利率", "Gross margin"), "gross_margin", "percent"),
            item(tr("单均利润", "Profit per order"), "profit_per_order", "money"),
            item(tr("折扣率", "Discount rate"), "discount_rate", "percent", up_is_good=False),
            item(tr("退款", "Refunds"), "returns_value", "money", up_is_good=False),
        ],
        key="profit_gauges",
    )

    section_header(tr("钱去了哪里", "Where the money went"), tr("本期从毛额到贡献利润", "Gross sales to contribution profit"))
    waterfall = cost_waterfall(DEFAULT_DB_PATH, filters)
    waterfall["component"] = [tr(name, COMPONENT_EN[name]) for name in waterfall["component"]]
    show(
        cash_waterfall(waterfall, label="component", value="value", money_prefix=prefix),
        key="profit_waterfall",
    )
    table_view(waterfall.round(0))

    section_header(
        tr("利润为什么变了", "Why profit changed"),
        tr("价格、销量、结构和成本的完整拆解，逐项加总等于实际变化", "Every step adds up to the actual change"),
    )
    show(
        bridge(
            tr("上期利润", "Prior profit"),
            float(steps.attrs["start"]),
            steps.loc[steps["impact"].abs() >= 1, ["label", "impact"]],
            tr("本期利润", "This period"),
            float(steps.attrs["end"]),
            money_prefix=prefix,
        ),
        key="profit_bridge",
    )
    note(
        tr(
            f"未解释差额 {money(float(steps.attrs['unexplained']), code, decimals=2)}。"
            "销量规模按上期单位利润计，结构反映卖得多的商品变了，退货影响含退款、回收成本和处理费。",
            f"Unexplained: {money(float(steps.attrs['unexplained']), code, decimals=2)}. Volume uses "
            "last period's unit profit, mix reflects which products sold more, and returns include "
            "refunds, recovered cost and handling.",
        )
    )
    table_view(steps[["label", "impact"]].round(0))

    section_header(tr("商品利润地图", "Product profit map"), tr("横线和竖线是中位数", "Lines mark the medians"))
    products = product_profitability(DEFAULT_DB_PATH, filters, limit=150)
    if products.empty:
        note(tr("当前筛选条件下没有商品数据。", "No products under the current filters."))
        return
    show(
        quadrant(
            products,
            x="revenue",
            y="contribution_margin",
            size="orders",
            name="description",
            labels={"x": tr("净销售额", "Net revenue"), "y": tr("贡献利润率", "Contribution margin")},
            money_prefix=prefix,
        ),
        key="profit_quadrant",
    )
    subhead(tr("卖得多但赚得少的商品", "Selling well, earning little"))
    weak = products[
        (products["revenue"] >= products["revenue"].median())
        & (products["contribution_margin"] < products["contribution_margin"].median())
    ].sort_values("revenue", ascending=False)
    columns = {
        "description": tr("商品", "Product"),
        "category": tr("品类", "Category"),
        "revenue": tr("净销售额", "Net revenue"),
        "contribution_margin": tr("贡献利润率", "Contribution margin"),
        "discount_rate": tr("折扣率", "Discount rate"),
        "returns_value": tr("退款", "Refunds"),
    }
    st.dataframe(
        weak.head(30)[list(columns)].rename(columns=columns),
        hide_index=True,
        column_config={
            columns["revenue"]: st.column_config.NumberColumn(format="%,.0f"),
            columns["contribution_margin"]: st.column_config.NumberColumn(format="percent"),
            columns["discount_rate"]: st.column_config.NumberColumn(format="percent"),
            columns["returns_value"]: st.column_config.NumberColumn(format="%,.0f"),
        },
    )
