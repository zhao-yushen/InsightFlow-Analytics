from __future__ import annotations

from dataclasses import replace

import pandas as pd
import streamlit as st

from insightflow.config import DEFAULT_DB_PATH
from insightflow.currency import money, symbol
from insightflow.geography import country_label, region_label
from insightflow.i18n import current_language, t, tr
from insightflow.live import gauge_strip, market_globe
from insightflow.metrics import (
    FilterSpec,
    dimension_performance,
    kpi_summary,
    market_performance,
    previous_period,
)
from insightflow.narrative import globe_payload
from insightflow.ui import (
    currency_code,
    gauge_item,
    note,
    page_header,
    period_meta,
    section_header,
    sidebar_filters,
    subhead,
)
from insightflow.viz import ranked_bars, show

SELECTED = "market_selected"


def _story(markets: pd.DataFrame, labels: pd.Series, code: str) -> str:
    ranked = markets.sort_values("revenue", ascending=False)
    top = ranked.iloc[0]
    three = float(ranked["revenue_share"].head(3).sum())
    best = markets[markets["revenue_share"] >= 0.01].sort_values("contribution_margin").iloc[-1]
    return tr(
        f"{labels[top['country']]}贡献 {top['revenue_share']:.0%} 的净销售额，前三个市场合计 {three:.0%}。"
        f"规模较大的市场里，{labels[best['country']]}的贡献利润率最高（{best['contribution_margin']:.1%}）。",
        f"{labels[top['country']]} brings {top['revenue_share']:.0%} of net revenue and the top three "
        f"markets {three:.0%}. Among sizeable markets, {labels[best['country']]} earns the best "
        f"contribution margin at {best['contribution_margin']:.1%}.",
    )


def _market_detail(filters: FilterSpec, country: str, label: str, code: str) -> None:
    scoped = replace(filters, countries=(country,), regions=())
    current = kpi_summary(DEFAULT_DB_PATH, scoped)
    previous = kpi_summary(DEFAULT_DB_PATH, previous_period(scoped))
    subhead(label)
    prefix = symbol(code)
    gauge_strip(
        [
            gauge_item(
                tr("净销售额", "Net revenue"),
                current["revenue"],
                "money",
                money(current["revenue"], code, short=True),
                current=current["revenue"],
                previous=previous["revenue"],
                prefix=prefix,
            ),
            gauge_item(
                tr("贡献利润率", "Contribution margin"),
                current["contribution_margin"],
                "percent",
                f"{current['contribution_margin']:.1%}",
                current=current["contribution_margin"],
                previous=previous["contribution_margin"],
            ),
            gauge_item(
                tr("退货取消率", "Return rate"),
                current["cancellation_rate"],
                "percent",
                f"{current['cancellation_rate']:.1%}",
                current=current["cancellation_rate"],
                previous=previous["cancellation_rate"],
                up_is_good=False,
            ),
        ],
        key=f"market_detail_{country}",
    )
    categories = dimension_performance(DEFAULT_DB_PATH, scoped, "category", limit=6)
    if not categories.empty:
        show(
            ranked_bars(categories, label="category", value="revenue", money_prefix=prefix),
            key=f"market_categories_{country}",
        )


def render() -> None:
    filters = sidebar_filters(DEFAULT_DB_PATH)
    code = currency_code()
    prefix = symbol(code)
    language = current_language()
    markets = market_performance(DEFAULT_DB_PATH, filters)
    if markets.empty:
        page_header(
            t("page.markets.title"),
            tr("当前筛选条件下没有销售。", "No sales under the current filters."),
            meta=period_meta(filters),
        )
        return
    labels = pd.Series({name: country_label(name, language) for name in markets["country"]})
    page_header(t("page.markets.title"), _story(markets, labels, code), meta=period_meta(filters))

    left, right = st.columns([1.35, 1], gap="large")
    with left:
        clicked = market_globe(
            globe_payload(markets, labels, code, st.session_state.get(SELECTED)),
            key="market_globe",
        )
        if clicked:
            st.session_state[SELECTED] = clicked
        note(
            tr(
                "气泡大小代表净销售额，青色高于整体利润率，珊瑚色低于整体。拖动旋转，点击市场查看详情。"
                "用键盘时，上下方向键切换市场，回车查看详情。",
                "Bubble size is net revenue. Aqua earns above the overall margin, coral below. "
                "Drag to rotate; click a market for detail. On a keyboard, the up and down arrows "
                "move between markets and Enter opens one.",
            )
        )
        unplaced = markets[markets["lat"].isna()]
        if not unplaced.empty:
            names = "、".join(labels[name] for name in unplaced["country"])
            share = float(unplaced["revenue_share"].sum())
            note(
                tr(
                    f"{names}没有地理位置，未显示在地球仪上，占净销售额 {share:.1%}。",
                    f"{', '.join(labels[name] for name in unplaced['country'])} has no location and "
                    f"is left off the globe, {share:.1%} of net revenue.",
                )
            )
    with right:
        selected = st.session_state.get(SELECTED)
        if selected in set(markets["country"]):
            _market_detail(filters, selected, labels[selected], code)
            if st.button(tr("查看全部区域", "Back to all regions"), key="market_clear"):
                st.session_state.pop(SELECTED, None)
                st.rerun()
        else:
            subhead(tr("各区域净销售额", "Net revenue by region"))
            regions = dimension_performance(DEFAULT_DB_PATH, filters, "market_region", limit=12)
            regions["label"] = regions["market_region"].map(lambda v: region_label(v, language))
            show(
                ranked_bars(regions, label="label", value="revenue", money_prefix=prefix),
                key="market_regions",
            )

    section_header(
        tr("市场排名", "Market ranking"),
        tr("按净销售额排序，已扣除退货", "Sorted by net revenue after returns"),
    )
    shown = markets.sort_values("revenue", ascending=False).copy()
    shown["name"] = shown["country"].map(labels)
    shown["region"] = shown["market_region"].map(lambda v: region_label(v, language))
    columns = {
        "name": tr("市场", "Market"),
        "region": tr("区域", "Region"),
        "revenue": tr(f"净销售额（{code}）", f"Net revenue ({code})"),
        "revenue_share": tr("占比", "Share"),
        "contribution_margin": tr("贡献利润率", "Contribution margin"),
        "cancellation_rate": tr("退货取消率", "Return rate"),
        "orders": tr("订单", "Orders"),
        "customers": tr("客户", "Customers"),
    }
    frame = shown[list(columns)].rename(columns=columns)
    st.dataframe(
        frame,
        hide_index=True,
        column_config={
            columns["revenue"]: st.column_config.NumberColumn(format="%,.0f"),
            columns["revenue_share"]: st.column_config.ProgressColumn(
                min_value=0.0, max_value=float(shown["revenue_share"].max()), format="percent"
            ),
            columns["contribution_margin"]: st.column_config.NumberColumn(format="percent"),
            columns["cancellation_rate"]: st.column_config.NumberColumn(format="percent"),
        },
    )
