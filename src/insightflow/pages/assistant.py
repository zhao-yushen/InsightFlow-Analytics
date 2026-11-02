from __future__ import annotations

import streamlit as st

from insightflow.config import DEFAULT_DB_PATH
from insightflow.i18n import current_language, t, tr
from insightflow.query_assistant import (
    SUPPORTED_QUESTIONS,
    QueryAnswer,
    answer_business_question,
    question_label,
)
from insightflow.ui import note, page_header, period_meta, sidebar_filters

HISTORY = "assistant_history"
USER_ICON = ":material/person:"
ASSISTANT_ICON = ":material/water_drop:"
COLUMN_LABELS = {
    "driver": ("驱动因素", "Driver"),
    "previous": ("上期", "Previous"),
    "current": ("本期", "Current"),
    "change": ("变化", "Change"),
    "revenue_contribution": ("收入贡献", "Revenue effect"),
    "profit_contribution": ("利润影响", "Profit effect"),
    "explanation": ("说明", "Explanation"),
    "channel": ("渠道", "Channel"),
    "country": ("市场", "Market"),
    "category": ("品类", "Category"),
    "description": ("商品", "Product"),
    "stock_code": ("商品编码", "Product code"),
    "revenue": ("净销售额", "Net revenue"),
    "returns_value": ("退款", "Refunds"),
    "cancelled_orders": ("退货单数", "Return orders"),
    "cancellation_rate": ("退货取消率", "Return rate"),
    "orders": ("订单", "Orders"),
    "contribution_profit": ("贡献利润", "Contribution profit"),
    "contribution_margin": ("贡献利润率", "Contribution margin"),
    "current_revenue": ("本期净销售额", "Current revenue"),
    "previous_revenue": ("上期净销售额", "Previous revenue"),
    "profit_change": ("利润变化", "Profit change"),
    "change_rate": ("变化率", "Change rate"),
    "month": ("月份", "Month"),
    "forecast": ("预测值", "Forecast"),
    "lower": ("95% 下限", "95% low"),
    "upper": ("95% 上限", "95% high"),
    "lower_80": ("80% 下限", "80% low"),
    "upper_80": ("80% 上限", "80% high"),
    "elasticity": ("价格弹性", "Elasticity"),
    "basis": ("依据", "Basis"),
    "recommended_move": ("建议调价", "Suggested move"),
    "expected_profit_change": ("预计利润变化", "Expected profit change"),
    "expected_revenue_change": ("预计收入变化", "Expected revenue change"),
    "antecedent_name": ("买了", "Bought"),
    "consequent_name": ("也买了", "Also bought"),
    "pair_orders": ("共同订单", "Joint orders"),
    "confidence": ("连带率", "Confidence"),
    "lift": ("提升度", "Lift"),
}


def _show_answer(answer: QueryAnswer) -> None:
    st.markdown(f"**{answer.title}**")
    st.write(answer.answer)
    if not answer.data.empty:
        names = {key: tr(*label) for key, label in COLUMN_LABELS.items()}
        st.dataframe(answer.data.round(3).rename(columns=names), hide_index=True)
    if answer.supported:
        st.caption(f"{answer.methodology}  ({answer.query_id})")
    else:
        for item in answer.suggestions:
            st.markdown(f"- {item}")


def render() -> None:
    filters = sidebar_filters(DEFAULT_DB_PATH)
    language = current_language()
    page_header(
        t("page.assistant.title"),
        tr(
            "用日常语言提问。每个回答都来自已审核的指标，并写明计算方法；答不了的问题会直接说明。",
            "Ask in plain language. Every answer comes from governed metrics and states its "
            "method; questions outside them are declined rather than guessed.",
        ),
        meta=period_meta(filters),
    )
    history: list[dict] = st.session_state.setdefault(HISTORY, [])
    labels = {question_label(item, language): item for item in SUPPORTED_QUESTIONS}
    picked = st.pills(
        tr("常见问题", "Common questions"),
        list(labels),
        selection_mode="single",
        key="assistant_pick",
    )
    typed = st.chat_input(tr("输入你的经营问题", "Type a business question"))
    question = typed or (labels.get(picked) if picked else None)
    if question and (not history or history[-1]["question"] != question):
        history.append(
            {
                "question": question_label(question, language),
                "answer": answer_business_question(
                    DEFAULT_DB_PATH, filters, question, language=language
                ),
            }
        )
    if not history:
        note(tr("选一个常见问题，或在下方直接输入。", "Pick a common question, or type your own below."))
    for turn in history[-6:]:
        with st.chat_message("user", avatar=USER_ICON):
            st.write(turn["question"])
        with st.chat_message("assistant", avatar=ASSISTANT_ICON):
            _show_answer(turn["answer"])
