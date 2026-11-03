from __future__ import annotations

import streamlit as st

from insightflow.churn import train_churn_model
from insightflow.config import DEFAULT_DB_PATH
from insightflow.currency import money, symbol
from insightflow.design import SERIES
from insightflow.i18n import t, tr
from insightflow.live import gauge_strip
from insightflow.metrics import (
    cohort_retention,
    customer_coverage,
    customer_value_risk,
    rfm_segments,
)
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
from insightflow.viz import calibration_chart, heatmap, quadrant, segment_treemap, show

SEGMENT_ZH = {
    "Champions": "冠军客户",
    "Loyal": "忠诚客户",
    "Potential": "潜力客户",
    "At Risk": "风险客户",
    "Hibernating": "沉睡客户",
    "Developing": "成长客户",
}
SEGMENT_ORDER = list(SEGMENT_ZH)


def render() -> None:
    filters = sidebar_filters(DEFAULT_DB_PATH)
    code = currency_code()
    prefix = symbol(code)
    rfm = rfm_segments(DEFAULT_DB_PATH, filters)
    if rfm.empty:
        page_header(
            t("page.customers.title"),
            tr("当前筛选条件下没有可分析的客户。", "No customers under the current filters."),
            meta=period_meta(filters),
        )
        return

    value = customer_value_risk(DEFAULT_DB_PATH, filters)
    at_risk = value[value["churn_risk"] >= 0.5]
    exposure = float(at_risk["expected_profit_at_risk"].sum())
    page_header(
        t("page.customers.title"),
        tr(
            f"{len(at_risk):,} 位客户大概率不再回购，涉及预期利润 {money(exposure, code, short=True)}。",
            f"{len(at_risk):,} customers are unlikely to return, putting "
            f"{money(exposure, code, short=True)} of expected profit at risk.",
        ),
        meta=period_meta(filters),
    )

    gauge_strip(
        [
            gauge_item(
                tr("期内客户", "Customers"), len(value), "count", f"{len(value):,}", note_text=""
            ),
            gauge_item(
                tr("客均贡献利润", "Profit per customer"),
                float(value["contribution_profit"].mean()),
                "money",
                money(float(value["contribution_profit"].mean()), code),
                prefix=prefix,
                note_text="",
            ),
            gauge_item(
                tr("预测客户价值中位数", "Median predicted value"),
                float(value["predicted_clv"].median()),
                "money",
                money(float(value["predicted_clv"].median()), code),
                prefix=prefix,
                note_text=tr("未来 12 个月", "Next 12 months"),
            ),
            gauge_item(
                tr("高风险客户占比", "High-risk share"),
                len(at_risk) / max(len(value), 1),
                "percent",
                f"{len(at_risk) / max(len(value), 1):.1%}",
                note_text=tr("回购概率低于 50%", "Return chance under 50%"),
            ),
        ],
        key="customer_gauges",
    )
    coverage = customer_coverage(DEFAULT_DB_PATH, filters)
    if coverage < 0.95:
        note(
            tr(
                f"这里只分析带客户编号的订单，占净销售额 {coverage:.0%}。其余是匿名订单，不在客户分析内。",
                f"Only orders with a customer ID are analysed here, {coverage:.0%} of net revenue. "
                "The rest are anonymous and fall outside customer analysis.",
            )
        )

    section_header(tr("客户分层", "Customer segments"), tr("按最近购买、频次和金额", "By recency, frequency and value"))
    segments = (
        rfm.groupby("segment", as_index=False)
        .agg(
            customers=("customer_id", "nunique"),
            revenue=("monetary", "sum"),
            contribution_profit=("contribution_profit", "sum"),
            avg_frequency=("frequency", "mean"),
        )
        .sort_values("contribution_profit", ascending=False)
    )
    names = {name: tr(chinese, name) for name, chinese in SEGMENT_ZH.items()}
    colors = dict(zip(SEGMENT_ORDER, SERIES, strict=False))
    segments["label"] = segments["segment"].map(names)
    show(
        segment_treemap(
            segments,
            label="label",
            value="contribution_profit",
            palette={names[name]: color for name, color in colors.items()},
            money_prefix=prefix,
        ),
        key="customer_segments",
    )
    table_view(segments[["segment", "customers", "revenue", "contribution_profit", "avg_frequency"]].round(2))

    section_header(tr("流失预测", "Churn prediction"), tr("未来 90 天是否回购", "Will they buy in the next 90 days"))
    model = train_churn_model(DEFAULT_DB_PATH)
    left, right = st.columns([1.4, 1], gap="large")
    with left:
        subhead(tr("价值与风险", "Value against risk"))
        show(
            quadrant(
                value.head(400),
                x="predicted_clv",
                y="churn_risk",
                size="contribution_profit",
                name="customer_id",
                labels={"x": tr("预测客户价值", "Predicted value"), "y": tr("流失风险", "Churn risk")},
                money_prefix=prefix,
                high_is_good=False,
            ),
            key="customer_risk_map",
        )
    with right:
        subhead(tr("模型靠不靠谱", "Can this model be trusted"))
        if model is None:
            verdict(
                tr("未启用模型", "Model not used"),
                tr(
                    "客户或历史数据不足以做跨期验证，当前使用可解释规则分数。",
                    "Too little history to validate out of time, so an explainable rule score is used.",
                ),
                "neutral",
            )
        else:
            if model.useful:
                verdict(
                    tr("已通过跨期验证", "Passed out-of-time validation"),
                    tr(
                        f"用旧数据训练，再预测之后 90 天：AUC {model.auc:.2f}，"
                        f"前 10% 客户的回购率是平均的 {model.top_decile_lift:.1f} 倍。",
                        f"Trained on older data and graded on the following 90 days: AUC "
                        f"{model.auc:.2f}, top 10% return at {model.top_decile_lift:.1f}× the average.",
                    ),
                    "good",
                )
            else:
                verdict(
                    tr("模型未达标", "Model below standard"),
                    tr(
                        f"跨期 AUC 只有 {model.auc:.2f}，因此继续使用规则分数。",
                        f"Out-of-time AUC is only {model.auc:.2f}, so the rule score stays in use.",
                    ),
                    "warning",
                )
            show(
                calibration_chart(
                    model.calibration,
                    labels={
                        "x": tr("预测回购率", "Predicted return rate"),
                        "y": tr("实际回购率", "Actual return rate"),
                        "ideal": tr("完全准确", "Perfect"),
                        "model": tr("本模型", "This model"),
                    },
                ),
                key="customer_calibration",
            )
            note(
                tr(
                    f"训练客户 {model.train_customers:,} 位，验证客户 {model.test_customers:,} 位，"
                    "点越靠近对角线，预测概率越可信。验证通过后，模型用最新一期数据重训再给客户打分。",
                    f"{model.train_customers:,} training and {model.test_customers:,} test customers. "
                    "Points near the diagonal mean the probabilities can be read literally. After "
                    "validation the model is refit on the newest window before scoring customers.",
                )
            )

    subhead(tr("优先联系名单", "Who to contact first"))
    actions_en = {
        "高价值定向召回": "Targeted win-back",
        "低成本自动触达": "Low-cost automated nudge",
        "忠诚度与交叉销售": "Loyalty and cross-sell",
        "常规培育": "Routine nurture",
    }
    columns = {
        "customer_id": tr("客户", "Customer"),
        "predicted_clv": tr("预测价值", "Predicted value"),
        "churn_risk": tr("流失风险", "Churn risk"),
        "expected_profit_at_risk": tr("风险利润", "Profit at risk"),
        "recency": tr("距上次购买（天）", "Days since purchase"),
        "frequency": tr("订单数", "Orders"),
        "recommended_action": tr("建议动作", "Suggested action"),
    }
    shown = value.head(60)[list(columns)].copy()
    shown["recommended_action"] = shown["recommended_action"].map(lambda v: tr(v, actions_en.get(v, v)))
    st.dataframe(
        shown.rename(columns=columns),
        hide_index=True,
        column_config={
            columns["predicted_clv"]: st.column_config.NumberColumn(format="%,.0f"),
            columns["expected_profit_at_risk"]: st.column_config.NumberColumn(format="%,.0f"),
            columns["churn_risk"]: st.column_config.ProgressColumn(
                min_value=0.0, max_value=1.0, format="percent"
            ),
        },
    )

    section_header(tr("队列留存", "Cohort retention"), tr("每个首购月份之后的留存率", "Share returning after the first purchase month"))
    retention = cohort_retention(DEFAULT_DB_PATH, filters.undated())
    if retention.empty:
        note(tr("数据不足以计算队列留存。", "Not enough data for cohort retention."))
    else:
        show(
            heatmap(
                retention.tail(12).iloc[:, :12],
                x_label=tr("首购后第几个月", "Months since first purchase"),
                y_label=tr("首购月份", "First purchase month"),
            ),
            key="customer_cohorts",
        )
