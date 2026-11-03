from __future__ import annotations

import pandas as pd
import streamlit as st

from insightflow.config import DEFAULT_DB_PATH
from insightflow.currency import money, symbol
from insightflow.i18n import t, tr
from insightflow.live import gauge_strip
from insightflow.metrics import inventory_kpis
from insightflow.supply import inventory_policy, policy_matrix
from insightflow.ui import (
    currency_code,
    gauge_item,
    note,
    page_header,
    section_header,
    sidebar_filters,
    subhead,
    trust_sentence,
)
from insightflow.viz import heatmap, ranked_bars, show


def _demand_view(policy: pd.DataFrame) -> None:
    """Without stock levels the ledger still shows what sells and how steadily."""
    active = policy[policy["daily_demand"] > 0]
    page_header(
        t("page.inventory.title"),
        tr(
            "这份数据没有库存字段，所以这里只分析需求，不判断缺货。导入时映射库存字段后会显示补货清单。",
            "This data has no stock levels, so this page reads demand and makes no stockout "
            "calls. Map a stock field on import to get an order list.",
        ),
        meta=trust_sentence(DEFAULT_DB_PATH),
    )
    gauge_strip(
        [
            gauge_item(tr("近 90 天有需求的商品", "Products with demand"), len(active), "count", f"{len(active):,}", note_text=tr("净需求大于零", "Net demand above zero")),
            gauge_item(tr("A 类商品", "A items"), int((active["abc_class"] == "A").sum()), "count", f"{int((active['abc_class'] == 'A').sum()):,}", note_text=tr("贡献 80% 收入", "Bring 80% of revenue")),
            gauge_item(tr("需求稳定", "Steady demand"), int((active["xyz_class"] == "X").sum()), "count", f"{int((active['xyz_class'] == 'X').sum()):,}", note_text=tr("X 类", "X class")),
            gauge_item(tr("需求波动大", "Erratic demand"), int((active["xyz_class"] == "Z").sum()), "count", f"{int((active['xyz_class'] == 'Z').sum()):,}", note_text=tr("Z 类", "Z class")),
        ],
        key="inventory_demand_gauges",
    )
    section_header(tr("需求结构", "Demand structure"), tr("根据近 90 天净需求计算，已扣除退货", "Last 90 days of net demand, after returns"))
    left, right = st.columns([1, 1.25], gap="large")
    with left:
        subhead(tr("收入分布（ABC-XYZ）", "Revenue by class (ABC-XYZ)"))
        show(
            heatmap(
                policy_matrix(policy),
                x_label=tr("需求稳定性：X 稳定，Z 波动", "Demand: X steady, Z erratic"),
                y_label=tr("价值：A 最高", "Value: A highest"),
                percent=False,
                height=320,
            ),
            key="inventory_matrix",
        )
    with right:
        subhead(tr("日均需求最高的商品", "Highest daily demand"))
        show(
            ranked_bars(
                policy.sort_values("daily_demand", ascending=False).head(10),
                label="description",
                value="daily_demand",
            ),
            key="inventory_top_demand",
        )


def render() -> None:
    sidebar_filters(DEFAULT_DB_PATH)
    code = currency_code()
    prefix = symbol(code)
    kpi = inventory_kpis(DEFAULT_DB_PATH)
    service = st.session_state.get("inventory_service", 95)
    policy = inventory_policy(DEFAULT_DB_PATH, service_level=service / 100)
    if not policy.empty and policy["inventory_on_hand"].isna().all():
        _demand_view(policy)
        return
    risk = float(policy["margin_at_risk"].sum()) if not policy.empty else 0.0
    urgent = policy[policy["recommended_order"] > 0]
    page_header(
        t("page.inventory.title"),
        tr(
            f"{len(urgent)} 个商品已低于补货线，到货前预计损失利润 {money(risk, code, short=True)}。",
            f"{len(urgent)} products are below their reorder level, risking "
            f"{money(risk, code, short=True)} of profit before stock arrives.",
        ),
        meta=trust_sentence(DEFAULT_DB_PATH),
    )

    gauge_strip(
        [
            gauge_item(tr("在售商品", "Active products"), kpi["sku_count"], "count", f"{kpi['sku_count']:,.0f}", note_text=""),
            gauge_item(tr("需补货", "To reorder"), len(urgent), "count", f"{len(urgent):,}", note_text=tr("低于补货线", "Below reorder level")),
            gauge_item(tr("库存积压", "Overstocked"), kpi["overstock_skus"], "count", f"{kpi['overstock_skus']:,.0f}", note_text=tr("超过 120 天销量", "Over 120 days of cover")),
            gauge_item(
                tr("库存价值", "Inventory value"),
                kpi["inventory_value"],
                "money",
                money(kpi["inventory_value"], code, short=True),
                prefix=prefix,
                note_text="",
            ),
            gauge_item(tr("平均可售天数", "Average cover"), kpi["avg_days_of_supply"], "count", f"{kpi['avg_days_of_supply']:.0f}", note_text=tr("天", "days")),
        ],
        key="inventory_gauges",
    )

    section_header(tr("补货策略", "Replenishment policy"), tr("根据近 90 天实际需求计算", "Calculated from the last 90 days of demand"))
    st.slider(
        tr("目标服务水平", "Target service level"),
        80,
        99,
        step=1,
        format="%d%%",
        key="inventory_service",
        value=service,
        help=tr(
            "到货前不缺货的概率。越高，需要的安全库存越多。",
            "The chance of not running out before stock arrives. Higher means more safety stock.",
        ),
    )
    left, right = st.columns([1, 1.25], gap="large")
    with left:
        subhead(tr("收入分布（ABC-XYZ）", "Revenue by class (ABC-XYZ)"))
        show(
            heatmap(
                policy_matrix(policy),
                x_label=tr("需求稳定性：X 稳定，Z 波动", "Demand: X steady, Z erratic"),
                y_label=tr("价值：A 最高", "Value: A highest"),
                percent=False,
                height=320,
            ),
            key="inventory_matrix",
        )
        note(
            tr(
                "A 类商品贡献 80% 收入，Z 类需求波动最大。AX 适合自动补货，AZ 需要人工盯。",
                "A items bring 80% of revenue and Z items swing most. AX can reorder "
                "automatically; AZ needs a person watching.",
            )
        )
    with right:
        subhead(tr("缺货损失最大的商品", "Largest stockout exposure"))
        exposed = policy[policy["margin_at_risk"] > 0].head(10)
        if exposed.empty:
            note(tr("当前没有预计缺货的商品。", "No product is expected to run out."))
        else:
            show(
                ranked_bars(
                    exposed,
                    label="stock_code",
                    value="margin_at_risk",
                    money_prefix=prefix,
                    color="#FF7B6B",
                ),
                key="inventory_exposure",
            )

    subhead(tr("补货清单", "Order list"))
    columns = {
        "stock_code": tr("商品", "Product"),
        "policy_class": tr("分类", "Class"),
        "inventory_on_hand": tr("现有库存", "On hand"),
        "daily_demand": tr("日均需求", "Daily demand"),
        "supplier_lead_days": tr("交期（天）", "Lead time (days)"),
        "safety_stock": tr("安全库存", "Safety stock"),
        "reorder_level": tr("补货线", "Reorder level"),
        "recommended_order": tr("建议订购", "Order now"),
        "stockout_date": tr("预计缺货日", "Runs out on"),
        "margin_at_risk": tr("风险利润", "Profit at risk"),
    }
    orders = policy[policy["recommended_order"] > 0].sort_values("margin_at_risk", ascending=False)
    st.dataframe(
        orders[list(columns)].rename(columns=columns),
        hide_index=True,
        column_config={
            columns["daily_demand"]: st.column_config.NumberColumn(format="%.1f"),
            columns["margin_at_risk"]: st.column_config.NumberColumn(format="%,.0f"),
        },
    )
    st.download_button(
        tr("下载补货清单", "Download order list"),
        orders[list(columns)].rename(columns=columns).to_csv(index=False).encode("utf-8-sig"),
        file_name="insightflow_order_list.csv",
        mime="text/csv",
    )
    note(
        tr(
            "安全库存 = 服务水平系数 × √(交期 × 需求方差 + 需求² × 交期方差)，交期波动按 20% 估计。",
            "Safety stock = service factor × √(lead time × demand variance + demand² × lead-time "
            "variance), assuming lead times vary by 20%.",
        )
    )
