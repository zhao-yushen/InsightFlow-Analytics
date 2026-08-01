from __future__ import annotations

import streamlit as st

from insightflow.config import DEFAULT_DB_PATH
from insightflow.i18n import current_language, lt, t
from insightflow.query_assistant import (
    SUPPORTED_QUESTIONS,
    answer_business_question,
    question_label,
)
from insightflow.ui import page_header, sidebar_filters


def render() -> None:
    page_header(
        t("page.assistant.title"),
        t("page.assistant.desc"),
        eyebrow="ASK INSIGHTFLOW",
    )
    filters = sidebar_filters(DEFAULT_DB_PATH)
    with st.container(border=True):
        st.markdown(f"#### {lt('提出经营问题')}")
        st.caption(lt("助手只调用已审核的指标与只读查询模板，不生成任意写入 SQL。"))
        preset = st.selectbox(
            lt("快速选择"),
            SUPPORTED_QUESTIONS,
            format_func=lambda value: question_label(value, current_language()),
        )
        question = st.text_input(
            lt("自然语言问题"), value=preset, placeholder=lt("例如：为什么最近一个月贡献利润下降？")
        )
        analyze = st.button(lt("生成可验证分析"), type="primary", use_container_width=True)
    if analyze:
        result = answer_business_question(
            DEFAULT_DB_PATH, filters, question, language=current_language()
        )
        with st.container(border=True):
            st.markdown(f"#### {result.title}")
            st.write(result.answer)
            st.caption(
                f"{lt('查询编号：')}{result.query_id}{lt('｜方法：')}{result.methodology}"
                f"{lt('｜期间：')}{filters.start_date}{lt(' 至 ')}{filters.end_date}"
            )
            st.dataframe(result.data.round(3), use_container_width=True, hide_index=True)
