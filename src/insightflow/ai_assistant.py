from __future__ import annotations

import json
import os
from typing import Iterable

from .diagnostics import DiagnosticIssue


def deterministic_executive_summary(issues: Iterable[DiagnosticIssue]) -> str:
    items = list(issues)
    high = [x for x in items if x.severity in {"P0", "P1"}]
    lead = high[0] if high else items[0]
    lines = [
        f"本期最值得关注的问题是：{lead.title}。{lead.finding}",
        f"关键证据：{lead.evidence}",
        f"建议行动：{lead.recommendation}",
    ]
    if len(items) > 1:
        lines.append("其他关注事项包括：" + "；".join(x.title for x in items[1:4]) + "。")
    return "\n\n".join(lines)


def openai_executive_summary(issues: Iterable[DiagnosticIssue], model: str | None = None) -> str | None:
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
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            store=False,
        )
        return response.output_text.strip()
    except Exception:
        return None


def executive_summary(issues: Iterable[DiagnosticIssue]) -> tuple[str, str]:
    items = list(issues)
    ai = openai_executive_summary(items)
    if ai:
        return ai, "OpenAI Responses API"
    return deterministic_executive_summary(items), "规则引擎"
