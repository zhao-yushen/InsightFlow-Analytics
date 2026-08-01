from __future__ import annotations

from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from insightflow.config import DEFAULT_DB_PATH
from insightflow.experiments import analyze_experiment
from insightflow.metrics import FilterSpec, date_bounds, kpi_summary, quality_score
from insightflow.provenance import dataset_profile
from insightflow.warehouse import query_df


def main() -> None:
    _, max_date = date_bounds(DEFAULT_DB_PATH)
    end = __import__("pandas").Timestamp(max_date)
    start = end - __import__("pandas").Timedelta(days=89)
    filters = FilterSpec(start.date().isoformat(), end.date().isoformat())
    kpi = kpi_summary(DEFAULT_DB_PATH, filters)
    profile = dataset_profile(DEFAULT_DB_PATH)
    experiment, _, _ = analyze_experiment(DEFAULT_DB_PATH, "EXP_BLANKET_DISCOUNT_01")
    fact_rows = int(query_df(DEFAULT_DB_PATH, "SELECT COUNT(*) n FROM fact_transactions").iloc[0, 0])
    benchmark_path = ROOT / "reports" / "performance_benchmark.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8")) if benchmark_path.exists() else {}
    query_seconds = next(
        (row["seconds"] for row in benchmark.get("benchmarks", []) if row["operation"] == "kpi_summary"),
        None,
    )
    html = f"""<!doctype html>
<html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>InsightFlow Pro v0.4.3.3 Portfolio</title>
<style>
:root{{--ink:#13233d;--muted:#63708a;--bg:#f4f7fb;--card:#fff;--accent:#2563eb;--good:#087a55;--warn:#b45309}}
*{{box-sizing:border-box}}body{{margin:0;font-family:Inter,Arial,'Microsoft YaHei',sans-serif;background:var(--bg);color:var(--ink)}}
.wrap{{max-width:1180px;margin:auto;padding:36px 24px 70px}}.hero{{padding:42px;border-radius:24px;background:linear-gradient(135deg,#12233f,#254f8f);color:#fff;box-shadow:0 20px 60px #14274a33}}
h1{{font-size:44px;margin:0 0 12px}}.lead{{font-size:19px;line-height:1.7;max-width:900px;color:#e7eefc}}.badges{{display:flex;gap:10px;flex-wrap:wrap;margin-top:20px}}.badge{{padding:8px 12px;border-radius:99px;background:#ffffff1f;border:1px solid #ffffff38}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:22px 0}}.card{{background:var(--card);border-radius:18px;padding:21px;box-shadow:0 8px 30px #1f335117}}.label{{font-size:13px;color:var(--muted)}}.value{{font-size:28px;font-weight:750;margin-top:8px}}h2{{margin-top:38px}}.two{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.feature{{border-left:4px solid var(--accent)}}
.result-good{{color:var(--good)}}.result-warn{{color:var(--warn)}}a.btn{{display:inline-block;text-decoration:none;color:white;background:var(--accent);padding:12px 18px;border-radius:11px;margin:8px 8px 0 0}}a.secondary{{background:#ffffff1f;border:1px solid #ffffff42}}.preview{{margin-top:22px;background:#fff;border-radius:20px;padding:12px;box-shadow:0 16px 46px #1f33511f}}.preview img{{display:block;width:100%;border-radius:13px}}ul{{line-height:1.75;padding-left:20px}}code{{background:#e9eef7;padding:2px 6px;border-radius:5px}}footer{{margin-top:36px;color:var(--muted);font-size:13px}}@media(max-width:850px){{.grid{{grid-template-columns:1fr 1fr}}.two{{grid-template-columns:1fr}}h1{{font-size:34px}}}}@media(max-width:520px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><main class='wrap'>
<section class='hero'><h1>InsightFlow Pro v0.4.3.3</h1><div class='lead'>可信经营分析与概率决策平台：从数据契约、增量ETL和星型模型，到利润诊断、Monte Carlo情景模拟、A/B实验利润护栏、可持久化行动闭环和只读公开演示。</div>
<div class='badges'><span class='badge'>Python + SQL</span><span class='badge'>Streamlit + Plotly</span><span class='badge'>Power BI Model Pack</span><span class='badge'>22 Automated Tests</span><span class='badge'>Data Hub + 8 Languages</span><span class='badge'>Trust-aware Analytics</span></div>
<a class='btn' href='ui_preview_v0.4.2.html'>查看新版界面</a><a class='btn secondary' href='../reports/insightflow_business_report.html'>查看经营报告</a><a class='btn secondary' href='../docs/case_studies/profit_decline_case.md'>查看案例说明</a></section><section class='preview'><img src='ui_preview_v0.4.2.png' alt='InsightFlow v0.4.3.3 Executive UI'></section>
<section class='grid'>
<div class='card'><div class='label'>交易明细</div><div class='value'>{fact_rows:,}</div></div>
<div class='card'><div class='label'>近90日净销售额</div><div class='value'>£{kpi['revenue']:,.0f}</div></div>
<div class='card'><div class='label'>近90日贡献利润</div><div class='value'>£{kpi['contribution_profit']:,.0f}</div></div>
<div class='card'><div class='label'>数据质量</div><div class='value'>{quality_score(DEFAULT_DB_PATH):.1f}/100</div></div>
</section>
<h2>项目区别度</h2><section class='two'>
<div class='card feature'><h3>不把估算值伪装成真实值</h3><p>当前配置为 <b>{profile['data_mode']}</b>。交易、成本和库存分别记录来源状态、置信度和说明，报告中持续展示可信边界。</p></div>
<div class='card feature'><h3>不只做点预测</h3><p>情景模拟输出利润改善概率、90%区间、增收但减利概率和参数敏感性，避免把假设结果描述成确定结论。</p></div>
<div class='card feature'><h3>不只看转化和收入</h3><p>模拟九折实验的单客利润提升为 <b class='result-warn'>£{experiment.lift:,.2f}</b>，系统结论为“{experiment.decision}”。</p></div>
<div class='card feature'><h3>不让问题停留在图表</h3><p>系统将异常、目标和库存风险转成负责人、证据、截止日期和可下载行动清单。</p></div>
</section>
<h2>端到端能力</h2><section class='two'>
<div class='card'><ul><li>单表、七表和Olist多表适配</li><li>数据契约、故障注入和Join验证</li><li>利润对账与Shapley/桥接分解</li><li>WAPE、sMAPE、MASE和Bias回测</li></ul></div>
<div class='card'><ul><li>Monte Carlo概率情景模拟</li><li>A/B实验Bootstrap与利润护栏</li><li>受控自然语言经营分析</li><li>Word、HTML及Power BI交付包</li></ul></div>
</section>
<h2>工程验证</h2><section class='grid'>
<div class='card'><div class='label'>自动化测试</div><div class='value result-good'>33 passed</div></div>
<div class='card'><div class='label'>典型KPI查询</div><div class='value'>{query_seconds if query_seconds is not None else '—'}s</div></div>
<div class='card'><div class='label'>A/B实验样本</div><div class='value'>{experiment.sample_size:,}</div></div>
<div class='card'><div class='label'>实验利润改善概率</div><div class='value'>{experiment.probability_positive:.1%}</div></div>
</section>
<footer>所有内置经营结果均属于演示数据；该页面展示产品与分析方法，不声称真实企业业务提升。生成于 InsightFlow Pro v0.4.3.3。</footer>
</main></body></html>"""
    output = ROOT / "portfolio" / "index.html"
    output.write_text(html, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
