from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .diagnostics import dimension_change, profit_driver_decomposition
from .metrics import (
    FilterSpec,
    customer_value_risk,
    inventory_status,
    kpi_summary,
    previous_period,
    product_profitability,
    quality_dimensions,
    target_status,
)


@dataclass
class QueryAnswer:
    query_id: str
    title: str
    answer: str
    data: pd.DataFrame
    methodology: str


SUPPORTED_QUESTIONS = [
    "为什么利润下降？",
    "哪些商品销售额高但利润率低？",
    "哪些国家对销售变化影响最大？",
    "哪些高价值客户存在流失风险？",
    "哪些商品需要补货？",
    "哪些经营目标没有完成？",
    "当前数据质量是否可信？",
]
QUESTION_EN = {
    "为什么利润下降？": "Why did profit decline?",
    "哪些商品销售额高但利润率低？": "Which products have high revenue but low margins?",
    "哪些国家对销售变化影响最大？": "Which countries drove the largest sales changes?",
    "哪些高价值客户存在流失风险？": "Which high-value customers are at risk of churning?",
    "哪些商品需要补货？": "Which products need replenishment?",
    "哪些经营目标没有完成？": "Which operating targets are off track?",
    "当前数据质量是否可信？": "Can the current data quality be trusted?",
}


def question_label(question: str, language: str = "zh-CN") -> str:
    return question if language == "zh-CN" else QUESTION_EN.get(question, question)


def _classify(question: str) -> str:
    text = question.lower()
    if any(k in text for k in ("利润", "盈利", "毛利", "profit", "margin")) and any(
        k in text for k in ("下降", "原因", "为什么", "decline", "drop", "why", "reason")
    ):
        return "profit_driver"
    if any(k in text for k in ("商品", "sku", "product")) and any(
        k in text for k in ("低利润", "低毛利", "利润率", "low margin", "low profit")
    ):
        return "low_margin_products"
    if any(k in text for k in ("国家", "地区", "country", "region", "market")):
        return "country_driver"
    if any(
        k in text
        for k in ("流失", "召回", "高价值客户", "churn", "win-back", "high-value customer")
    ):
        return "churn_risk"
    if any(k in text for k in ("库存", "补货", "缺货", "inventory", "reorder", "stockout")):
        return "inventory_risk"
    if any(k in text for k in ("目标", "完成率", "达成", "target", "goal", "off track")):
        return "target_risk"
    if any(
        k in text
        for k in (
            "数据质量",
            "可信",
            "缺失",
            "重复",
            "data quality",
            "trust",
            "missing",
            "duplicate",
        )
    ):
        return "data_quality"
    return "profit_driver"


def answer_business_question(
    db_path: str | Path,
    filters: FilterSpec,
    question: str,
    *,
    language: str = "zh-CN",
) -> QueryAnswer:
    intent = _classify(question)
    english = language != "zh-CN"
    if intent == "profit_driver":
        current = kpi_summary(db_path, filters)
        previous = kpi_summary(db_path, previous_period(filters))
        data = profit_driver_decomposition(current, previous)
        worst = data.iloc[0]
        delta = current["contribution_profit"] - previous["contribution_profit"]
        answer = (
            f"Contribution profit changed by £{delta:,.0f} versus the previous period. "
            f"The largest negative driver was {worst['driver']}, with an estimated impact of "
            f"£{worst['profit_contribution']:,.0f}. Review product cost, discounting, and variable operating expenses first."
            if english
            else f"本期贡献利润较上期变化 £{delta:,.0f}。最大负向因素是“{worst['driver']}”，"
            f"影响约 £{worst['profit_contribution']:,.0f}。应先检查商品成本、折扣和可变经营费用。"
        )
        return QueryAnswer(
            "profit_driver_v1",
            "Contribution-profit drivers" if english else "贡献利润变化原因",
            answer,
            data,
            "Exact profit bridge: net-revenue effect + gross-margin effect + variable-cost effect."
            if english
            else "使用精确利润桥接：净销售额影响 + 毛利率影响 + 可变经营成本影响。",
        )
    if intent == "low_margin_products":
        data = product_profitability(db_path, filters, limit=100)
        revenue_cut = data["revenue"].median() if not data.empty else 0
        data = data[(data["revenue"] >= revenue_cut) & (data["contribution_margin"] < 0.12)].head(
            20
        )
        answer = (
            f"Identified {len(data)} high-revenue products with contribution margins below 12%. "
            "Review discounts, procurement costs, and shipping costs before expanding volume."
            if english
            else f"识别到 {len(data)} 个高收入但贡献利润率低于12%的商品。"
            "建议优先检查折扣、采购成本和物流成本，而不是直接扩大销量。"
        )
        return QueryAnswer(
            "low_margin_products_v1",
            "High-revenue, low-margin products" if english else "高收入低利润商品",
            answer,
            data,
            "Revenue above the median and contribution margin below 12%."
            if english
            else "按照收入高于中位数且贡献利润率低于12%筛选。",
        )
    if intent == "country_driver":
        data = dimension_change(db_path, filters, "country", limit=10)
        top = data.iloc[0] if not data.empty else None
        answer = (
            (
                f"The largest market driver was {top['country']}: net revenue changed by about "
                f"£{top['change']:,.0f} and contribution profit by about £{top['profit_change']:,.0f}."
                if english
                else f"影响最大的地区是 {top['country']}，净销售额变化约 £{top['change']:,.0f}，"
                f"贡献利润变化约 £{top['profit_change']:,.0f}。"
            )
            if top is not None
            else (
                "There is not enough data under the current filters."
                if english
                else "当前筛选条件下没有足够数据。"
            )
        )
        return QueryAnswer(
            "country_driver_v1",
            "Country and region contributions" if english else "国家/地区变化贡献",
            answer,
            data,
            "Compare equal-length periods and rank by absolute net-revenue change."
            if english
            else "比较等长前后期间，并按净销售额绝对变化排序。",
        )
    if intent == "churn_risk":
        data = customer_value_risk(db_path, filters).head(20)
        risk_value = float(data["expected_profit_at_risk"].sum()) if not data.empty else 0
        answer = (
            f"The top 20 at-risk customers represent about £{risk_value:,.0f} in expected profit risk. "
            "Prioritize customers with both high CLV and high churn risk."
            if english
            else f"前20名风险客户预计涉及利润风险约 £{risk_value:,.0f}，应优先处理高CLV且流失风险高的客户。"
        )
        return QueryAnswer(
            "customer_churn_v1",
            "High-value customer churn risk" if english else "高价值客户流失风险",
            answer,
            data,
            "Explainable score combining recency, frequency, discount dependence, and profit contribution."
            if english
            else "综合最近购买时间、购买频次、折扣依赖和利润贡献形成可解释风险分数。",
        )
    if intent == "inventory_risk":
        data = inventory_status(db_path, "Reorder").head(30)
        count = len(inventory_status(db_path, "Reorder"))
        answer = (
            f"{count} SKUs meet the replenishment-alert condition."
            if english
            else f"共有 {count} 个SKU达到补货预警条件。"
        )
        return QueryAnswer(
            "inventory_reorder_v1",
            "Replenishment-risk SKUs" if english else "补货风险SKU",
            answer,
            data,
            "Alert when days of supply are below supplier lead time plus a seven-day safety buffer."
            if english
            else "当库存可售天数低于供应商提前期加7天安全期时触发预警。",
        )
    if intent == "target_risk":
        month = str(pd.Timestamp(filters.end_date).to_period("M"))
        data = target_status(db_path, month)
        off = data[data["status"] != "On Track"] if not data.empty else data
        answer = (
            f"{len(off)} metrics are at risk or off track in {month}."
            if english
            else f"{month}共有 {len(off)} 项指标处于风险或未达标状态。"
        )
        return QueryAnswer(
            "target_status_v1",
            "Operating target status" if english else "经营目标完成状态",
            answer,
            off,
            "Calculate attainment from actual versus target with metric direction applied."
            if english
            else "将实际值与目标值按指标方向计算完成度。",
        )
    data = quality_dimensions(db_path)
    score = float(data["score_100"].mean()) if not data.empty else 0
    lowest = data.sort_values("score_100").iloc[0] if not data.empty else None
    answer = (
        (
            f"The composite data-quality score is {score:.1f}/100. The lowest dimension is "
            f"{lowest['dimension']} ({lowest['score_100']:.1f})."
            if english
            else f"综合数据质量得分为 {score:.1f}/100。最低维度是{lowest['dimension']}（{lowest['score_100']:.1f}分）。"
        )
        if lowest is not None
        else ("No data-quality records are available." if english else "没有数据质量记录。")
    )
    return QueryAnswer(
        "data_quality_v1",
        "Data-quality trust" if english else "数据质量可信度",
        answer,
        data,
        "Score completeness, uniqueness, validity, consistency, and temporal coverage."
        if english
        else "从完整性、唯一性、有效性、一致性和时间覆盖五个维度评分。",
    )
