from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt
from jinja2 import Template

from .ai_assistant import executive_summary
from .config import DEFAULT_CURRENCY
from .currency import money
from .diagnostics import DiagnosticIssue

HTML_TEMPLATE = Template(
    """
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>InsightFlow 经营分析报告</title>
<style>
:root{--ink:#0F2747;--soft:#4A6283;--line:#D9E2EE;--flow:#0E8C7E;--profit:#B57F00;--leak:#C8483A}
*{box-sizing:border-box}
body{font-family:"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:#fff;color:var(--ink);margin:0;line-height:1.65}
main{max-width:1040px;margin:0 auto;padding:40px 24px 64px}
h1{font-size:32px;line-height:1.2;letter-spacing:-.02em;margin:0}
h2{font-size:19px;margin:0 0 12px;padding-top:18px;border-top:1px solid var(--line)}
section{margin-top:32px}
.meta{color:var(--soft);font-size:14px;margin:10px 0 0}
.summary{white-space:pre-wrap;font-size:16px;margin:20px 0 0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin-top:28px}
.kpi{padding:14px 12px 14px 0}
.label{font-size:13px;color:var(--soft)}
.value{font-size:24px;font-weight:600;letter-spacing:-.02em}
.issue{padding:12px 0;border-bottom:1px solid var(--line);break-inside:avoid}
.issue b{display:block}
.issue .level{font-size:13px;color:var(--soft)}
.issue p{margin:4px 0 0;font-size:14px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 10px 8px 0;border-bottom:1px solid var(--line);text-align:left;font-variant-numeric:tabular-nums}
th{color:var(--soft);font-weight:500}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:32px}
svg{display:block;width:100%;height:auto}
.legend{font-size:13px;color:var(--soft);margin-top:6px}
.legend i{display:inline-block;width:14px;height:2px;vertical-align:middle;margin:0 6px 0 14px}
.legend i:first-child{margin-left:0}
@media(max-width:760px){.grid{grid-template-columns:1fr}main{padding:24px 16px}}
@media print{main{padding:0;max-width:none}section{break-inside:avoid}}
</style></head><body><main>
<h1>InsightFlow 经营分析与决策报告</h1>
<p class="meta">分析期间：{{ period }}。生成时间：{{ generated_at }}。摘要来源：{{ summary_engine }}。</p>
<p class="meta">{{ data_profile }}</p>
<div class="summary">{{ summary }}</div>
<div class="kpis">{% for label,value in kpis %}<div class="kpi"><div class="label">{{ label }}</div><div class="value">{{ value }}</div></div>{% endfor %}</div>
<section><h2>月度趋势</h2>{{ trend_chart }}</section>
<section><h2>关键诊断与行动</h2>{% for issue in issues %}<div class="issue"><span class="level">{{ issue.severity }}</span><b>{{ issue.title }}</b><p>{{ issue.finding }}</p><p>证据：{{ issue.evidence }}</p><p>建议：{{ issue.recommendation }}</p></div>{% endfor %}</section>
<div class="grid"><section><h2>收入变化驱动</h2>{{ drivers_table }}</section><section><h2>利润变化驱动</h2>{{ profit_table }}</section></div>
<div class="grid"><section><h2>目标状态</h2>{{ targets_table }}</section><section><h2>未来预测</h2>{{ forecast_table }}</section></div>
<div class="grid"><section><h2>库存风险</h2>{{ inventory_table }}</section><section><h2>数据质量</h2>{{ quality_table }}</section></div>
<section><h2>月度明细</h2>{{ trend_table }}</section>
</main></body></html>
"""
)


def format_kpis(kpi: dict[str, float], currency: str = DEFAULT_CURRENCY) -> list[tuple[str, str]]:
    return [
        ("净销售额", money(kpi["revenue"], currency)),
        ("毛利润", money(kpi.get("gross_profit", 0), currency)),
        ("毛利率", f"{kpi.get('gross_margin', 0):.1%}"),
        ("贡献利润", money(kpi.get("contribution_profit", 0), currency)),
        ("贡献利润率", f"{kpi.get('contribution_margin', 0):.1%}"),
        ("退款", money(kpi.get("returns_value", 0), currency)),
        ("订单量", f"{kpi['orders']:,.0f}"),
        ("活跃客户", f"{kpi['active_customers']:,.0f}"),
        ("复购率", f"{kpi['repeat_rate']:.1%}"),
        ("退货取消率", f"{kpi['cancellation_rate']:.1%}"),
    ]


def trend_svg(trend: pd.DataFrame) -> str:
    """Draw the revenue and profit trend as inline SVG so the report stays self-contained."""
    data = trend.tail(18)
    if len(data) < 2 or "revenue" not in data:
        return "<p class='meta'>月份不足，暂无趋势图。</p>"
    width, height, pad = 960, 220, 8
    top = max(float(data["revenue"].max()), 1.0)
    low = min(float(data["contribution_profit"].min()), 0.0)

    def points(column: str) -> str:
        coordinates = []
        for index, value in enumerate(data[column].astype(float)):
            x = pad + index * (width - 2 * pad) / (len(data) - 1)
            y = height - pad - (value - low) / (top - low) * (height - 2 * pad)
            coordinates.append(f"{x:.1f},{y:.1f}")
        return " ".join(coordinates)

    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="净销售额与贡献利润月度趋势">'
        f'<line x1="{pad}" x2="{width - pad}" y1="{height - pad}" y2="{height - pad}" stroke="#D9E2EE"/>'
        f'<polyline points="{points("revenue")}" fill="none" stroke="#0E8C7E" stroke-width="2"/>'
        f'<polyline points="{points("contribution_profit")}" fill="none" stroke="#B57F00" stroke-width="2"/>'
        "</svg>"
        f'<div class="legend"><i style="background:#0E8C7E"></i>净销售额'
        f'<i style="background:#B57F00"></i>贡献利润'
        f"（{data['month'].iloc[0]} 至 {data['month'].iloc[-1]}）</div>"
    )


def present_drivers(drivers: pd.DataFrame) -> pd.DataFrame:
    labels = {
        "driver": "驱动因素",
        "previous": "上期",
        "current": "本期",
        "change": "变化",
        "revenue_contribution": "净销售额贡献",
    }
    columns = [c for c in labels if c in drivers.columns]
    return drivers[columns].rename(columns=labels).copy()


def present_targets(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    labels = {
        "target_period": "期间",
        "metric_id": "指标",
        "actual_value": "实际值",
        "target_value": "目标值",
        "attainment": "完成度",
        "status": "状态",
        "owner": "负责人",
    }
    metrics = {
        "net_revenue": "净销售额",
        "contribution_profit": "贡献利润",
        "gross_margin": "毛利率",
        "cancellation_rate": "取消率",
    }
    out = df[[c for c in labels if c in df.columns]].rename(columns=labels).copy()
    if "指标" in out:
        out["指标"] = out["指标"].map(metrics).fillna(out["指标"])
    if "完成度" in out:
        out["完成度"] = out["完成度"].map(lambda x: f"{x:.1%}" if pd.notna(x) else "")
    return out


def present_forecast(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    labels = {"month": "月份", "forecast": "预测值", "lower": "区间下限", "upper": "区间上限"}
    return df[[c for c in labels if c in df.columns]].rename(columns=labels).copy()


def present_inventory(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    labels = {
        "stock_code": "SKU",
        "description": "商品",
        "category": "品类",
        "supplier": "供应商",
        "supplier_lead_days": "提前期",
        "inventory_on_hand": "现有库存",
        "avg_daily_units": "日均销量",
        "days_of_supply": "可售天数",
        "inventory_value": "库存价值",
    }
    return df[[c for c in labels if c in df.columns]].rename(columns=labels).copy()


def present_quality(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    labels = {"dimension": "质量维度", "score_100": "得分", "description": "说明"}
    return df[[c for c in labels if c in df.columns]].rename(columns=labels).copy()


def present_trend(df: pd.DataFrame) -> pd.DataFrame:
    labels = {
        "month": "月份",
        "revenue": "净销售额",
        "gross_profit": "毛利润",
        "contribution_profit": "贡献利润",
        "orders": "订单",
        "active_customers": "活跃客户",
        "cancellation_rate": "退货取消率",
    }
    return df[[c for c in labels if c in df.columns]].tail(12).rename(columns=labels).copy()


def _safe_table(df: pd.DataFrame | None, empty_text: str = "暂无数据") -> str:
    if df is None or df.empty:
        return f"<p class='meta'>{empty_text}</p>"
    return df.round(3).to_html(index=False, border=0)


def build_markdown_report(
    period: str,
    kpi: dict[str, float],
    issues: list[DiagnosticIssue],
    drivers: pd.DataFrame,
    *,
    targets: pd.DataFrame | None = None,
    forecast: pd.DataFrame | None = None,
    data_profile: str | None = None,
    currency: str = DEFAULT_CURRENCY,
) -> str:
    summary, engine = executive_summary(issues)
    lines = [
        "# InsightFlow 经营周报",
        "",
        f"- 分析期间：{period}",
        f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M}",
        f"- 摘要引擎：{engine}",
        f"- 数据状态：{data_profile or '未提供来源标签'}",
        "",
        "## 管理层摘要",
        "",
        summary,
        "",
        "## 核心指标",
        "",
    ]
    for label, value in format_kpis(kpi, currency):
        lines.append(f"- **{label}**：{value}")
    lines.extend(["", "## 关键诊断", ""])
    for issue in issues:
        lines.extend(
            [
                f"### {issue.severity}｜{issue.title}",
                "",
                issue.finding,
                "",
                f"**证据：** {issue.evidence}",
                "",
                f"**建议：** {issue.recommendation}",
                "",
            ]
        )
    lines.extend(["## 收入变化驱动", "", present_drivers(drivers).to_markdown(index=False), ""])
    if targets is not None and not targets.empty:
        lines.extend(["## 目标状态", "", targets.to_markdown(index=False), ""])
    if forecast is not None and not forecast.empty:
        lines.extend(["## 未来预测", "", forecast.to_markdown(index=False), ""])
    return "\n".join(lines)


def render_html_report(
    period: str,
    kpi: dict[str, float],
    issues: list[DiagnosticIssue],
    drivers: pd.DataFrame,
    trend: pd.DataFrame,
    *,
    profit_table: pd.DataFrame | None = None,
    targets: pd.DataFrame | None = None,
    forecast: pd.DataFrame | None = None,
    inventory: pd.DataFrame | None = None,
    quality: pd.DataFrame | None = None,
    data_profile: str | None = None,
    currency: str = DEFAULT_CURRENCY,
) -> str:
    summary, engine = executive_summary(issues)
    return HTML_TEMPLATE.render(
        period=period,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        summary_engine=engine,
        summary=summary,
        data_profile=data_profile or "未提供来源标签",
        kpis=format_kpis(kpi, currency),
        issues=issues,
        drivers_table=_safe_table(present_drivers(drivers)),
        profit_table=_safe_table(profit_table),
        targets_table=_safe_table(present_targets(targets)),
        forecast_table=_safe_table(present_forecast(forecast)),
        inventory_table=_safe_table(present_inventory(inventory)),
        quality_table=_safe_table(present_quality(quality)),
        trend_table=_safe_table(present_trend(trend)),
        trend_chart=trend_svg(trend),
    )


def build_html_report(
    output_path: str | Path,
    period: str,
    kpi: dict[str, float],
    issues: list[DiagnosticIssue],
    drivers: pd.DataFrame,
    trend: pd.DataFrame,
    **kwargs,
) -> Path:
    html = render_html_report(period, kpi, issues, drivers, trend, **kwargs)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output


def _add_df_table(doc: Document, df: pd.DataFrame, *, max_rows: int = 20) -> None:
    shown = df.head(max_rows).copy()
    if shown.empty:
        doc.add_paragraph("暂无数据。")
        return
    table = doc.add_table(rows=1, cols=len(shown.columns))
    table.style = "Table Grid"
    for idx, col in enumerate(shown.columns):
        table.rows[0].cells[idx].text = str(col)
    for _, row in shown.iterrows():
        cells = table.add_row().cells
        for idx, value in enumerate(row):
            if isinstance(value, float):
                cells[idx].text = f"{value:,.3f}"
            else:
                cells[idx].text = str(value)
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(8)


def _create_word_report(
    period: str,
    kpi: dict[str, float],
    issues: list[DiagnosticIssue],
    drivers: pd.DataFrame,
    *,
    targets: pd.DataFrame | None = None,
    forecast: pd.DataFrame | None = None,
    inventory: pd.DataFrame | None = None,
    quality: pd.DataFrame | None = None,
    data_profile: str | None = None,
    currency: str = DEFAULT_CURRENCY,
) -> Document:
    summary, engine = executive_summary(issues)
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.65)
    section.bottom_margin = Inches(0.65)
    section.left_margin = Inches(0.7)
    section.right_margin = Inches(0.7)
    title = doc.add_heading("InsightFlow 经营分析与决策报告", 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    meta = doc.add_paragraph(
        f"分析期间：{period}｜生成时间：{datetime.now():%Y-%m-%d %H:%M}｜摘要引擎：{engine}"
    )
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    trust = doc.add_paragraph(f"数据状态：{data_profile or '未提供来源标签'}")
    trust.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_heading("一、管理层摘要", level=1)
    doc.add_paragraph(summary)

    doc.add_heading("二、核心经营指标", level=1)
    kpi_table = doc.add_table(rows=1, cols=3)
    kpi_table.style = "Table Grid"
    kpi_table.rows[0].cells[0].text = "指标"
    kpi_table.rows[0].cells[1].text = "数值"
    kpi_table.rows[0].cells[2].text = "经营含义"
    meanings = {
        "净销售额": "商品毛额扣除折扣和退款",
        "毛利润": "净销售额扣除商品成本",
        "毛利率": "商品结构与采购成本质量",
        "贡献利润": "进一步扣除物流、支付、营销和退货处理费用",
        "贡献利润率": "规模增长是否真正创造利润",
        "退款": "退货与取消退还的金额",
        "订单量": "交易规模",
        "活跃客户": "产生有效购买的客户数",
        "复购率": "客户质量与收入可持续性",
        "退货取消率": "退货或取消单数占销售订单的比例",
    }
    for label, value in format_kpis(kpi, currency):
        cells = kpi_table.add_row().cells
        cells[0].text = label
        cells[1].text = value
        cells[2].text = meanings.get(label, "")

    doc.add_heading("三、关键诊断与行动建议", level=1)
    for issue in issues:
        doc.add_heading(f"{issue.severity}｜{issue.title}", level=2)
        doc.add_paragraph(issue.finding)
        doc.add_paragraph(f"证据：{issue.evidence}")
        doc.add_paragraph(f"建议：{issue.recommendation}")

    doc.add_heading("四、收入变化驱动", level=1)
    _add_df_table(doc, present_drivers(drivers))

    if targets is not None:
        doc.add_heading("五、目标完成状态", level=1)
        _add_df_table(doc, present_targets(targets))
    if forecast is not None:
        doc.add_heading("六、未来预测", level=1)
        _add_df_table(doc, present_forecast(forecast))
    if inventory is not None:
        doc.add_heading("七、库存风险", level=1)
        _add_df_table(doc, present_inventory(inventory), max_rows=15)
    if quality is not None:
        doc.add_heading("八、数据质量", level=1)
        _add_df_table(doc, present_quality(quality))

    doc.add_heading("九、管理行动清单", level=1)
    for issue in issues:
        doc.add_paragraph(issue.recommendation, style="List Bullet")

    doc.add_heading("十、核心指标口径", level=1)
    definitions = [
        "净销售额：商品毛额减折扣，再减退款。",
        "毛利润：净销售额减商品成本。",
        "贡献利润：毛利润减物流、支付手续费、营销费用和退货处理成本。",
        "复购率：期间内订单数不少于2笔的客户占购买客户比例。",
        "收入驱动：采用Shapley方法，将收入变化分解为活跃客户、购买频次和客单价贡献。",
        "预测：在多个时序模型中通过滚动回测选择误差最低模型，并给出不确定区间。",
        "退货：退货是对原销售的反向记录，商品回库比例可通过配置调整。",
    ]
    for item in definitions:
        doc.add_paragraph(item, style="List Bullet")

    return doc


def build_word_report(
    output_path: str | Path,
    period: str,
    kpi: dict[str, float],
    issues: list[DiagnosticIssue],
    drivers: pd.DataFrame,
    **kwargs,
) -> Path:
    doc = _create_word_report(period, kpi, issues, drivers, **kwargs)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output)
    return output


def build_word_report_bytes(
    period: str,
    kpi: dict[str, float],
    issues: list[DiagnosticIssue],
    drivers: pd.DataFrame,
    **kwargs,
) -> bytes:
    doc = _create_word_report(period, kpi, issues, drivers, **kwargs)
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
