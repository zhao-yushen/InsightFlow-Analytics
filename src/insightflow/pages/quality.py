from __future__ import annotations

import plotly.express as px
import streamlit as st

from insightflow.i18n import lt, t
from insightflow.config import DEFAULT_DB_PATH, DEFAULT_RAW_PATH, is_read_only
from insightflow.etl import clean_transactions, load_source
from insightflow.fault_injection import FaultPlan, inject_faults
from insightflow.metrics import data_lineage, quality_dimensions, quality_score, quality_summary
from insightflow.provenance import dataset_profile, metric_trust_table, trust_label
from insightflow.ui import page_header, sidebar_filters
from insightflow.warehouse import query_df


def render() -> None:
    page_header(
        t("page.quality.title"),
        t("page.quality.desc"),
        eyebrow="TRUST CENTER",
    )
    sidebar_filters(DEFAULT_DB_PATH)
    profile = dataset_profile(DEFAULT_DB_PATH)
    st.subheader(lt("数据资产状态"))
    score = quality_score(DEFAULT_DB_PATH)
    cols = st.columns(5)
    cols[0].metric(lt("质量得分"), f"{score:.1f}/100")
    cols[1].metric(lt("整体模式"), trust_label(str(profile.get("data_mode", "Mixed"))))
    cols[2].metric(lt("交易数据"), trust_label(str(profile.get("transaction_status", "Mixed"))))
    cols[3].metric(lt("成本数据"), trust_label(str(profile.get("economic_status", "Mixed"))))
    cols[4].metric(lt("库存数据"), trust_label(str(profile.get("inventory_status", "Mixed"))))
    st.caption(str(profile.get("source_note", "")))
    dims = quality_dimensions(DEFAULT_DB_PATH)
    st.plotly_chart(
        px.bar(dims, x="dimension", y="score_100", text_auto=".1f", range_y=[0, 100]),
        use_container_width=True,
    )

    tabs = st.tabs([lt("契约问题"), lt("质量指标"), lt("指标可信度"), lt("数据血缘"), lt("ETL运行"), lt("故障演练")])
    with tabs[0]:
        contract = query_df(DEFAULT_DB_PATH, "SELECT * FROM data_contract_issues")
        if set(contract["severity"]) == {"PASS"}:
            st.success(lt("当前数据通过全部契约检查。"))
        st.dataframe(contract, use_container_width=True, hide_index=True)
        st.caption(lt("数据契约覆盖必要字段、业务主键、类型、数值范围、枚举值和未来日期。"))
    with tabs[1]:
        st.dataframe(quality_summary(DEFAULT_DB_PATH), use_container_width=True, hide_index=True)
    with tabs[2]:
        trust = metric_trust_table(DEFAULT_DB_PATH)
        if not trust.empty:
            trust["confidence"] = trust["confidence"].map(lambda value: f"{value:.0%}")
        st.dataframe(trust, use_container_width=True, hide_index=True)
    with tabs[3]:
        st.dataframe(data_lineage(DEFAULT_DB_PATH), use_container_width=True, hide_index=True)
    with tabs[4]:
        runs = query_df(DEFAULT_DB_PATH, "SELECT * FROM etl_runs ORDER BY run_at DESC LIMIT 50")
        st.dataframe(runs, use_container_width=True, hide_index=True)
    with tabs[5]:
        st.markdown(lt("通过故意注入重复、缺失、负价格、未来日期、未知渠道和缺失月份，验证质量体系是否真的能发现问题。"))
        sample_size = st.select_slider(lt("演练样本量"), options=[1000, 3000, 5000, 10000], value=3000)
        read_only = is_read_only()
        if read_only:
            st.info(lt("只读访客模式已禁用故障演练。该演练虽不写入正式仓库，但会执行数据处理任务。"))
        if st.button(lt("运行故障注入演练"), type="primary", disabled=read_only):
            source = load_source(DEFAULT_RAW_PATH).head(sample_size)
            corrupted = inject_faults(source, FaultPlan(remove_month=True))
            result = clean_transactions(corrupted, source_profile="fault_injection_demo", transaction_status="Simulated")
            left, right = st.columns(2)
            with left:
                st.metric(lt("原始样本"), f"{len(source):,}")
                st.metric(lt("故障后样本"), f"{len(corrupted):,}")
            with right:
                st.metric(lt("演练质量得分"), f"{result.quality_dimensions['score_100'].mean():.1f}/100")
                st.metric(lt("契约问题数"), int((result.contract_issues["severity"] != "PASS").sum()))
            st.dataframe(result.contract_issues, use_container_width=True, hide_index=True)
            st.dataframe(result.quality_summary, use_container_width=True, hide_index=True)
            st.info(lt("演练只在内存中运行，不会污染正式仓库。"))
