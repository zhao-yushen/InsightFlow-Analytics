from __future__ import annotations

import streamlit as st

from insightflow.basket import association_rules
from insightflow.config import DEFAULT_DB_PATH
from insightflow.currency import symbol
from insightflow.i18n import t, tr
from insightflow.metrics import product_profitability
from insightflow.ui import (
    currency_code,
    note,
    page_header,
    period_meta,
    section_header,
    sidebar_filters,
    subhead,
    table_view,
)
from insightflow.viz import pareto, quadrant, ranked_bars, show


def render() -> None:
    filters = sidebar_filters(DEFAULT_DB_PATH)
    code = currency_code()
    prefix = symbol(code)
    products = product_profitability(DEFAULT_DB_PATH, filters, limit=400)
    if products.empty:
        page_header(
            t("page.products.title"),
            tr("当前筛选条件下没有商品数据。", "No products under the current filters."),
            meta=period_meta(filters),
        )
        return
    total = max(float(products["revenue"].clip(lower=0).sum()), 1.0)
    head_count = max(1, round(len(products) * 0.2))
    head_share = float(products["revenue"].clip(lower=0).nlargest(head_count).sum()) / total
    page_header(
        t("page.products.title"),
        tr(
            f"前 20% 的商品（{head_count} 个）贡献了 {head_share:.0%} 的净销售额。",
            f"The top 20% of products ({head_count}) bring {head_share:.0%} of net revenue.",
        ),
        meta=period_meta(filters),
    )

    section_header(tr("收入集中度", "Revenue concentration"))
    left, right = st.columns(2, gap="large")
    with left:
        subhead(tr("累计收入曲线", "Cumulative revenue"))
        show(
            pareto(
                products,
                value="revenue",
                labels={"x": tr("商品占比", "Share of products"), "y": tr("收入占比", "Share of revenue")},
            ),
            key="products_pareto",
        )
    with right:
        subhead(tr("净销售额前十", "Top ten by net revenue"))
        show(
            ranked_bars(products.head(10), label="description", value="revenue", money_prefix=prefix),
            key="products_top",
        )

    section_header(tr("商品效率地图", "Product efficiency map"), tr("横线和竖线是中位数", "Lines mark the medians"))
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
        key="products_quadrant",
    )
    table_view(products.round(3))

    section_header(tr("连带购买", "Bought together"), tr("提升度越高，越不是巧合", "Higher lift means less coincidence"))
    level = st.segmented_control(
        tr("分析层级", "Level"),
        ["stock_code", "category"],
        default="stock_code",
        format_func={"stock_code": tr("商品", "Products"), "category": tr("品类", "Categories")}.get,
        label_visibility="collapsed",
        key="products_basket_level",
    )
    rules = association_rules(DEFAULT_DB_PATH, filters, level=level or "stock_code", limit=30)
    if rules.empty:
        note(
            tr(
                "当前范围的订单太少，还找不到可靠组合。至少需要 8 笔共同购买。",
                "Too few orders for reliable pairs. At least eight joint orders are needed.",
            )
        )
        return
    # A pair appears once per direction; keep the stronger reading of each.
    pairs = rules.assign(
        pair=[" | ".join(sorted(p)) for p in zip(rules["antecedent"], rules["consequent"], strict=True)]
    ).drop_duplicates("pair")
    top = pairs.iloc[0]
    note(
        tr(
            f"最强组合：买 {top['antecedent_name']} 的订单有 {top['confidence']:.0%} 也买了 "
            f"{top['consequent_name']}，是随机水平的 {top['lift']:.1f} 倍。",
            f"Strongest pair: {top['confidence']:.0%} of orders with {top['antecedent_name']} also "
            f"include {top['consequent_name']}, {top['lift']:.1f}× chance.",
        )
    )
    columns = {
        "antecedent_name": tr("买了", "Bought"),
        "consequent_name": tr("也买了", "Also bought"),
        "pair_orders": tr("共同订单", "Joint orders"),
        "confidence": tr("连带率", "Confidence"),
        "lift": tr("提升度", "Lift"),
    }
    st.dataframe(
        pairs.head(15)[list(columns)].rename(columns=columns),
        hide_index=True,
        column_config={
            columns["confidence"]: st.column_config.NumberColumn(format="percent"),
            columns["lift"]: st.column_config.NumberColumn(format="%.1f"),
        },
    )
