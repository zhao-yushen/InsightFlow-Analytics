from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from insightflow.backup import KEEP_BACKUPS, create_backup, list_backups, restore_backup
from insightflow.config import DEFAULT_DB_PATH, INCOMING_DIR, is_read_only
from insightflow.currency import SYMBOLS, warehouse_currency
from insightflow.etl import NON_MERCHANDISE, ETLResult, clean_transactions
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
from insightflow.narrative import rejection_table
from insightflow.provenance import dataset_profile
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
REJECTED_COLUMNS = [
    "reject_reason",
    "invoice_no",
    "stock_code",
    "description",
    "quantity",
    "invoice_date",
    "unit_price",
    "customer_id",
    "country",
    "channel",
]


def _read_upload(name: str, content: bytes) -> tuple[str, pd.DataFrame]:
    """Read a file once. Widget changes rerun the page, and a large workbook takes a minute."""
    digest = hashlib.sha256(content).hexdigest()
    held = st.session_state.get("import_frame")
    if held and held[0] == digest:
        return digest, held[1]
    with st.spinner(tr("正在读取文件，大文件可能需要一分钟……", "Reading the file. Large files can take a minute.")):
        frame = read_table(content, name)
    st.session_state["import_frame"] = (digest, frame)
    return digest, frame


def _prepare_import(
    frame: pd.DataFrame,
    digest: str,
    mapping: dict[str, str],
    default_country: str,
    file_code: str,
    target_code: str,
    rates: dict[str, float],
) -> tuple[ETLResult, list[str], bytes]:
    """Clean the file once per set of choices, so ticking a box does not redo the work."""
    key = (
        digest,
        tuple(sorted(mapping.items())),
        default_country,
        file_code,
        target_code,
        tuple(sorted(rates.items())),
    )
    held = st.session_state.get("import_result")
    if held and held[0] == key:
        return held[1], held[2], held[3]
    with st.spinner(tr("正在清洗和校验数据……", "Cleaning and checking the data.")):
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
        held_back = result.rejected[REJECTED_COLUMNS].to_csv(index=False).encode("utf-8-sig")
    st.session_state["import_result"] = (key, result, notes, held_back)
    return result, notes, held_back


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
        digest, frame = _read_upload(uploaded.name, uploaded.getvalue())
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
    # The first real file must not land on top of the demo, where every total would be a
    # silent blend of real and simulated rows.
    on_demo = str(dataset_profile(DEFAULT_DB_PATH).get("transaction_status")) == "Simulated"
    with right:
        replace = st.toggle(
            tr("替换仓库全部数据", "Replace the whole warehouse"),
            value=on_demo,
            help=t("data.replace_warning"),
            key="import_replace",
        )
        load_mode = "replace" if replace else "append"
        if on_demo:
            st.caption(
                tr(
                    "当前仓库是演示数据，默认替换，避免真实数据和模拟数据混在一起。",
                    "The warehouse holds demo data, so this replaces it by default and keeps real "
                    "and simulated rows apart.",
                )
            )
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

    result, notes, held_back = _prepare_import(
        frame, digest, mapping, default_country, file_code, target_code, rates
    )
    blockers = result.block_reasons()
    problems = result.problem_rows
    services = int((result.curated["reject_reason"] == NON_MERCHANDISE).sum())
    warnings = int((result.contract_issues["severity"] == "P2").sum())
    score = float(result.quality_dimensions["score_100"].mean())

    subhead(tr("导入前检查", "Pre-import check"))
    gauge_strip(
        [
            gauge_item(tr("文件行数", "Rows in file"), len(frame), "count", f"{len(frame):,}", note_text=""),
            gauge_item(tr("有效销售行", "Valid sales rows"), result.metadata["valid_sales_rows"], "count", f"{result.metadata['valid_sales_rows']:,}", note_text=""),
            gauge_item(tr("问题行", "Problem rows"), problems, "count", f"{problems:,}", note_text=f"{result.problem_share:.2%}"),
            gauge_item(tr("非商品行", "Non-merchandise"), services, "count", f"{services:,}", note_text=tr("运费、手续费等", "Postage, fees")),
            gauge_item(tr("质量得分", "Quality score"), score, "count", f"{score:.1f}", note_text="/100"),
        ],
        key="data_hub_precheck",
    )
    for item in notes:
        st.caption(item)
    if result.metadata["category_source"] == "derived":
        st.caption(
            tr(
                "文件没有品类字段，已按商品名称里的名词自动归为商品族。",
                "The file has no category field, so products were grouped into families by the "
                "nouns in their names.",
            )
        )
    if blockers:
        verdict(tr("不能导入", "Cannot import"), "；".join(blockers), "bad")
        st.dataframe(result.contract_issues, hide_index=True)
    elif problems:
        verdict(
            tr("需要你确认", "Needs your decision"),
            tr(
                f"{problems:,} 行不符合规则。它们会保留在仓库里备查，但不计入任何指标。",
                f"{problems:,} rows break the rules. They stay in the warehouse for audit but "
                "count toward no metric.",
            ),
            "warning",
        )
    elif warnings:
        verdict(
            tr("可以导入", "Ready to import"),
            tr(f"有 {warnings} 项提示，不影响导入。", f"{warnings} notes; these do not block import."),
            "warning",
        )
    else:
        verdict(tr("可以导入", "Ready to import"), tr("数据通过全部契约检查。", "All contract checks passed."), "good")
    if not result.rejected.empty:
        st.dataframe(rejection_table(result.rejection_summary(), target_code), hide_index=True)
        st.download_button(
            tr("下载这些行", "Download these rows"),
            held_back,
            file_name="insightflow_rows_held_back.csv",
            mime="text/csv",
        )
    with st.expander(tr("预览清洗结果", "Preview cleaned data")):
        st.dataframe(result.curated.head(100), hide_index=True)

    if read_only:
        st.info(t("data.read_only"))
    if replace:
        st.warning(t("data.replace_warning"))
    agreed = True
    if problems and not blockers:
        agreed = st.checkbox(
            tr(f"隔离这 {problems:,} 行，继续导入", f"Set these {problems:,} rows aside and continue"),
            key="import_isolate",
        )
    if st.button(
        tr("确认导入", "Import data"),
        type="primary",
        disabled=read_only or bool(blockers) or not agreed,
    ):
        try:
            with st.spinner(tr("正在备份并写入仓库……", "Backing up and writing to the warehouse.")):
                create_backup(DEFAULT_DB_PATH)
                stats = build_warehouse(
                    result, DEFAULT_DB_PATH, load_mode=load_mode, source_name=uploaded.name
                )
        except ValueError as error:
            st.error(str(error))
            return
        st.cache_data.clear()
        for key in (
            "global_analysis_period",
            "import_result",
            "import_frame",
            "import_isolate",
            "import_replace",
        ):
            st.session_state.pop(key, None)
        if load_mode == "replace":
            for key in ("filter_regions", "filter_countries", "filter_categories", "filter_channels"):
                st.session_state.pop(key, None)
        st.success(t("data.imported", inserted=stats["inserted_rows"], skipped=stats["skipped_rows"]))
        st.rerun()


def _backup_section(read_only: bool) -> None:
    section_header(
        tr("备份与恢复", "Backups"),
        tr(f"每次导入前自动备份，保留最近 {KEEP_BACKUPS} 份", f"Taken before every import; the last {KEEP_BACKUPS} are kept"),
    )
    backups = list_backups(DEFAULT_DB_PATH)
    if not backups:
        note(tr("还没有备份。第一次导入前会自动创建。", "No backups yet. One is made before the first import."))
        return
    labels = {
        path.name: f"{path.name[12:16]}-{path.name[16:18]}-{path.name[18:20]} "
        f"{path.name[21:23]}:{path.name[23:25]}:{path.name[25:27]} UTC, "
        f"{path.stat().st_size / 1_048_576:,.0f} MB"
        for path in backups
    }
    chosen = st.selectbox(tr("选择备份", "Backup"), list(labels), format_func=labels.get)
    agreed = st.checkbox(
        tr("我知道当前仓库会被这份备份替换（替换前会再存一份）", "Replace the current warehouse with this backup (it is saved first)"),
        key="restore_agreed",
    )
    if st.button(tr("恢复这份备份", "Restore this backup"), disabled=read_only or not agreed):
        with st.spinner(tr("正在恢复……", "Restoring.")):
            restore_backup(chosen, DEFAULT_DB_PATH)
        st.cache_data.clear()
        st.session_state.pop("global_analysis_period", None)
        st.session_state.pop("restore_agreed", None)
        st.rerun()


def render() -> None:
    sidebar_filters(DEFAULT_DB_PATH)
    read_only = is_read_only()
    code = warehouse_currency(DEFAULT_DB_PATH)
    rows = int(query_df(DEFAULT_DB_PATH, "SELECT COUNT(*) FROM fact_transactions").iloc[0, 0])
    first_day, last_day = date_bounds(DEFAULT_DB_PATH)
    counts = filter_option_counts(DEFAULT_DB_PATH)
    page_header(
        t("page.data_hub.title"),
        tr(
            f"仓库现有 {rows:,} 行交易，覆盖 {first_day} 至 {last_day}，报告币种 {code}。",
            f"The warehouse holds {rows:,} transaction rows from {first_day} to {last_day}, "
            f"reported in {code}.",
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
    _backup_section(read_only)

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
