from __future__ import annotations

import pandas as pd
import streamlit as st

from insightflow.config import DEFAULT_DB_PATH, INCOMING_DIR, is_read_only
from insightflow.currency import SYMBOLS, warehouse_currency
from insightflow.data_contracts import blocking_contract_issues
from insightflow.etl import clean_transactions
from insightflow.i18n import t, tr
from insightflow.ingest import (
    SUPPORTED_SUFFIXES,
    apply_mapping,
    missing_required,
    read_table,
    suggest_mapping,
)
from insightflow.live import gauge_strip
from insightflow.metrics import date_bounds, filter_option_counts
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
from insightflow.warehouse import build_warehouse, database_version, query_df
from insightflow.watcher import scan_once

CORE_FIELDS = {
    "invoice_no": ("订单号", "Order number"),
    "stock_code": ("商品编码", "Product code"),
    "description": ("商品名称", "Product name"),
    "quantity": ("数量", "Quantity"),
    "invoice_date": ("下单时间", "Order date"),
    "unit_price": ("单价", "Unit price"),
    "line_amount": ("行金额（无单价时使用）", "Line amount (if no unit price)"),
    "country": ("国家", "Country"),
}
OPTIONAL_FIELDS = {
    "customer_id": ("客户", "Customer"),
    "category": ("品类", "Category"),
    "channel": ("渠道", "Channel"),
    "order_status": ("订单状态", "Order status"),
    "discount_rate": ("折扣率", "Discount rate"),
    "unit_cost": ("单位成本", "Unit cost"),
    "shipping_cost": ("运费", "Shipping cost"),
    "payment_fee": ("支付手续费", "Payment fee"),
    "marketing_cost": ("营销费用", "Marketing cost"),
    "inventory_on_hand": ("库存", "Stock on hand"),
    "supplier": ("供应商", "Supplier"),
    "currency": ("币种", "Currency"),
}
NOT_MAPPED = "—"


@st.cache_data(show_spinner=False, max_entries=8)
def _read_upload(name: str, content: bytes) -> pd.DataFrame:
    return read_table(content, name)


def _template_csv() -> bytes:
    sample = pd.DataFrame(
        [
            {
                "订单号": "INV-0001",
                "商品编码": "SKU-0001",
                "商品名称": "保温杯",
                "品类": "Kitchen",
                "数量": 2,
                "下单时间": "2025-08-01 10:30:00",
                "单价": 29.90,
                "客户ID": "CUST-0001",
                "国家": "中国",
                "渠道": "Mobile App",
                "成本": 15.20,
                "折扣率": 0.05,
            }
        ]
    )
    return sample.to_csv(index=False).encode("utf-8-sig")


def _mapping_controls(frame: pd.DataFrame) -> dict[str, str]:
    """Show each field with the column it was matched to, editable by the user."""
    suggested = suggest_mapping(frame)
    options = [NOT_MAPPED, *map(str, frame.columns)]
    mapping: dict[str, str] = {}

    def picker(field: str, label: str) -> None:
        match = suggested.get(field)
        index = options.index(match.column) if match else 0
        help_text = None
        if match and match.confidence < 1.0:
            help_text = tr(
                f"自动匹配，置信度 {match.confidence:.0%}，请确认。",
                f"Matched automatically at {match.confidence:.0%} confidence. Please confirm.",
            )
        chosen = st.selectbox(label, options, index=index, key=f"map_{field}", help=help_text)
        if chosen != NOT_MAPPED:
            mapping[field] = chosen

    columns = st.columns(4)
    for index, (field, (chinese, english)) in enumerate(CORE_FIELDS.items()):
        with columns[index % 4]:
            picker(field, tr(chinese, english))
    with st.expander(tr("可选字段：提供后可减少估算", "Optional fields: each one replaces an estimate")):
        columns = st.columns(4)
        for index, (field, (chinese, english)) in enumerate(OPTIONAL_FIELDS.items()):
            with columns[index % 4]:
                picker(field, tr(chinese, english))
    low = [item for item in suggested.values() if item.confidence < 0.8]
    if low:
        note(
            tr(
                f"有 {len(low)} 个字段是按相似度或数值特征匹配的，导入前请确认。",
                f"{len(low)} fields were matched by similarity or by their values. Confirm before importing.",
            )
        )
    return mapping


def _upload_flow(read_only: bool, warehouse_code: str) -> None:
    section_header(tr("导入数据", "Import data"))
    note(
        tr(
            "支持 CSV、TSV、Excel、Parquet 和 JSON，能读取 GBK 编码、中文表头和带货币符号的数字。",
            "CSV, TSV, Excel, Parquet and JSON are supported, including GBK encoding, Chinese "
            "headers and numbers with currency symbols.",
        )
    )
    uploaded = st.file_uploader(
        t("data.upload"),
        type=[suffix.lstrip(".") for suffix in sorted(SUPPORTED_SUFFIXES)],
        label_visibility="collapsed",
    )
    st.download_button(
        tr("下载导入模板", "Download import template"),
        _template_csv(),
        file_name="insightflow_input_template.csv",
        mime="text/csv",
    )
    if uploaded is None:
        return
    try:
        frame = _read_upload(uploaded.name, uploaded.getvalue())
    except Exception as error:
        st.error(tr(f"无法读取文件：{error}", f"Could not read the file: {error}"))
        return

    subhead(tr("确认字段对应关系", "Confirm the field mapping"))
    mapping = _mapping_controls(frame)
    gaps = missing_required(mapping)
    if gaps:
        names = [tr(*CORE_FIELDS.get(gap, (gap, gap))) for gap in gaps]
        st.error(tr(f"还缺少：{'、'.join(names)}", f"Still missing: {', '.join(names)}"))
        return

    subhead(tr("补充信息", "Details"))
    codes = sorted(SYMBOLS)
    left, middle, right = st.columns(3)
    with left:
        default_country = st.text_input(
            tr("文件没有国家字段时使用", "Country if the file has none"),
            value=tr("中国", "China"),
            disabled="country" in mapping,
        )
    with middle:
        file_code = st.selectbox(
            tr("文件币种", "File currency"),
            codes,
            index=codes.index(warehouse_code) if warehouse_code in codes else 0,
        )
    load_mode = "append"
    with right:
        replace = st.toggle(
            tr("替换仓库全部数据", "Replace the whole warehouse"),
            help=t("data.replace_warning"),
        )
        load_mode = "replace" if replace else "append"
    target_code = file_code if replace else warehouse_code
    rates: dict[str, float] = {}
    if file_code != target_code:
        rate = st.number_input(
            tr(f"1 {file_code} 等于多少 {target_code}", f"1 {file_code} equals how many {target_code}"),
            min_value=0.0,
            value=1.0,
            step=0.01,
            format="%.4f",
        )
        rates[file_code] = rate

    canonical, notes = apply_mapping(frame, mapping, default_country=default_country)
    if "currency" not in canonical:
        canonical["currency"] = file_code
    result = clean_transactions(
        canonical,
        source_profile="web_incremental_import",
        transaction_status="Verified",
        currency=target_code,
        fx_rates=rates,
    )
    blocking = blocking_contract_issues(result.contract_issues)
    warnings = int((result.contract_issues["severity"] == "P2").sum())
    score = float(result.quality_dimensions["score_100"].mean())

    subhead(tr("导入前检查", "Pre-import check"))
    gauge_strip(
        [
            gauge_item(tr("文件行数", "Rows in file"), len(frame), "count", f"{len(frame):,}", note_text=""),
            gauge_item(tr("有效销售行", "Valid sales rows"), result.metadata["valid_sales_rows"], "count", f"{result.metadata['valid_sales_rows']:,}", note_text=""),
            gauge_item(tr("质量得分", "Quality score"), score, "count", f"{score:.1f}", note_text="/100"),
            gauge_item(tr("阻断问题", "Blocking issues"), len(blocking), "count", f"{len(blocking)}", note_text=""),
        ],
        key="data_hub_precheck",
    )
    for item in notes:
        st.caption(item)
    if not blocking.empty:
        verdict(
            tr("不能导入", "Cannot import"),
            tr("下列问题必须先在源文件中修复。", "Fix the issues below in the source file first."),
            "bad",
        )
        st.dataframe(result.contract_issues, hide_index=True)
    elif warnings:
        verdict(
            tr("可以导入", "Ready to import"),
            tr(f"有 {warnings} 项未登记类别的提示，不影响导入。", f"{warnings} unregistered-category notes; these do not block import."),
            "warning",
        )
    else:
        verdict(tr("可以导入", "Ready to import"), tr("数据通过全部契约检查。", "All contract checks passed."), "good")
    with st.expander(tr("预览清洗结果", "Preview cleaned data")):
        st.dataframe(result.curated.head(100), hide_index=True)

    if read_only:
        st.info(t("data.read_only"))
    if replace:
        st.warning(t("data.replace_warning"))
    if st.button(
        tr("确认导入", "Import data"),
        type="primary",
        disabled=read_only or not blocking.empty,
    ):
        try:
            stats = build_warehouse(
                result, DEFAULT_DB_PATH, load_mode=load_mode, source_name=uploaded.name
            )
        except ValueError as error:
            st.error(str(error))
            return
        st.cache_data.clear()
        st.session_state.pop("global_analysis_period", None)
        if load_mode == "replace":
            for key in ("filter_regions", "filter_countries", "filter_categories", "filter_channels"):
                st.session_state.pop(key, None)
        st.success(t("data.imported", inserted=stats["inserted_rows"], skipped=stats["skipped_rows"]))
        st.rerun()


def render() -> None:
    sidebar_filters(DEFAULT_DB_PATH)
    read_only = is_read_only()
    code = warehouse_currency(DEFAULT_DB_PATH)
    total = query_df(
        DEFAULT_DB_PATH,
        "SELECT COUNT(*) AS rows, MIN(date) AS min_date, MAX(date) AS max_date FROM fact_transactions",
    ).iloc[0]
    counts = filter_option_counts(DEFAULT_DB_PATH)
    page_header(
        t("page.data_hub.title"),
        tr(
            f"仓库现有 {int(total['rows']):,} 行交易，覆盖 {total['min_date']} 至 {total['max_date']}，报告币种 {code}。",
            f"The warehouse holds {int(total['rows']):,} transaction rows from {total['min_date']} to "
            f"{total['max_date']}, reported in {code}.",
        ),
        meta=trust_sentence(DEFAULT_DB_PATH),
    )
    gauge_strip(
        [
            gauge_item(tr("市场", "Markets"), len(counts["countries"]), "count", str(len(counts["countries"])), note_text=""),
            gauge_item(tr("品类", "Categories"), len(counts["categories"]), "count", str(len(counts["categories"])), note_text=""),
            gauge_item(tr("渠道", "Channels"), len(counts["channels"]), "count", str(len(counts["channels"])), note_text=""),
        ],
        key="data_hub_gauges",
    )
    _upload_flow(read_only, code)

    section_header(tr("监听文件夹", "Watched folder"), tr("文件放入后自动导入", "Files dropped here import automatically"))
    st.code(f"insightflow watch --interval 30\n# {INCOMING_DIR}", language="powershell")
    left, right = st.columns(2)
    with left:
        if st.button(tr("立即扫描一次", "Scan once now"), disabled=read_only, width="stretch"):
            results = scan_once(DEFAULT_DB_PATH)
            if results:
                st.dataframe(pd.DataFrame(results), hide_index=True)
                st.cache_data.clear()
            else:
                note(tr(f"{INCOMING_DIR} 中没有可导入的文件。", f"No files to import in {INCOMING_DIR}."))
    with right:
        if st.button(t("data.refresh"), width="stretch"):
            st.cache_data.clear()
            st.rerun()

    section_header(tr("导入历史", "Import history"))
    history = query_df(
        DEFAULT_DB_PATH,
        "SELECT run_at, source_name, load_mode, inserted_rows, skipped_rows FROM etl_runs ORDER BY run_at DESC LIMIT 50",
    )
    st.dataframe(history, hide_index=True)
    st.caption(
        f"{tr('版本', 'Version')} {database_version(DEFAULT_DB_PATH)[0]} "
        f"{tr('数据范围', 'Range')} {date_bounds(DEFAULT_DB_PATH)}"
    )
