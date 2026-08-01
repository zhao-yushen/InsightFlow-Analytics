from pathlib import Path

import pandas as pd

from insightflow.diagnostics import DiagnosticIssue
from insightflow.reporting import build_html_report, build_markdown_report, build_word_report


def test_reports_are_created(tmp_path: Path):
    issue = DiagnosticIssue("P1", "test", "测试问题", "发现", "证据", "建议", 0.9)
    drivers = pd.DataFrame([{"driver": "活跃客户数", "revenue_contribution": -100}])
    trend = pd.DataFrame([{"month": "2025-01", "revenue": 1000}])
    kpi = {"revenue": 1000, "orders": 10, "active_customers": 8, "average_order_value": 100, "repeat_rate": 0.4, "cancellation_rate": 0.02}
    md = build_markdown_report("2025-01", kpi, [issue], drivers)
    assert "测试问题" in md
    html = build_html_report(tmp_path / "report.html", "2025-01", kpi, [issue], drivers, trend)
    docx = build_word_report(tmp_path / "report.docx", "2025-01", kpi, [issue], drivers)
    assert html.exists() and html.stat().st_size > 0
    assert docx.exists() and docx.stat().st_size > 0
