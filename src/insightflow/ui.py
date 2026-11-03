from __future__ import annotations

import hmac
import os
import time
from datetime import date, timedelta
from html import escape
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from . import __version__
from .config import CACHE_TTL_SECONDS, DEFAULT_DB_PATH, is_read_only
from .currency import money, symbol, warehouse_currency
from .demo_data import write_demo_csv
from .design import COLORS, GLOBAL_CSS, SEVERITY, STATUS, configure_plotly
from .etl import SCHEMA_VERSION, clean_transactions, load_source
from .geography import country_label, region_label
from .i18n import LANGUAGES, base_period, current_language, language_name, t, tr
from .metrics import (
    FilterSpec,
    available_filters,
    date_bounds,
    filter_coverage,
    filter_dimension_counts,
    filter_option_counts,
)
from .provenance import dataset_profile, trust_label
from .warehouse import build_warehouse, database_version, table_exists, warehouse_schema_version

COMPARE_BASES = ("previous", "year")
SHARED_SCOPES = (
    ("regions", "filter_regions", "region"),
    ("countries", "filter_countries", "country"),
    ("categories", "filter_categories", "category"),
    ("channels", "filter_channels", "channel"),
)


def apply_design_system() -> None:
    configure_plotly()
    st.html(GLOBAL_CSS)


def require_access() -> None:
    """Hold the app behind a shared code when INSIGHTFLOW_ACCESS_CODE is set.

    This is a simple door for a small team, not user accounts. Anything facing the open
    internet still belongs behind HTTPS and a real identity provider.
    """
    expected = os.getenv("INSIGHTFLOW_ACCESS_CODE", "").strip()
    if not expected or st.session_state.get("access_granted"):
        return
    st.html(f'<h1 class="if-page-title">{escape(tr("请输入访问码", "Enter the access code"))}</h1>')
    with st.form("access_form"):
        code = st.text_input(tr("访问码", "Access code"), type="password")
        submitted = st.form_submit_button(tr("进入", "Enter"), type="primary")
    if submitted:
        if hmac.compare_digest(code.strip().encode(), expected.encode()):
            st.session_state["access_granted"] = True
            st.rerun()
        # A short pause makes guessing a code by hand or by script impractical.
        time.sleep(1)
        st.error(tr("访问码不正确。", "That code is not correct."))
    st.stop()


def page_header(title: str, lede: str, *, meta: str | None = None) -> None:
    meta_html = f'<div class="if-page-meta">{meta}</div>' if meta else ""
    st.html(
        f"""
        <h1 class="if-page-title">{escape(title)}</h1>
        <p class="if-page-lede">{escape(lede)}</p>
        {meta_html}
        """
    )


def section_header(title: str, note: str | None = None) -> None:
    note_html = f'<div class="if-section-note">{escape(note)}</div>' if note else ""
    st.html(
        f'<div class="if-section"><div class="if-section-title">{escape(title)}</div>{note_html}</div>'
    )


def subhead(text: str) -> None:
    st.html(f'<div class="if-subhead">{escape(text)}</div>')


def note(text: str) -> None:
    st.html(f'<div class="if-note">{escape(text)}</div>')


def signal(severity: str, title: str, body: str) -> None:
    """One finding in a ledger. Severity is written out so colour never carries it alone."""
    level = SEVERITY.get(severity, COLORS["muted"])
    st.html(
        f"""
        <div class="if-signal" style="--level:{level}">
          <div class="if-signal-level"><i></i>{escape(severity)}</div>
          <div>
            <div class="if-signal-title">{escape(title)}</div>
            <div class="if-signal-body">{escape(body)}</div>
          </div>
        </div>
        """
    )


VERDICT_TONES = {
    "good": STATUS["good"],
    "warning": STATUS["warning"],
    "bad": STATUS["critical"],
    "neutral": COLORS["muted"],
}


def verdict(label: str, detail: str, tone: str = "neutral") -> None:
    color = VERDICT_TONES.get(tone, COLORS["muted"])
    st.html(
        f'<div class="if-verdict" style="--tone:{color}"><b>{escape(label)}</b>'
        f"<span>{escape(detail)}</span></div>"
    )


def currency_code(db_path: Path = DEFAULT_DB_PATH) -> str:
    return warehouse_currency(db_path)


def money_prefix(db_path: Path = DEFAULT_DB_PATH) -> str:
    return symbol(currency_code(db_path))


def fmt_money(value: float, *, short: bool = False, db_path: Path = DEFAULT_DB_PATH) -> str:
    return money(float(value), currency_code(db_path), short=short)


def table_view(frame: pd.DataFrame, label: str | None = None, **options: Any) -> None:
    """Keep every chart's numbers readable without the chart."""
    with st.expander(label or tr("查看数据表", "View data table")):
        st.dataframe(frame, hide_index=True, **options)


def gauge_item(
    label: str,
    raw: float,
    kind: str,
    display: str,
    *,
    current: float | None = None,
    previous: float | None = None,
    up_is_good: bool = True,
    comparable: bool = True,
    spark: list[float] | None = None,
    note_text: str | None = None,
    prefix: str = "",
) -> dict[str, Any]:
    """Describe one gauge. Rates compare in points; amounts compare in percent."""
    delta, tone = "", "neutral"
    if current is not None and previous is not None and comparable:
        if kind == "percent":
            change = current - previous
            delta = f"{change * 100:+.1f}{tr(' 个百分点', ' pts')}"
        else:
            change = (current - previous) / abs(previous) if previous else 0.0
            delta = f"{change:+.1%}" if previous else ""
        if abs(change) > 1e-9 and delta:
            tone = "good" if (change > 0) == up_is_good else "bad"
    return {
        "label": label,
        "raw": float(raw),
        "kind": kind,
        "display": display,
        "symbol": prefix,
        "delta": delta,
        "tone": tone,
        "note": (
            note_text
            if note_text is not None
            else (tr(f"较{base_period()}", f"on {base_period()}") if delta else "")
        ),
        "spark": [float(value) for value in (spark or [])],
    }


def ensure_demo_warehouse(db_path: Path = DEFAULT_DB_PATH) -> None:
    if table_exists(db_path, "fact_transactions") and table_exists(db_path, "metric_catalog"):
        if warehouse_schema_version(db_path) == SCHEMA_VERSION:
            return
        profile = str(dataset_profile(db_path).get("profile_id", ""))
        if not profile.startswith("demo") or is_read_only():
            raise FileNotFoundError(
                "数据仓库由旧版本创建，指标口径已变化。请重新导入数据，或运行 insightflow bootstrap。"
            )
    if is_read_only():
        raise FileNotFoundError(
            "当前为只读模式，但数据仓库不存在。请先运行 python scripts/bootstrap.py，"
            "或将 INSIGHTFLOW_READ_ONLY=false 后初始化。"
        )
    from .config import DEFAULT_RAW_PATH

    with st.spinner(tr("首次启动，正在生成演示数据，约需 15 秒。", "First run: building demo data, about 15 seconds.")):
        source = write_demo_csv(DEFAULT_RAW_PATH)
        result = clean_transactions(
            load_source(source),
            source_profile="demo_generated",
            transaction_status="Simulated",
        )
        build_warehouse(result, db_path)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _cached_sidebar_metadata(
    db_path: str,
    version: tuple[int, int, int, int],
) -> tuple[
    tuple[str, str],
    dict[str, list[str]],
    dict[str, dict[str, int]],
    dict[str, object],
]:
    del version
    return (
        date_bounds(db_path),
        available_filters(db_path),
        filter_option_counts(db_path),
        dataset_profile(db_path),
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _cached_dimension_counts(
    db_path: str,
    version: tuple[int, int, int, int],
    start_date: str,
    end_date: str,
    regions: tuple[str, ...],
    countries: tuple[str, ...],
    categories: tuple[str, ...],
    channels: tuple[str, ...],
    dimension: str,
) -> dict[str, int]:
    del version
    return filter_dimension_counts(
        db_path,
        FilterSpec(
            start_date=start_date,
            end_date=end_date,
            regions=regions,
            countries=countries,
            categories=categories,
            channels=channels,
        ),
        dimension,
    )


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _cached_filter_coverage(
    db_path: str,
    version: tuple[int, int, int, int],
    start_date: str,
    end_date: str,
    regions: tuple[str, ...],
    countries: tuple[str, ...],
    categories: tuple[str, ...],
    channels: tuple[str, ...],
) -> dict[str, object]:
    del version
    return filter_coverage(
        db_path,
        FilterSpec(
            start_date=start_date,
            end_date=end_date,
            regions=regions,
            countries=countries,
            categories=categories,
            channels=channels,
        ),
    )


def render_app_brand() -> None:
    st.logo(str(Path(__file__).resolve().parent / "assets" / "logo.svg"), size="large")


def render_language_selector() -> str:
    codes = list(LANGUAGES)
    current = current_language()
    language = st.sidebar.selectbox(
        "语言 / Language",
        codes,
        index=codes.index(current) if current in codes else 0,
        format_func=language_name,
        key="insightflow_language",
    )
    if language not in {"zh-CN", "en"}:
        st.sidebar.caption(
            "Beta: navigation is localized; analytical narratives use English fallback."
        )
    return str(language)


def _set_filter_state(key: str, values: list[str]) -> None:
    st.session_state[key] = list(values)


def _sanitize_filter_state(key: str, options: list[str]) -> None:
    current = st.session_state.get(key)
    if current is None:
        return
    st.session_state[key] = [value for value in current if value in options]


def _trust_display(status: str) -> str:
    return trust_label(status) if current_language() == "zh-CN" else status


def _restore_shared_view(min_day: date, max_day: date) -> None:
    """Open a shared link once per session. Filter values are checked later against the data."""
    if st.session_state.get("shared_view_read"):
        return
    st.session_state["shared_view_read"] = True
    params = st.query_params
    for _, key, name in SHARED_SCOPES:
        values = params.get_all(name)
        if values:
            st.session_state[key] = values
    if params.get("compare") in COMPARE_BASES:
        st.session_state["compare_basis"] = params["compare"]
    try:
        start = date.fromisoformat(params.get("from", ""))
        end = date.fromisoformat(params.get("to", ""))
    except ValueError:
        return
    if min_day <= start <= end <= max_day:
        st.session_state["global_analysis_period"] = (start, end)


def _publish_view(filters: FilterSpec, default_start: date, max_day: date) -> None:
    """Keep the address in step with the filters, so a copied link reopens this view."""
    wanted: dict[str, list[str]] = {}
    if (filters.start_date, filters.end_date) != (default_start.isoformat(), max_day.isoformat()):
        wanted.update({"from": [str(filters.start_date)], "to": [str(filters.end_date)]})
    if filters.compare != "previous":
        wanted["compare"] = [filters.compare]
    for attribute, _, name in SHARED_SCOPES:
        if getattr(filters, attribute):
            wanted[name] = list(getattr(filters, attribute))
    current = {key: st.query_params.get_all(key) for key in st.query_params}
    if current != wanted:
        st.query_params.from_dict(wanted)


def sidebar_filters(db_path: Path = DEFAULT_DB_PATH) -> FilterSpec:
    try:
        ensure_demo_warehouse(db_path)
    except FileNotFoundError as exc:
        st.error(str(exc))
        st.stop()
    (min_date, max_date), _options, _option_counts, profile = _cached_sidebar_metadata(
        str(db_path.resolve()), database_version(db_path)
    )
    render_language_selector()
    st.sidebar.html(f'<div class="if-rail-title">{escape(t("filters.scope"))}</div>')
    max_day = date.fromisoformat(max_date)
    min_day = date.fromisoformat(min_date)
    default_start = max(min_day, max_day - timedelta(days=89))
    _restore_shared_view(min_day, max_day)
    st.session_state.setdefault("global_analysis_period", (default_start, max_day))
    selected = st.sidebar.date_input(
        t("filters.period"),
        min_value=min_day,
        max_value=max_day,
        key="global_analysis_period",
    )
    # While a range is half picked the widget holds one date, or none after being cleared.
    picked = tuple(selected) if isinstance(selected, (tuple, list)) else (selected,)
    start = picked[0] if picked else default_start
    end = picked[-1] if picked else max_day
    st.session_state.setdefault("compare_basis", COMPARE_BASES[0])
    compare = st.sidebar.selectbox(
        tr("对比基准", "Compare with"),
        COMPARE_BASES,
        format_func=lambda basis: (
            tr("去年同期", "Same period last year")
            if basis == "year"
            else tr("上一周期", "Previous period")
        ),
        key="compare_basis",
    )

    db_key = str(db_path.resolve())
    db_version = database_version(db_path)
    start_iso, end_iso = start.isoformat(), end.isoformat()

    # Cascading filter options prevent impossible intersections such as
    # "Greater China + Japan". Option counts reflect the selected date range
    # and the higher-level dimensions, rather than global warehouse totals.
    region_counts = _cached_dimension_counts(
        db_key, db_version, start_iso, end_iso, (), (), (), (), "market_region"
    )
    regions_options = list(region_counts)
    _sanitize_filter_state("filter_regions", regions_options)
    selected_regions = tuple(st.session_state.get("filter_regions", []))

    country_counts = _cached_dimension_counts(
        db_key, db_version, start_iso, end_iso, selected_regions, (), (), (), "country"
    )
    countries_options = list(country_counts)
    _sanitize_filter_state("filter_countries", countries_options)
    selected_countries = tuple(st.session_state.get("filter_countries", []))

    category_counts = _cached_dimension_counts(
        db_key,
        db_version,
        start_iso,
        end_iso,
        selected_regions,
        selected_countries,
        (),
        (),
        "category",
    )
    categories_options = list(category_counts)
    _sanitize_filter_state("filter_categories", categories_options)
    selected_categories = tuple(st.session_state.get("filter_categories", []))

    channel_counts = _cached_dimension_counts(
        db_key,
        db_version,
        start_iso,
        end_iso,
        selected_regions,
        selected_countries,
        selected_categories,
        (),
        "channel",
    )
    channels_options = list(channel_counts)
    _sanitize_filter_state("filter_channels", channels_options)

    with st.sidebar.expander(t("filters.dimensions"), expanded=False):
        st.caption(
            t(
                "filters.summary",
                regions=len(regions_options),
                countries=len(countries_options),
                categories=len(categories_options),
                channels=len(channels_options),
            )
        )
        st.caption(t("filters.logic_help"))
        all_col, clear_col = st.columns(2)
        all_col.button(
            t("filters.select_all"),
            key="filters_select_all",
            width="stretch",
            on_click=lambda: (
                _set_filter_state("filter_regions", regions_options),
                _set_filter_state("filter_countries", countries_options),
                _set_filter_state("filter_categories", categories_options),
                _set_filter_state("filter_channels", channels_options),
            ),
        )
        clear_col.button(
            t("filters.clear"),
            key="filters_clear_all",
            width="stretch",
            on_click=lambda: (
                _set_filter_state("filter_regions", []),
                _set_filter_state("filter_countries", []),
                _set_filter_state("filter_categories", []),
                _set_filter_state("filter_channels", []),
            ),
        )
        regions = st.multiselect(
            t("filters.region"),
            regions_options,
            key="filter_regions",
            format_func=lambda value: (
                f"{region_label(value, current_language())} ({region_counts.get(value, 0):,})"
            ),
        )
        countries = st.multiselect(
            t("filters.country"),
            countries_options,
            key="filter_countries",
            format_func=lambda value: (
                f"{country_label(value, current_language())} ({country_counts.get(value, 0):,})"
            ),
        )
        categories = st.multiselect(
            t("filters.category"),
            categories_options,
            key="filter_categories",
            format_func=lambda value: f"{value} ({category_counts.get(value, 0):,})",
        )
        channels = st.multiselect(
            t("filters.channel"),
            channels_options,
            key="filter_channels",
            format_func=lambda value: f"{value} ({channel_counts.get(value, 0):,})",
        )

    current_filters = FilterSpec(
        start_date=start_iso,
        end_date=end_iso,
        countries=tuple(countries),
        categories=tuple(categories),
        channels=tuple(channels),
        regions=tuple(regions),
        compare=compare,
    )
    _publish_view(current_filters, default_start, max_day)
    coverage = _cached_filter_coverage(
        db_key,
        db_version,
        start_iso,
        end_iso,
        current_filters.regions,
        current_filters.countries,
        current_filters.categories,
        current_filters.channels,
    )
    if int(coverage["orders"]) == 0:
        st.sidebar.error(t("filters.no_match"))
    elif int(coverage["orders"]) < 5:
        st.sidebar.warning(
            t(
                "filters.low_sample",
                rows=int(coverage["rows"]),
                orders=int(coverage["orders"]),
                customers=int(coverage["customers"]),
            )
        )
    else:
        st.sidebar.caption(
            t(
                "filters.coverage",
                rows=int(coverage["rows"]),
                orders=int(coverage["orders"]),
                customers=int(coverage["customers"]),
            )
        )
    mode = t("mode.read_only") if is_read_only() else t("mode.local_edit")
    st.sidebar.html(
        f"""
        <div class="if-rail-title">{escape(t("environment"))}</div>
        <div class="if-rail-status">
          <b>{escape(str(profile.get("profile_name", "Unknown")))}</b><br>
          {escape(t("status.transaction"))} {escape(_trust_display(str(profile.get("transaction_status", "Mixed"))))}<br>
          {escape(t("status.economic"))} {escape(_trust_display(str(profile.get("economic_status", "Mixed"))))}<br>
          {escape(t("status.inventory"))} {escape(_trust_display(str(profile.get("inventory_status", "Mixed"))))}<br>
          {escape(mode)}，v{__version__}
        </div>
        """
    )
    return current_filters


def trust_sentence(db_path: Path = DEFAULT_DB_PATH) -> str:
    """State plainly what the numbers on this page rest on."""
    _, _, _, profile = _cached_sidebar_metadata(str(db_path.resolve()), database_version(db_path))
    mode = str(profile.get("data_mode", "Mixed"))
    if mode == "Simulated":
        return tr(
            "全部为模拟演示数据，不代表任何企业的真实经营结果。",
            "All figures are simulated demo data and describe no real company.",
        )
    transaction = _trust_display(str(profile.get("transaction_status", "Mixed")))
    economic = _trust_display(str(profile.get("economic_status", "Mixed")))
    inventory = _trust_display(str(profile.get("inventory_status", "Mixed")))
    return tr(
        f"交易：{transaction}；成本：{economic}；库存：{inventory}。估算值不是审计数字。",
        f"Transactions: {transaction}. Costs: {economic}. Inventory: {inventory}. "
        "Estimates are not audited figures.",
    )


def period_meta(filters: FilterSpec, db_path: Path = DEFAULT_DB_PATH) -> str:
    scope = sum(
        bool(values)
        for values in (filters.regions, filters.countries, filters.categories, filters.channels)
    )
    scope_text = tr(f"，已筛选 {scope} 个维度", f", {scope} filters on") if scope else ""
    return (
        f"<b>{filters.start_date} {tr('至', 'to')} {filters.end_date}</b>{escape(scope_text)}"
        f"<br>{escape(trust_sentence(db_path))}"
    )
