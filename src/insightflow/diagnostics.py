from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import permutations
from pathlib import Path

import numpy as np
import pandas as pd

from .currency import money, warehouse_currency
from .metrics import (
    FilterSpec,
    dimension_performance,
    filter_clause,
    inventory_kpis,
    kpi_summary,
    monthly_trend,
    percent_change,
    previous_period,
    quality_score,
    target_status,
)
from .warehouse import query_df

TARGET_LABELS = {
    "net_revenue": ("净销售额", "Net revenue"),
    "contribution_profit": ("贡献利润", "Contribution profit"),
    "gross_margin": ("毛利率", "Gross margin"),
    "cancellation_rate": ("退货取消率", "Return rate"),
}


def _chooser(language: str):
    """Return a picker for inline copy. Everything except zh-CN reads the English."""

    def say(chinese: str, english: str) -> str:
        return chinese if language == "zh-CN" else english

    return say


@dataclass
class DiagnosticIssue:
    severity: str
    category: str
    title: str
    finding: str
    evidence: str
    recommendation: str
    confidence: float
    code: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def revenue_driver_decomposition(
    current: dict[str, float], previous: dict[str, float], *, language: str = "zh-CN"
) -> pd.DataFrame:
    """Exact Shapley decomposition of R = customers × frequency × AOV."""
    say = _chooser(language)
    factor_names = ["active_customers", "purchase_frequency", "average_order_value"]
    labels = {
        "active_customers": say("活跃客户数", "Active customers"),
        "purchase_frequency": say("购买频次", "Purchase frequency"),
        "average_order_value": say("客单价", "Average order value"),
    }
    base = {k: float(previous.get(k, 0)) for k in factor_names}
    new = {k: float(current.get(k, 0)) for k in factor_names}

    def revenue(state: dict[str, float]) -> float:
        return (
            state["active_customers"] * state["purchase_frequency"] * state["average_order_value"]
        )

    contributions = {k: 0.0 for k in factor_names}
    perms = list(permutations(factor_names))
    for order in perms:
        state = base.copy()
        for factor in order:
            before = revenue(state)
            state[factor] = new[factor]
            after = revenue(state)
            contributions[factor] += after - before
    for factor in contributions:
        contributions[factor] /= len(perms)

    return pd.DataFrame(
        [
            {
                "driver": labels[k],
                "previous": base[k],
                "current": new[k],
                "change": new[k] - base[k],
                "revenue_contribution": contributions[k],
            }
            for k in factor_names
        ]
    ).sort_values("revenue_contribution")


def profit_driver_decomposition(
    current: dict[str, float], previous: dict[str, float], *, language: str = "zh-CN"
) -> pd.DataFrame:
    """Exact bridge of contribution profit = revenue × gross margin - variable operating cost."""
    say = _chooser(language)
    cur_revenue = float(current.get("revenue", 0))
    prev_revenue = float(previous.get("revenue", 0))
    cur_margin = float(current.get("gross_margin", 0))
    prev_margin = float(previous.get("gross_margin", 0))
    operating_costs = ("shipping_cost", "payment_fee", "marketing_cost", "return_processing_cost")
    cur_opex = sum(float(current.get(k, 0)) for k in operating_costs)
    prev_opex = sum(float(previous.get(k, 0)) for k in operating_costs)
    rows = [
        {
            "driver": say("净销售额变化", "Net revenue change"),
            "profit_contribution": (cur_revenue - prev_revenue) * prev_margin,
            "explanation": say(
                "销售规模变化在上期毛利率下产生的利润影响",
                "Profit effect of the change in sales at last period's gross margin",
            ),
        },
        {
            "driver": say("毛利率变化", "Gross margin change"),
            "profit_contribution": cur_revenue * (cur_margin - prev_margin),
            "explanation": say(
                "商品成本、价格和折扣结构变化带来的影响",
                "Effect of changes in product cost, price and discount mix",
            ),
        },
        {
            "driver": say("可变经营成本变化", "Variable cost change"),
            "profit_contribution": -(cur_opex - prev_opex),
            "explanation": say(
                "物流、支付、营销与退货处理费用变化带来的影响",
                "Effect of changes in shipping, payment, marketing and return handling",
            ),
        },
    ]
    return pd.DataFrame(rows).sort_values("profit_contribution")


def dimension_change(
    db_path: str | Path, current: FilterSpec, dimension: str, limit: int = 12
) -> pd.DataFrame:
    previous = previous_period(current)
    cur = dimension_performance(db_path, current, dimension, limit=1000).rename(
        columns={"revenue": "current_revenue", "contribution_profit": "current_profit"}
    )
    prev = dimension_performance(db_path, previous, dimension, limit=1000).rename(
        columns={"revenue": "previous_revenue", "contribution_profit": "previous_profit"}
    )
    cols = [dimension, "current_revenue", "current_profit"]
    prev_cols = [dimension, "previous_revenue", "previous_profit"]
    merged = cur[cols].merge(prev[prev_cols], on=dimension, how="outer").fillna(0)
    merged["change"] = merged["current_revenue"] - merged["previous_revenue"]
    merged["profit_change"] = merged["current_profit"] - merged["previous_profit"]
    merged["change_rate"] = np.where(
        merged["previous_revenue"].abs() > 0,
        merged["change"] / merged["previous_revenue"].abs(),
        np.nan,
    )
    return merged.reindex(merged["change"].abs().sort_values(ascending=False).index).head(limit)


def monthly_anomalies(db_path: str | Path, filters: FilterSpec | None = None) -> pd.DataFrame:
    trend = monthly_trend(db_path, filters or FilterSpec())
    if len(trend) < 6:
        return pd.DataFrame()
    out = trend.copy()
    for metric in ("revenue", "contribution_profit", "cancellation_rate"):
        if metric not in out:
            continue
        series = out[metric].astype(float)
        rolling_median = series.rolling(6, min_periods=4).median()
        mad = (series - rolling_median).abs().rolling(6, min_periods=4).median()
        out[f"{metric}_robust_z"] = 0.6745 * (series - rolling_median) / mad.replace(0, np.nan)
    z_cols = [c for c in out.columns if c.endswith("_robust_z")]
    if not z_cols:
        return pd.DataFrame()
    out["is_anomaly"] = out[z_cols].abs().max(axis=1) >= 2.5
    return out.loc[out["is_anomaly"]].copy()


def generate_diagnostics(
    db_path: str | Path, current: FilterSpec, *, language: str = "zh-CN"
) -> tuple[list[DiagnosticIssue], pd.DataFrame]:
    say = _chooser(language)
    code = warehouse_currency(db_path)

    def amount(value: float) -> str:
        return money(float(value), code)

    prev_filter = previous_period(current)
    cur = kpi_summary(db_path, current)
    prev = kpi_summary(db_path, prev_filter)
    drivers = revenue_driver_decomposition(cur, prev, language=language)
    profit_drivers = profit_driver_decomposition(cur, prev, language=language)
    issues: list[DiagnosticIssue] = []
    if float(cur.get("orders", 0)) < 5:
        return issues, drivers
    comparison_sufficient = float(prev.get("orders", 0)) >= 5

    revenue_change = (
        percent_change(cur["revenue"], prev["revenue"]) if comparison_sufficient else None
    )
    profit_change = (
        percent_change(cur["contribution_profit"], prev["contribution_profit"])
        if comparison_sufficient
        else None
    )
    if revenue_change is not None and revenue_change <= -0.05:
        worst = drivers.iloc[0]
        contribution = amount(worst["revenue_contribution"])
        issues.append(
            DiagnosticIssue(
                severity="P1",
                category=say("经营结果", "Results"),
                title=say("净销售额显著下降", "Net revenue fell sharply"),
                finding=say(
                    f"本期净销售额较上期下降 {abs(revenue_change):.1%}。",
                    f"Net revenue fell {abs(revenue_change):.1%} on the prior period.",
                ),
                evidence=say(
                    f"最大负向驱动为{worst['driver']}，收入贡献约 {contribution}。",
                    f"The largest negative driver was {worst['driver']}, about {contribution}.",
                ),
                recommendation=say(
                    "按国家、客户群与商品定位下滑来源，并区分需求下降和结构迁移。",
                    "Locate the decline by market, customer group and product, and separate "
                    "falling demand from a shift in mix.",
                ),
                confidence=0.96,
                code="revenue_drop",
            )
        )
    elif revenue_change is not None and revenue_change >= 0.08:
        best = drivers.iloc[-1]
        contribution = amount(best["revenue_contribution"])
        issues.append(
            DiagnosticIssue(
                severity="P3",
                category=say("增长机会", "Growth"),
                title=say("净销售额实现较快增长", "Net revenue grew quickly"),
                finding=say(
                    f"本期净销售额较上期增长 {revenue_change:.1%}。",
                    f"Net revenue grew {revenue_change:.1%} on the prior period.",
                ),
                evidence=say(
                    f"最大正向驱动为{best['driver']}，收入贡献约 {contribution}。",
                    f"The largest positive driver was {best['driver']}, about {contribution}.",
                ),
                recommendation=say(
                    "验证增长是否来自可持续客户与高利润商品，避免低质量规模扩张。",
                    "Check that growth comes from lasting customers and profitable products, "
                    "not low-quality volume.",
                ),
                confidence=0.94,
                code="revenue_growth",
            )
        )

    if profit_change is not None and profit_change <= -0.05:
        worst_profit = profit_drivers.iloc[0]
        severity = "P0" if (revenue_change or 0) >= 0 else "P1"
        impact = amount(worst_profit["profit_contribution"])
        issues.append(
            DiagnosticIssue(
                severity=severity,
                category=say("盈利能力", "Profitability"),
                title=say("贡献利润显著承压", "Contribution profit under pressure"),
                finding=say(
                    f"本期贡献利润较上期下降 {abs(profit_change):.1%}，"
                    f"贡献利润率为 {cur['contribution_margin']:.1%}。",
                    f"Contribution profit fell {abs(profit_change):.1%}, to a "
                    f"{cur['contribution_margin']:.1%} margin.",
                ),
                evidence=say(
                    f"最大负向因素为{worst_profit['driver']}，影响约 {impact}。",
                    f"The largest negative factor was {worst_profit['driver']}, about {impact}.",
                ),
                recommendation=say(
                    "优先检查折扣、商品成本、物流与营销费用，避免只追求收入增长。",
                    "Check discounts, product cost, shipping and marketing first, rather than "
                    "chasing revenue alone.",
                ),
                confidence=0.97,
                code="profit_pressure",
            )
        )
    if cur["gross_margin"] < 0.38:
        cost_share = cur["cogs"] / max(cur["revenue"], 1)
        issues.append(
            DiagnosticIssue(
                severity="P1",
                category=say("盈利能力", "Profitability"),
                title=say("毛利率低于经营警戒线", "Gross margin below the alert line"),
                finding=say(
                    f"本期毛利率为 {cur['gross_margin']:.1%}。",
                    f"Gross margin is {cur['gross_margin']:.1%}.",
                ),
                evidence=say(
                    f"折扣率 {cur['discount_rate']:.1%}，商品成本占净销售额 {cost_share:.1%}。",
                    f"Discount rate {cur['discount_rate']:.1%}; product cost is {cost_share:.1%} "
                    "of net revenue.",
                ),
                recommendation=say(
                    "筛查高收入低毛利商品，并模拟价格、折扣和采购成本调整方案。",
                    "Review high-revenue, low-margin products and simulate changes to price, "
                    "discount and purchase cost.",
                ),
                confidence=0.94,
                code="margin_floor",
            )
        )

    cancel_change = (
        cur["cancellation_rate"] - prev["cancellation_rate"] if comparison_sufficient else 0.0
    )
    if cur["cancellation_rate"] >= 0.05 or cancel_change >= 0.015:
        issues.append(
            DiagnosticIssue(
                severity="P1",
                category=say("履约质量", "Fulfilment"),
                title=say("退货取消率偏高或快速上升", "Return rate high or rising fast"),
                finding=say(
                    f"本期退货取消率为 {cur['cancellation_rate']:.1%}，"
                    f"较上期变化 {cancel_change * 100:+.1f} 个百分点。",
                    f"The return rate is {cur['cancellation_rate']:.1%}, "
                    f"{cancel_change * 100:+.1f} pts on the prior period.",
                ),
                evidence=say(
                    f"退货退款 {amount(cur['returns_value'])}，"
                    f"折合利润损失 {amount(cur['return_loss'])}。",
                    f"Refunds of {amount(cur['returns_value'])} cost "
                    f"{amount(cur['return_loss'])} of profit.",
                ),
                recommendation=say(
                    "按国家、商品与渠道拆解退货，并检查库存、质量和履约环节。",
                    "Break returns down by market, product and channel, and check stock, "
                    "quality and fulfilment.",
                ),
                confidence=0.93,
                code="returns_rising",
            )
        )

    if cur["repeat_rate"] < 0.35:
        issues.append(
            DiagnosticIssue(
                severity="P2",
                category=say("客户质量", "Customers"),
                title=say("复购率偏低", "Repeat rate is low"),
                finding=say(
                    f"本期复购率为 {cur['repeat_rate']:.1%}。",
                    f"The repeat rate is {cur['repeat_rate']:.1%}.",
                ),
                evidence=say(
                    "较低复购率意味着收入对持续获客依赖较强，营销费用回收压力更高。",
                    "A low repeat rate makes revenue depend on new customers and makes "
                    "marketing harder to pay back.",
                ),
                recommendation=say(
                    "针对首购后30天未复购客户建立分层召回，并优先保护高CLV客户。",
                    "Set up tiered win-back for customers who have not returned 30 days after "
                    "their first order, starting with the most valuable.",
                ),
                confidence=0.86,
                code="repeat_low",
            )
        )

    where, params = filter_clause(current)
    concentration = query_df(
        db_path,
        f"""
        WITH p AS (
          SELECT stock_code, SUM(net_revenue) revenue
          FROM v_ledger
          WHERE {where}
          GROUP BY stock_code
        ), ranked AS (
          SELECT revenue, ROW_NUMBER() OVER (ORDER BY revenue DESC) rn FROM p
        )
        SELECT COALESCE(SUM(CASE WHEN rn <= 10 THEN revenue ELSE 0 END),0) /
               NULLIF(SUM(revenue),0) AS top10_share
        FROM ranked
        """,
        params,
    ).iloc[0, 0]
    distinct_products = query_df(
        db_path, f"SELECT COUNT(DISTINCT stock_code) FROM v_ledger WHERE {where}", params
    ).iloc[0, 0]
    # With few products in scope the top ten are simply all of them, which says nothing.
    if concentration and concentration >= 0.45 and int(distinct_products) > 30:
        issues.append(
            DiagnosticIssue(
                severity="P2",
                category=say("结构风险", "Concentration"),
                title=say("收入对头部商品依赖较高", "Revenue depends on a few products"),
                finding=say(
                    f"前10个商品贡献本期净销售额的 {float(concentration):.1%}。",
                    f"The top ten products bring {float(concentration):.1%} of net revenue.",
                ),
                evidence=say(
                    "高集中度会放大单品缺货、竞争或生命周期变化带来的波动。",
                    "High concentration magnifies the effect of a stockout, a competitor or a "
                    "product ageing.",
                ),
                recommendation=say(
                    "建立头部商品库存预警，同时培育高利润第二梯队商品。",
                    "Watch stock on the top products and develop a profitable second tier.",
                ),
                confidence=0.90,
                code="concentration",
            )
        )

    inv = inventory_kpis(db_path)
    if inv["reorder_skus"] > 0:
        issues.append(
            DiagnosticIssue(
                severity="P1" if inv["reorder_skus"] >= 10 else "P2",
                category=say("库存履约", "Inventory"),
                title=say("部分商品存在补货风险", "Some products risk running out"),
                finding=say(
                    f"当前有 {inv['reorder_skus']:.0f} 个SKU库存覆盖低于补货提前期加安全天数。",
                    f"{inv['reorder_skus']:.0f} products have less stock than their lead time "
                    "plus a safety buffer.",
                ),
                evidence=say(
                    f"全部库存价值约 {amount(inv['inventory_value'])}，"
                    f"平均可售天数 {inv['avg_days_of_supply']:.1f} 天。",
                    f"Inventory is worth about {amount(inv['inventory_value'])}, with "
                    f"{inv['avg_days_of_supply']:.1f} days of average cover.",
                ),
                recommendation=say(
                    "优先对高销售额且补货周期长的SKU下达补货计划。",
                    "Reorder high-revenue products with long lead times first.",
                ),
                confidence=0.91,
                code="reorder_risk",
            )
        )

    target = (
        target_status(db_path, str(pd.Timestamp(current.end_date).to_period("M")))
        if current.end_date
        else pd.DataFrame()
    )
    if not target.empty:
        off_track = target[target["status"] == "Off Track"]
        if not off_track.empty:
            metric = off_track.sort_values("attainment").iloc[0]
            metric_id = str(metric["metric_id"])
            metric_name = say(*TARGET_LABELS.get(metric_id, (metric_id, metric_id)))
            rate = metric_id in {"gross_margin", "cancellation_rate"}
            actual = f"{metric['actual_value']:.1%}" if rate else amount(metric["actual_value"])
            goal = f"{metric['target_value']:.1%}" if rate else amount(metric["target_value"])
            issues.append(
                DiagnosticIssue(
                    severity="P1",
                    category=say("目标管理", "Targets"),
                    title=say("关键经营目标明显偏离", "A key target is far off track"),
                    finding=say(
                        f"{metric_name}目标完成度为 {metric['attainment']:.1%}。",
                        f"{metric_name} is at {metric['attainment']:.1%} of target.",
                    ),
                    evidence=say(
                        f"实际值 {actual}，目标值 {goal}。",
                        f"Actual {actual} against a target of {goal}.",
                    ),
                    recommendation=say(
                        f"由{metric['owner']}负责人建立差距关闭计划，并在决策实验室比较可行方案。",
                        f"{metric['owner']} should own a plan to close the gap and compare "
                        "options in the Decision Lab.",
                    ),
                    confidence=0.95,
                    code="target_gap",
                )
            )

    dq_score = quality_score(db_path)
    if dq_score < 90:
        issues.append(
            DiagnosticIssue(
                severity="P2",
                category=say("数据质量", "Data quality"),
                title=say("数据质量得分低于发布标准", "Data quality below standard"),
                finding=say(
                    f"当前综合数据质量得分为 {dq_score:.1f}/100。",
                    f"Overall data quality is {dq_score:.1f}/100.",
                ),
                evidence=say(
                    "低质量数据可能影响客户、利润和预测结论的可信度。",
                    "Poor data can undermine customer, profit and forecast conclusions.",
                ),
                recommendation=say(
                    "在数据质量中心处理缺失、重复和非法记录后再发布正式报告。",
                    "Fix missing, duplicate and invalid records in the Trust Center before "
                    "publishing a report.",
                ),
                confidence=0.99,
                code="quality_low",
            )
        )

    if not issues:
        issues.append(
            DiagnosticIssue(
                severity="P3",
                category=say("经营状态", "Status"),
                title=say("核心经营指标总体稳定", "Core metrics are stable"),
                finding=say(
                    "未发现达到预设阈值的重大经营异常。",
                    "Nothing crossed an alert threshold.",
                ),
                evidence=say(
                    "收入、利润、取消率、复购率、库存及数据质量均未触发高风险规则。",
                    "Revenue, profit, returns, repeat rate, inventory and data quality all "
                    "stayed within their rules.",
                ),
                recommendation=say(
                    "继续关注预测区间和细分结构，避免整体稳定掩盖局部异常。",
                    "Keep watching forecast bands and segments, since a stable total can hide "
                    "local problems.",
                ),
                confidence=0.88,
                code="stable",
            )
        )
    return issues, drivers
