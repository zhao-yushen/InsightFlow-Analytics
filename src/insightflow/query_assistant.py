from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .basket import association_rules
from .currency import money, warehouse_currency
from .diagnostics import dimension_change, profit_driver_decomposition, revenue_driver_decomposition
from .elasticity import category_price_moves
from .forecasting import forecast_metric
from .metrics import (
    FilterSpec,
    customer_value_risk,
    dimension_performance,
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
    supported: bool = True
    suggestions: list[str] = field(default_factory=list)


SUPPORTED_QUESTIONS = [
    "为什么利润下降？",
    "为什么收入变化了？",
    "哪些商品销售额高但利润率低？",
    "哪些国家对销售变化影响最大？",
    "哪个渠道的退货最多？",
    "哪些高价值客户存在流失风险？",
    "哪些商品需要补货？",
    "哪些经营目标没有完成？",
    "未来三个月收入预测是多少？",
    "哪些品类应该调价？",
    "哪些商品适合搭配销售？",
    "当前数据质量是否可信？",
]
QUESTION_EN = {
    "为什么利润下降？": "Why did profit decline?",
    "为什么收入变化了？": "Why did revenue change?",
    "哪些商品销售额高但利润率低？": "Which products have high revenue but low margins?",
    "哪些国家对销售变化影响最大？": "Which countries drove the largest sales changes?",
    "哪个渠道的退货最多？": "Which channel has the most returns?",
    "哪些高价值客户存在流失风险？": "Which high-value customers are at risk of churning?",
    "哪些商品需要补货？": "Which products need replenishment?",
    "哪些经营目标没有完成？": "Which operating targets are off track?",
    "未来三个月收入预测是多少？": "What is the revenue forecast for the next three months?",
    "哪些品类应该调价？": "Which categories should change price?",
    "哪些商品适合搭配销售？": "Which products sell well together?",
    "当前数据质量是否可信？": "Can the current data quality be trusted?",
}

# Checked in order: the first rule whose pattern matches wins, so narrow questions come first.
INTENT_RULES = (
    ("returns", r"退货|退款|取消|返品|return|refund|cancel"),
    ("bundles", r"搭配|一起买|捆绑|连带|bundle|basket|cross.?sell|sold together|sell well together"),
    ("price_moves", r"调价|定价|提价|降价|涨价|price change|pricing|reprice|change price"),
    ("forecast", r"预测|未来|下个?月|下季度|forecast|outlook|next (month|quarter|three)"),
    (
        "revenue_driver",
        r"(收入|销售额|营收).*(为什么|原因|下降|变化|驱动)|(为什么|原因).*(收入|销售额|营收)"
        r"|(revenue|sales).*(why|driver|change|drop|decline)|why.*(revenue|sales)",
    ),
    (
        "profit_driver",
        r"(利润|盈利|毛利).*(为什么|原因|下降|变化)|(为什么|原因).*(利润|盈利|毛利)"
        r"|(profit|margin).*(why|reason|drop|decline)|why.*(profit|margin)",
    ),
    (
        "low_margin_products",
        r"(商品|产品|sku|product).*(低利润|低毛利|利润率|low margin|low profit)",
    ),
    ("country_driver", r"国家|地区|市场|country|region|market"),
    ("channel_mix", r"渠道|平台|channel|platform"),
    ("category_mix", r"品类|类目|category"),
    ("churn_risk", r"流失|召回|高价值客户|churn|win.?back|high.?value customer"),
    ("inventory_risk", r"库存|补货|缺货|inventory|reorder|replenish|stockout"),
    ("target_risk", r"目标|完成率|达成|target|goal|off track"),
    ("data_quality", r"数据质量|可信|缺失|重复|data quality|trust|missing|duplicate"),
    ("top_products", r"畅销|卖得最好|top product|best.?sell"),
)


def question_label(question: str, language: str = "zh-CN") -> str:
    return question if language == "zh-CN" else QUESTION_EN.get(question, question)


def _classify(question: str) -> str:
    text = question.lower()
    for intent, pattern in INTENT_RULES:
        if re.search(pattern, text):
            return intent
    return "unsupported"


def answer_business_question(
    db_path: str | Path,
    filters: FilterSpec,
    question: str,
    *,
    language: str = "zh-CN",
) -> QueryAnswer:
    intent = _classify(question)
    english = language != "zh-CN"
    code = warehouse_currency(db_path)

    def say(zh: str, en: str) -> str:
        return en if english else zh

    def amount(value: float) -> str:
        return money(value, code)

    if intent == "unsupported":
        return QueryAnswer(
            "unsupported",
            say("暂时答不了这个问题", "This question is outside what I can answer"),
            say(
                "这个问题没有对应的已审核指标，所以不作回答，以免给出不可核对的结论。下面是能回答的问题。",
                "No governed metric covers this question, so it stays unanswered rather than "
                "receiving a result nobody can verify. These are the questions I can answer.",
            ),
            pd.DataFrame(),
            say("只有匹配到已审核查询模板的问题才会作答。", "Only governed query templates answer."),
            supported=False,
            suggestions=[question_label(item, language) for item in SUPPORTED_QUESTIONS],
        )

    if intent == "profit_driver":
        current = kpi_summary(db_path, filters)
        previous = kpi_summary(db_path, previous_period(filters))
        data = profit_driver_decomposition(current, previous, language=language)
        worst = data.iloc[0]
        delta = current["contribution_profit"] - previous["contribution_profit"]
        return QueryAnswer(
            "profit_driver_v2",
            say("贡献利润变化原因", "Contribution-profit drivers"),
            say(
                f"本期贡献利润较上期变化 {amount(delta)}。最大负向因素是“{worst['driver']}”，"
                f"影响约 {amount(worst['profit_contribution'])}。应先检查商品成本、折扣和可变经营费用。",
                f"Contribution profit changed by {amount(delta)} versus the previous period. "
                f"The largest negative driver was {worst['driver']}, with an estimated impact of "
                f"{amount(worst['profit_contribution'])}. Review product cost, discounting, and "
                "variable operating expenses first.",
            ),
            data,
            say(
                "使用精确利润桥接：净销售额影响 + 毛利率影响 + 可变经营成本影响。",
                "Exact profit bridge: net-revenue effect + gross-margin effect + variable-cost effect.",
            ),
        )

    if intent == "revenue_driver":
        current = kpi_summary(db_path, filters)
        previous = kpi_summary(db_path, previous_period(filters))
        data = revenue_driver_decomposition(current, previous, language=language)
        worst = data.iloc[0]
        delta = current["revenue"] - previous["revenue"]
        return QueryAnswer(
            "revenue_driver_v1",
            say("收入变化驱动", "Revenue change drivers"),
            say(
                f"本期净销售额较上期变化 {amount(delta)}。影响最负的因素是“{worst['driver']}”，"
                f"约 {amount(worst['revenue_contribution'])}。",
                f"Net revenue changed by {amount(delta)}. The weakest driver was {worst['driver']}, "
                f"about {amount(worst['revenue_contribution'])}.",
            ),
            data,
            say(
                "用 Shapley 方法把收入精确拆分为活跃客户、购买频次和客单价。",
                "Exact Shapley split of revenue into customers, frequency and order value.",
            ),
        )

    if intent == "returns":
        text = question.lower()
        dimension = (
            "country"
            if re.search(r"国家|地区|市场|country|market", text)
            else "category"
            if re.search(r"品类|类目|category", text)
            else "channel"
        )
        data = dimension_performance(db_path, filters, dimension, limit=50)
        data = data.loc[data["orders"] > 0].sort_values("returns_value", ascending=False)
        if data.empty or float(data["returns_value"].sum()) == 0:
            return QueryAnswer(
                "returns_by_dimension_v1",
                say("退货分布", "Returns breakdown"),
                say("当前筛选范围内没有退货记录。", "No returns under the current filters."),
                data,
                say("汇总销售对冲记录。", "Sums reversal lines."),
            )
        top = data.iloc[0]
        share = float(top["returns_value"]) / float(data["returns_value"].sum())
        shown = data[[dimension, "returns_value", "cancelled_orders", "cancellation_rate", "orders"]]
        return QueryAnswer(
            "returns_by_dimension_v1",
            say("退货分布", "Returns breakdown"),
            say(
                f"退款最多的是 {top[dimension]}：{amount(top['returns_value'])}，"
                f"占全部退款的 {share:.0%}，退货取消率 {top['cancellation_rate']:.1%}。",
                f"{top[dimension]} has the most refunds at {amount(top['returns_value'])}, "
                f"{share:.0%} of all refunds, with a {top['cancellation_rate']:.1%} return rate.",
            ),
            shown,
            say(
                "按退款金额排序；退货取消率 = 退货单数 ÷ 销售订单数。",
                "Ranked by refund value; return rate = return orders ÷ sale orders.",
            ),
        )

    if intent == "forecast":
        result = forecast_metric(db_path, "revenue", horizon=3, filters=filters.undated())
        data = result.forecast
        total = float(data["forecast"].sum())
        return QueryAnswer(
            "forecast_v2",
            say("未来三个月净销售额预测", "Three-month net revenue forecast"),
            say(
                f"未来三个月净销售额预计合计 {amount(total)}。"
                f"回测选出的模型是 {result.selected_model}。",
                f"Net revenue over the next three months is expected to total {amount(total)}. "
                f"Backtesting selected {result.selected_model}.",
            ),
            data,
            say(
                "多个时序模型滚动回测后按 WAPE 选优，区间来自回测误差。",
                "Rolling backtests pick the model by WAPE; intervals come from backtest error.",
            ),
        )

    if intent == "price_moves":
        data = category_price_moves(db_path, filters)
        if data.empty:
            return QueryAnswer(
                "price_moves_v1",
                say("品类调价建议", "Category price moves"),
                say("当前范围的数据不足以估算价格弹性。", "Not enough data to estimate elasticity."),
                data,
                say("需要足够的价格波动。", "Requires observed price variation."),
            )
        best = data.iloc[0]
        shown = data[
            [
                "category",
                "elasticity",
                "basis",
                "recommended_move",
                "expected_profit_change",
                "expected_revenue_change",
            ]
        ]
        return QueryAnswer(
            "price_moves_v1",
            say("品类调价建议", "Category price moves"),
            say(
                f"调价潜力最大的是 {best['category']}：建议价格变动 {best['recommended_move']:+.1%}，"
                f"预计贡献利润变化 {amount(best['expected_profit_change'])}。先用实验验证再全量执行。",
                f"{best['category']} has the largest pricing opportunity: a "
                f"{best['recommended_move']:+.1%} move for an expected "
                f"{amount(best['expected_profit_change'])} profit change. Test before rolling out.",
            ),
            shown,
            say(
                "弹性由周度量价回归估计并向先验收缩，单次调价上限 ±10%。",
                "Elasticity comes from weekly regressions shrunk to a prior; moves are capped at ±10%.",
            ),
        )

    if intent == "bundles":
        data = association_rules(db_path, filters, limit=15)
        if data.empty:
            return QueryAnswer(
                "bundles_v1",
                say("连带购买组合", "Products bought together"),
                say("当前范围的订单太少，找不到可靠的组合。", "Too few orders to find reliable pairs."),
                data,
                say("至少需要 8 笔共同购买。", "Requires at least 8 joint orders."),
            )
        top = data.iloc[0]
        return QueryAnswer(
            "bundles_v1",
            say("连带购买组合", "Products bought together"),
            say(
                f"最强组合是 {top['antecedent_name']} 与 {top['consequent_name']}："
                f"同时购买的概率是随机水平的 {top['lift']:.1f} 倍，共 {top['pair_orders']} 单。",
                f"The strongest pair is {top['antecedent_name']} and {top['consequent_name']}, "
                f"bought together {top['lift']:.1f}× more often than chance across "
                f"{top['pair_orders']} orders.",
            ),
            data,
            say(
                "提升度 = 置信度 ÷ 目标商品的基准购买率，大于 1 说明不是巧合。",
                "Lift = confidence ÷ the target's base rate; above 1 means more than coincidence.",
            ),
        )

    if intent == "low_margin_products":
        data = product_profitability(db_path, filters, limit=100)
        revenue_cut = data["revenue"].median() if not data.empty else 0
        data = data[(data["revenue"] >= revenue_cut) & (data["contribution_margin"] < 0.12)].head(
            20
        )
        return QueryAnswer(
            "low_margin_products_v2",
            say("高收入低利润商品", "High-revenue, low-margin products"),
            say(
                f"识别到 {len(data)} 个高收入但贡献利润率低于12%的商品。"
                "建议优先检查折扣、采购成本和物流成本，而不是直接扩大销量。",
                f"Identified {len(data)} high-revenue products with contribution margins below 12%. "
                "Review discounts, procurement costs, and shipping costs before expanding volume.",
            ),
            data,
            say(
                "按照收入高于中位数且贡献利润率低于12%筛选。",
                "Revenue above the median and contribution margin below 12%.",
            ),
        )

    if intent in {"country_driver", "channel_mix", "category_mix"}:
        dimension = {
            "country_driver": "country",
            "channel_mix": "channel",
            "category_mix": "category",
        }[intent]
        labels = {
            "country": say("国家/地区", "Market"),
            "channel": say("渠道", "Channel"),
            "category": say("品类", "Category"),
        }
        data = dimension_change(db_path, filters, dimension, limit=10)
        if data.empty:
            answer = say("当前筛选条件下没有足够数据。", "There is not enough data under the current filters.")
        else:
            top = data.iloc[0]
            answer = say(
                f"影响最大的{labels[dimension]}是 {top[dimension]}，净销售额变化约 "
                f"{amount(top['change'])}，贡献利润变化约 {amount(top['profit_change'])}。",
                f"The largest {labels[dimension].lower()} driver was {top[dimension]}: net revenue "
                f"changed by about {amount(top['change'])} and contribution profit by about "
                f"{amount(top['profit_change'])}.",
            )
        return QueryAnswer(
            f"{dimension}_driver_v2",
            say(f"{labels[dimension]}变化贡献", f"{labels[dimension]} contributions"),
            answer,
            data,
            say(
                "比较等长前后期间，并按净销售额绝对变化排序。",
                "Compare equal-length periods and rank by absolute net-revenue change.",
            ),
        )

    if intent == "top_products":
        data = product_profitability(db_path, filters, limit=20)
        top = data.iloc[0] if not data.empty else None
        return QueryAnswer(
            "top_products_v1",
            say("畅销商品", "Top products"),
            say(
                f"净销售额最高的是 {top['description']}，{amount(top['revenue'])}。"
                if top is not None
                else "当前筛选条件下没有商品数据。",
                f"The top product is {top['description']} at {amount(top['revenue'])}."
                if top is not None
                else "No products under the current filters.",
            ),
            data,
            say("按净销售额（已扣退货）排序。", "Ranked by net revenue after returns."),
        )

    if intent == "churn_risk":
        data = customer_value_risk(db_path, filters).head(20)
        risk_value = float(data["expected_profit_at_risk"].sum()) if not data.empty else 0
        return QueryAnswer(
            "customer_churn_v2",
            say("高价值客户流失风险", "High-value customer churn risk"),
            say(
                f"前20名风险客户预计涉及利润风险约 {amount(risk_value)}，应优先处理高CLV且流失风险高的客户。",
                f"The top 20 at-risk customers represent about {amount(risk_value)} in expected "
                "profit risk. Prioritize customers with both high CLV and high churn risk.",
            ),
            data,
            say(
                "模型通过跨期验证时用模型概率，否则回退为可解释规则分数。",
                "Uses the model when out-of-time validation passes, otherwise an explainable rule score.",
            ),
        )

    if intent == "inventory_risk":
        data = inventory_status(db_path, "Reorder").head(30)
        count = len(inventory_status(db_path, "Reorder"))
        return QueryAnswer(
            "inventory_reorder_v1",
            say("补货风险SKU", "Replenishment-risk SKUs"),
            say(f"共有 {count} 个SKU达到补货预警条件。", f"{count} SKUs meet the replenishment-alert condition."),
            data,
            say(
                "当库存可售天数低于供应商提前期加7天安全期时触发预警。",
                "Alert when days of supply are below supplier lead time plus a seven-day safety buffer.",
            ),
        )

    if intent == "target_risk":
        month = str(pd.Timestamp(filters.end_date).to_period("M"))
        data = target_status(db_path, month)
        off = data[data["status"] != "On Track"] if not data.empty else data
        return QueryAnswer(
            "target_status_v1",
            say("经营目标完成状态", "Operating target status"),
            say(
                f"{month}共有 {len(off)} 项指标处于风险或未达标状态。",
                f"{len(off)} metrics are at risk or off track in {month}.",
            ),
            off,
            say(
                "将实际值与目标值按指标方向计算完成度。",
                "Calculate attainment from actual versus target with metric direction applied.",
            ),
        )

    data = quality_dimensions(db_path)
    score = float(data["score_100"].mean()) if not data.empty else 0
    lowest = data.sort_values("score_100").iloc[0] if not data.empty else None
    return QueryAnswer(
        "data_quality_v1",
        say("数据质量可信度", "Data-quality trust"),
        (
            say(
                f"综合数据质量得分为 {score:.1f}/100。最低维度是{lowest['dimension']}（{lowest['score_100']:.1f}分）。",
                f"The composite data-quality score is {score:.1f}/100. The lowest dimension is "
                f"{lowest['dimension']} ({lowest['score_100']:.1f}).",
            )
            if lowest is not None
            else say("没有数据质量记录。", "No data-quality records are available.")
        ),
        data,
        say(
            "从完整性、唯一性、有效性、一致性和时间覆盖五个维度评分。",
            "Score completeness, uniqueness, validity, consistency, and temporal coverage.",
        ),
    )
