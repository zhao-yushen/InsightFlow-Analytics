from __future__ import annotations

import json
import os
from collections.abc import Iterable

from .diagnostics import DiagnosticIssue


def deterministic_executive_summary(
    issues: Iterable[DiagnosticIssue], language: str = "zh-CN"
) -> str:
    items = list(issues)
    if not items:
        return (
            "当前范围的样本太小，暂不下结论。"
            if language == "zh-CN"
            else "The sample in this scope is too small to draw a conclusion."
        )
    high = [x for x in items if x.severity in {"P0", "P1"}]
    lead = high[0] if high else items[0]
    others = items[1:4]
    if language == "zh-CN":
        lines = [
            f"本期最值得关注的问题是：{lead.title}。{lead.finding}",
            f"关键证据：{lead.evidence}",
            f"建议行动：{lead.recommendation}",
        ]
        if others:
            lines.append("其他关注事项包括：" + "；".join(x.title for x in others) + "。")
    else:
        lines = [
            f"The main issue this period: {lead.title}. {lead.finding}",
            f"Evidence: {lead.evidence}",
            f"Next step: {lead.recommendation}",
        ]
        if others:
            lines.append("Also watch: " + "; ".join(x.title for x in others) + ".")
    return "\n\n".join(lines)


def openai_executive_summary(
    issues: Iterable[DiagnosticIssue], model: str | None = None, language: str = "zh-CN"
) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        payload = [x.to_dict() for x in issues]
        response = client.responses.create(
            model=model or os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            input=[
                {
                    "role": "system",
                    "content": (
                        "你是企业经营分析师。只根据提供的诊断证据，写一份不超过250字的中文管理层摘要。"
                        "区分事实、推断和建议，不得虚构数字。"
                        if language == "zh-CN"
                        else "You are a business analyst. Using only the diagnostic evidence "
                        "provided, write an executive summary of at most 120 words. Separate "
                        "facts, inferences and recommendations, and never invent a number."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            store=False,
        )
        return response.output_text.strip()
    except Exception:
        return None


def executive_summary(
    issues: Iterable[DiagnosticIssue], language: str = "zh-CN"
) -> tuple[str, str]:
    items = list(issues)
    ai = openai_executive_summary(items, language=language)
    if ai:
        return ai, "OpenAI Responses API"
    engine = "规则引擎" if language == "zh-CN" else "Rules engine"
    return deterministic_executive_summary(items, language), engine
