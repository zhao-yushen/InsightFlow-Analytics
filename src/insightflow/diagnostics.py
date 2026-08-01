from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import permutations
from pathlib import Path

import numpy as np
import pandas as pd

from .metrics import (
    FilterSpec,
    dimension_performance,
    inventory_kpis,
    kpi_summary,
    monthly_trend,
    percent_change,
    previous_period,
    quality_score,
    target_status,
)
from .warehouse import query_df


@dataclass
class DiagnosticIssue:
    severity: str
    category: str
    title: str
    finding: str
    evidence: str
    recommendation: str
    confidence: float

    def to_dict(self) -> dict:
        return asdict(self)


def revenue_driver_decomposition(current: dict[str, float], previous: dict[str, float]) -> pd.DataFrame:
    """Exact Shapley decomposition of R = customers × frequency × AOV."""
    factor_names = ["active_customers", "purchase_frequency", "average_order_value"]
    labels = {
        "active_customers": "活跃客户数",
        "purchase_frequency": "购买频次",
        "average_order_value": "客单价",
    }
    base = {k: float(previous.get(k, 0)) for k in factor_names}
    new = {k: float(current.get(k, 0)) for k in factor_names}

    def revenue(state: dict[str, float]) -> float:
        return state["active_customers"] * state["purchase_frequency"] * state["average_order_value"]

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


def profit_driver_decomposition(current: dict[str, float], previous: dict[str, float]) -> pd.DataFrame:
    """Exact bridge of contribution profit = revenue × gross margin - variable operating cost."""
    cur_revenue = float(current.get("revenue", 0))
    prev_revenue = float(previous.get("revenue", 0))
    cur_margin = float(current.get("gross_margin", 0))
    prev_margin = float(previous.get("gross_margin", 0))
    cur_opex = sum(float(current.get(k, 0)) for k in ("shipping_cost", "payment_fee", "marketing_cost"))
    prev_opex = sum(float(previous.get(k, 0)) for k in ("shipping_cost", "payment_fee", "marketing_cost"))
    rows = [
        {
            "driver": "净销售额变化",
            "profit_contribution": (cur_revenue - prev_revenue) * prev_margin,
            "explanation": "销售规模变化在上期毛利率下产生的利润影响",
        },
        {
            "driver": "毛利率变化",
            "profit_contribution": cur_revenue * (cur_margin - prev_margin),
            "explanation": "商品成本、价格和折扣结构变化带来的影响",
        },
        {
            "driver": "可变经营成本变化",
            "profit_contribution": -(cur_opex - prev_opex),
            "explanation": "物流、支付与营销费用变化带来的影响",
        },
    ]
    return pd.DataFrame(rows).sort_values("profit_contribution")


def dimension_change(db_path: str | Path, current: FilterSpec, dimension: str, limit: int = 12) -> pd.DataFrame:
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
    db_path: str | Path, current: FilterSpec
) -> tuple[list[DiagnosticIssue], pd.DataFrame]:
    prev_filter = previous_period(current)
    cur = kpi_summary(db_path, current)
    prev = kpi_summary(db_path, prev_filter)
    drivers = revenue_driver_decomposition(cur, prev)
    profit_drivers = profit_driver_decomposition(cur, prev)
    issues: list[DiagnosticIssue] = []
    if float(cur.get("orders", 0)) < 5:
        return issues, drivers
    comparison_sufficient = float(prev.get("orders", 0)) >= 5

    revenue_change = percent_change(cur["revenue"], prev["revenue"]) if comparison_sufficient else None
    profit_change = (
        percent_change(cur["contribution_profit"], prev["contribution_profit"])
        if comparison_sufficient
        else None
    )
    if revenue_change is not None and revenue_change <= -0.05:
        worst = drivers.iloc[0]
        issues.append(
            DiagnosticIssue(
                severity="P1",
                category="经营结果",
                title="净销售额显著下降",
                finding=f"本期净销售额较上期下降 {abs(revenue_change):.1%}。",
                evidence=f"最大负向驱动为{worst['driver']}，收入贡献约 {worst['revenue_contribution']:,.0f}。",
                recommendation="按国家、客户群与商品定位下滑来源，并区分需求下降和结构迁移。",
                confidence=0.96,
            )
        )
    elif revenue_change is not None and revenue_change >= 0.08:
        best = drivers.iloc[-1]
        issues.append(
            DiagnosticIssue(
                severity="P3",
                category="增长机会",
                title="净销售额实现较快增长",
                finding=f"本期净销售额较上期增长 {revenue_change:.1%}。",
                evidence=f"最大正向驱动为{best['driver']}，收入贡献约 {best['revenue_contribution']:,.0f}。",
                recommendation="验证增长是否来自可持续客户与高利润商品，避免低质量规模扩张。",
                confidence=0.94,
            )
        )

    if profit_change is not None and profit_change <= -0.05:
        worst_profit = profit_drivers.iloc[0]
        severity = "P0" if (revenue_change or 0) >= 0 else "P1"
        issues.append(
            DiagnosticIssue(
                severity=severity,
                category="盈利能力",
                title="贡献利润显著承压",
                finding=f"本期贡献利润较上期下降 {abs(profit_change):.1%}，贡献利润率为 {cur['contribution_margin']:.1%}。",
                evidence=f"最大负向因素为{worst_profit['driver']}，影响约 {worst_profit['profit_contribution']:,.0f}。",
                recommendation="优先检查折扣、商品成本、物流与营销费用，避免只追求收入增长。",
                confidence=0.97,
            )
        )
    if cur["gross_margin"] < 0.38:
        issues.append(
            DiagnosticIssue(
                severity="P1",
                category="盈利能力",
                title="毛利率低于经营警戒线",
                finding=f"本期毛利率为 {cur['gross_margin']:.1%}。",
                evidence=f"折扣率 {cur['discount_rate']:.1%}，商品成本占净销售额 {cur['cogs']/max(cur['revenue'],1):.1%}。",
                recommendation="筛查高收入低毛利商品，并模拟价格、折扣和采购成本调整方案。",
                confidence=0.94,
            )
        )

    cancel_change = (
        cur["cancellation_rate"] - prev["cancellation_rate"]
        if comparison_sufficient
        else 0.0
    )
    if cur["cancellation_rate"] >= 0.05 or cancel_change >= 0.015:
        issues.append(
            DiagnosticIssue(
                severity="P1",
                category="履约质量",
                title="取消率偏高或快速上升",
                finding=f"本期取消率为 {cur['cancellation_rate']:.1%}，较上期变化 {cancel_change:+.1%}。",
                evidence=f"取消与退货预计造成损失 {cur['return_loss']:,.0f}。",
                recommendation="按国家、商品与渠道拆解取消率，并检查库存、质量和履约环节。",
                confidence=0.93,
            )
        )

    if cur["repeat_rate"] < 0.35:
        issues.append(
            DiagnosticIssue(
                severity="P2",
                category="客户质量",
                title="复购率偏低",
                finding=f"本期复购率为 {cur['repeat_rate']:.1%}。",
                evidence="较低复购率意味着收入对持续获客依赖较强，营销费用回收压力更高。",
                recommendation="针对首购后30天未复购客户建立分层召回，并优先保护高CLV客户。",
                confidence=0.86,
            )
        )

    concentration = query_df(
        db_path,
        """
        WITH p AS (
          SELECT stock_code, SUM(net_revenue) revenue
          FROM v_sales
          WHERE date BETWEEN ? AND ?
          GROUP BY stock_code
        ), ranked AS (
          SELECT revenue, ROW_NUMBER() OVER (ORDER BY revenue DESC) rn FROM p
        )
        SELECT COALESCE(SUM(CASE WHEN rn <= 10 THEN revenue ELSE 0 END),0) /
               NULLIF(SUM(revenue),0) AS top10_share
        FROM ranked
        """,
        (current.start_date, current.end_date),
    ).iloc[0, 0]
    if concentration and concentration >= 0.45:
        issues.append(
            DiagnosticIssue(
                severity="P2",
                category="结构风险",
                title="收入对头部商品依赖较高",
                finding=f"前10个商品贡献本期净销售额的 {float(concentration):.1%}。",
                evidence="高集中度会放大单品缺货、竞争或生命周期变化带来的波动。",
                recommendation="建立头部商品库存预警，同时培育高利润第二梯队商品。",
                confidence=0.90,
            )
        )

    inv = inventory_kpis(db_path)
    if inv["reorder_skus"] > 0:
        issues.append(
            DiagnosticIssue(
                severity="P1" if inv["reorder_skus"] >= 10 else "P2",
                category="库存履约",
                title="部分商品存在补货风险",
                finding=f"当前有 {inv['reorder_skus']:.0f} 个SKU库存覆盖低于补货提前期加安全天数。",
                evidence=f"全部库存价值约 {inv['inventory_value']:,.0f}，平均可售天数 {inv['avg_days_of_supply']:.1f} 天。",
                recommendation="优先对高销售额且补货周期长的SKU下达补货计划。",
                confidence=0.91,
            )
        )

    target = target_status(db_path, str(pd.Timestamp(current.end_date).to_period("M"))) if current.end_date else pd.DataFrame()
    if not target.empty:
        off_track = target[target["status"] == "Off Track"]
        if not off_track.empty:
            metric = off_track.sort_values("attainment").iloc[0]
            metric_labels = {
                "net_revenue": "净销售额",
                "contribution_profit": "贡献利润",
                "gross_margin": "毛利率",
                "cancellation_rate": "取消率",
            }
            metric_name = metric_labels.get(str(metric["metric_id"]), str(metric["metric_id"]))
            issues.append(
                DiagnosticIssue(
                    severity="P1",
                    category="目标管理",
                    title="关键经营目标明显偏离",
                    finding=f"{metric_name}目标完成度为 {metric['attainment']:.1%}。",
                    evidence=f"实际值 {metric['actual_value']:,.2f}，目标值 {metric['target_value']:,.2f}。",
                    recommendation=f"由{metric['owner']}负责人建立差距关闭计划，并在决策实验室比较可行方案。",
                    confidence=0.95,
                )
            )

    dq_score = quality_score(db_path)
    if dq_score < 90:
        issues.append(
            DiagnosticIssue(
                severity="P2",
                category="数据质量",
                title="数据质量得分低于发布标准",
                finding=f"当前综合数据质量得分为 {dq_score:.1f}/100。",
                evidence="低质量数据可能影响客户、利润和预测结论的可信度。",
                recommendation="在数据质量中心处理缺失、重复和非法记录后再发布正式报告。",
                confidence=0.99,
            )
        )

    if not issues:
        issues.append(
            DiagnosticIssue(
                severity="P3",
                category="经营状态",
                title="核心经营指标总体稳定",
                finding="未发现达到预设阈值的重大经营异常。",
                evidence="收入、利润、取消率、复购率、库存及数据质量均未触发高风险规则。",
                recommendation="继续关注预测区间和细分结构，避免整体稳定掩盖局部异常。",
                confidence=0.88,
            )
        )
    return issues, drivers
