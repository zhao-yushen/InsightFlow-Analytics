from __future__ import annotations

import streamlit as st

from insightflow.config import DEFAULT_DB_PATH, is_read_only
from insightflow.etl import clean_transactions
from insightflow.fault_injection import FaultPlan, inject_faults
from insightflow.i18n import t, tr
from insightflow.live import gauge_strip
from insightflow.metrics import data_lineage, quality_dimensions, quality_score, quality_summary
from insightflow.provenance import dataset_profile, metric_trust_table, trust_label
from insightflow.ui import (
    gauge_item,
    note,
    page_header,
    section_header,
    sidebar_filters,
    subhead,
    trust_sentence,
    verdict,
)
from insightflow.viz import lineage_sankey, ranked_bars, show
from insightflow.warehouse import query_df

DRILL_COLUMNS = (
    "invoice_no, stock_code, description, category, quantity, invoice_date, "
    "unit_price, customer_id, country, channel"
)
DIMENSION_EN = {
    "完整性": "Completeness",
    "唯一性": "Uniqueness",
    "有效性": "Validity",
    "一致性": "Consistency",
    "覆盖度": "Coverage",
    "契约符合度": "Contract",
}


def _status(profile: dict, key: str) -> str:
    status = str(profile.get(key, "Mixed"))
    return tr(trust_label(status), status)


def render() -> None:
    sidebar_filters(DEFAULT_DB_PATH)
    profile = dataset_profile(DEFAULT_DB_PATH)
    score = quality_score(DEFAULT_DB_PATH)
    contract = query_df(DEFAULT_DB_PATH, "SELECT * FROM data_contract_issues")
    failing = contract[contract["severity"] != "PASS"]
    page_header(
        t("page.quality.title"),
        tr(
            f"综合质量 {score:.1f}/100，数据契约发现 {len(failing)} 类问题。",
            f"Overall quality is {score:.1f}/100, with {len(failing)} kinds of contract issue.",
        ),
        meta=trust_sentence(DEFAULT_DB_PATH),
    )
    gauge_strip(
        [
            gauge_item(tr("质量得分", "Quality score"), score, "count", f"{score:.1f}", note_text="/100"),
            gauge_item(tr("交易数据", "Transactions"), 0, "count", _status(profile, "transaction_status"), note_text=""),
            gauge_item(tr("成本数据", "Costs"), 0, "count", _status(profile, "economic_status"), note_text=""),
            gauge_item(tr("库存数据", "Inventory"), 0, "count", _status(profile, "inventory_status"), note_text=""),
        ],
        key="quality_gauges",
    )

    section_header(tr("质量维度", "Quality dimensions"))
    dimensions = quality_dimensions(DEFAULT_DB_PATH)
    dimensions["dimension"] = dimensions["dimension"].map(
        lambda name: tr(name, DIMENSION_EN.get(name, name))
    )
    show(
        ranked_bars(dimensions, label="dimension", value="score_100"),
        key="quality_dimensions",
    )

    tabs = st.tabs(
        [
            tr("契约问题", "Contract issues"),
            tr("指标可信度", "Metric trust"),
            tr("数据血缘", "Lineage"),
            tr("质量明细", "Quality detail"),
            tr("导入记录", "Import runs"),
            tr("故障演练", "Fault drill"),
        ]
    )
    with tabs[0]:
        if failing.empty:
            verdict(tr("全部通过", "All passed"), tr("当前数据通过全部契约检查。", "The current data passes every contract check."), "good")
        st.dataframe(contract, hide_index=True)
        note(
            tr(
                "校验在任何估算或修正之前进行，所以越界的折扣和成本不会被悄悄改掉。",
                "Checks run before any estimate or correction, so out-of-range discounts and costs "
                "are never silently altered.",
            )
        )
    with tabs[1]:
        trust = metric_trust_table(DEFAULT_DB_PATH)
        st.dataframe(
            trust,
            hide_index=True,
            column_config={
                "confidence": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="percent")
            },
        )
        note(
            tr(
                "指标的可信度取决于最弱的输入，并按行数加权。仓库混入多种来源时显示为混合。",
                "A metric is rated by its weakest input and weighted by rows. Warehouses with "
                "several sources read as Mixed.",
            )
        )
    with tabs[2]:
        show(lineage_sankey(data_lineage(DEFAULT_DB_PATH)), key="quality_lineage")
    with tabs[3]:
        st.dataframe(quality_summary(DEFAULT_DB_PATH), hide_index=True)
    with tabs[4]:
        runs = query_df(DEFAULT_DB_PATH, "SELECT * FROM etl_runs ORDER BY run_at DESC LIMIT 50")
        st.dataframe(runs, hide_index=True)
    with tabs[5]:
        subhead(tr("验证质量体系能否发现问题", "Prove the checks catch real problems"))
        note(
            tr(
                "向样本中注入重复、缺失、负价格、未来日期、未知渠道和缺失月份。只在内存中运行，不影响正式仓库。",
                "Injects duplicates, gaps, negative prices, future dates, unknown channels and a "
                "missing month. Runs in memory and never touches the warehouse.",
            )
        )
        sample_size = st.select_slider(
            tr("演练样本量", "Sample size"), options=[1000, 3000, 5000, 10000], value=3000
        )
        read_only = is_read_only()
        if read_only:
            st.info(tr("只读模式下不能运行演练。", "Drills are disabled in read-only mode."))
        if st.button(tr("运行演练", "Run drill"), type="primary", disabled=read_only):
            # Sampling the warehouse keeps the drill working after a user replaces the demo.
            source = query_df(
                DEFAULT_DB_PATH,
                f"""
                SELECT {DRILL_COLUMNS} FROM fact_transactions
                WHERE data_valid = 1 ORDER BY record_hash LIMIT ?
                """,
                (sample_size,),
            )
            corrupted = inject_faults(source, FaultPlan(remove_month=True))
            result = clean_transactions(
                corrupted, source_profile="fault_injection_demo", transaction_status="Simulated"
            )
            gauge_strip(
                [
                    gauge_item(tr("原始样本", "Original rows"), len(source), "count", f"{len(source):,}", note_text=""),
                    gauge_item(tr("故障后样本", "After faults"), len(corrupted), "count", f"{len(corrupted):,}", note_text=""),
                    gauge_item(tr("演练质量得分", "Drill quality"), result.quality_dimensions["score_100"].mean(), "count", f"{result.quality_dimensions['score_100'].mean():.1f}", note_text="/100"),
                    gauge_item(tr("发现的问题", "Issues found"), int((result.contract_issues["severity"] != "PASS").sum()), "count", str(int((result.contract_issues["severity"] != "PASS").sum())), note_text=""),
                ],
                key="quality_drill",
            )
            st.dataframe(result.contract_issues, hide_index=True)
