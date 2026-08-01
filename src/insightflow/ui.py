from __future__ import annotations

from datetime import date, timedelta
from html import escape
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from .config import CACHE_TTL_SECONDS, DEFAULT_DB_PATH, is_read_only
from .demo_data import write_demo_csv
from .etl import clean_transactions, load_source
from .geography import country_label, region_label
from .i18n import LANGUAGES, current_language, language_name, t
from .metrics import (
    FilterSpec,
    available_filters,
    date_bounds,
    filter_coverage,
    filter_dimension_counts,
    filter_option_counts,
)
from .provenance import dataset_profile, trust_label
from .warehouse import build_warehouse, database_version, table_exists

PALETTE = {
    "ink": "#111827",
    "muted": "#667085",
    "line": "#E7ECF3",
    "panel": "#FFFFFF",
    "canvas": "#F5F7FB",
    "navy": "#111A2E",
    "blue": "#5267F8",
    "blue_dark": "#3F51D9",
    "cyan": "#38BDF8",
    "violet": "#8B5CF6",
    "gold": "#D6A84B",
    "orange": "#F59E0B",
    "rose": "#E86C8D",
    "teal": "#2AA79B",
    "danger": "#D95D67",
    "success": "#2B9B72",
}


def _configure_plotly() -> None:
    template = go.layout.Template(
        layout=go.Layout(
            font={
                "family": "Inter, SF Pro Display, PingFang SC, Microsoft YaHei, sans-serif",
                "color": PALETTE["ink"],
                "size": 13,
            },
            colorway=[
                PALETTE["blue"],
                PALETTE["cyan"],
                PALETTE["violet"],
                PALETTE["gold"],
                PALETTE["teal"],
                PALETTE["rose"],
            ],
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin={"l": 36, "r": 22, "t": 34, "b": 36},
            hoverlabel={
                "bgcolor": "#111827",
                "bordercolor": "#111827",
                "font": {"color": "#FFFFFF", "size": 12},
            },
            legend={
                "orientation": "h",
                "yanchor": "bottom",
                "y": 1.02,
                "xanchor": "left",
                "x": 0,
                "title": {"text": ""},
                "font": {"color": PALETTE["muted"], "size": 12},
            },
            xaxis={
                "gridcolor": "#EEF2F7",
                "linecolor": "#DDE3EC",
                "zerolinecolor": "#DDE3EC",
                "tickfont": {"color": PALETTE["muted"]},
                "title": {"font": {"color": PALETTE["muted"]}},
                "automargin": True,
            },
            yaxis={
                "gridcolor": "#EEF2F7",
                "linecolor": "#DDE3EC",
                "zerolinecolor": "#DDE3EC",
                "tickfont": {"color": PALETTE["muted"]},
                "title": {"font": {"color": PALETTE["muted"]}},
                "automargin": True,
            },
            modebar={"bgcolor": "rgba(255,255,255,.85)", "color": "#667085"},
        )
    )
    pio.templates["insightflow"] = template
    pio.templates.default = "insightflow"


_DESIGN_CSS = r"""
<style>
:root {
  --if-ink: #111827;
  --if-muted: #667085;
  --if-line: #E7ECF3;
  --if-canvas: #F5F7FB;
  --if-panel: #FFFFFF;
  --if-navy: #111A2E;
  --if-blue: #5267F8;
  --if-blue-dark: #3F51D9;
  --if-cyan: #38BDF8;
  --if-violet: #8B5CF6;
  --if-gold: #D6A84B;
  --if-success: #2B9B72;
  --if-danger: #D95D67;
  --if-shadow: 0 12px 34px rgba(20, 29, 52, .07);
}
html, body, [class*="css"] {
  font-family: Inter, "SF Pro Display", "PingFang SC", "Microsoft YaHei", sans-serif;
}
.stApp {
  background:
    radial-gradient(circle at 83% -12%, rgba(82,103,248,.10), transparent 27rem),
    radial-gradient(circle at 56% 12%, rgba(56,189,248,.055), transparent 22rem),
    var(--if-canvas);
  color: var(--if-ink);
}
[data-testid="stHeader"] {
  background: rgba(245,247,251,.82);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid rgba(231,236,243,.75);
}
[data-testid="stAppViewContainer"] > .main .block-container {
  max-width: 1540px;
  padding-top: 2.0rem;
  padding-bottom: 4rem;
  padding-left: clamp(1.1rem, 2.4vw, 2.8rem);
  padding-right: clamp(1.1rem, 2.4vw, 2.8rem);
}
[data-testid="stSidebar"] {
  background:
    radial-gradient(circle at 15% 0%, rgba(82,103,248,.23), transparent 17rem),
    linear-gradient(180deg, #111A2E 0%, #0C1324 100%);
  border-right: 1px solid rgba(255,255,255,.06);
}
[data-testid="stSidebar"] * { color: #EAF0FF; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] small { color: #B9C4DB !important; }
[data-testid="stSidebar"] [data-testid="stSidebarNav"] { padding-top: .45rem; }
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a {
  border-radius: 11px;
  margin: .16rem .48rem;
  padding-top: .55rem;
  padding-bottom: .55rem;
  transition: all .16s ease;
}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover {
  background: rgba(255,255,255,.075);
  transform: translateX(2px);
}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] {
  background: linear-gradient(90deg, rgba(82,103,248,.34), rgba(56,189,248,.11));
  box-shadow: inset 3px 0 0 #8EA2FF;
}
[data-testid="stSidebar"] [data-baseweb="select"] > div,
[data-testid="stSidebar"] [data-baseweb="input"] > div,
[data-testid="stSidebar"] input {
  background: rgba(255,255,255,.07) !important;
  border-color: rgba(255,255,255,.10) !important;
  color: #F8FAFF !important;
}
[data-testid="stSidebar"] [data-testid="stExpander"] {
  background: rgba(255,255,255,.035);
  border: 1px solid rgba(255,255,255,.075);
  border-radius: 13px;
}
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.10); }
.if-brand {
  display:flex; align-items:center; gap:.76rem;
  padding:.88rem .92rem .75rem; margin:.2rem .18rem .95rem;
  border:1px solid rgba(255,255,255,.08); border-radius:16px;
  background:linear-gradient(135deg, rgba(255,255,255,.075), rgba(255,255,255,.025));
  box-shadow:0 14px 28px rgba(0,0,0,.13);
}
.if-brand-mark {
  width:37px;height:37px;border-radius:12px;display:grid;place-items:center;
  color:#fff;font-weight:800;font-size:18px;
  background:linear-gradient(145deg,#7285FF,#4C5FEB 56%,#2FB7E9);
  box-shadow:0 8px 18px rgba(82,103,248,.35);
}
.if-brand-name { color:#fff;font-weight:760;font-size:15px;letter-spacing:.01em;line-height:1.15; }
.if-brand-sub { color:#98A7C1;font-size:10px;text-transform:uppercase;letter-spacing:.11em;margin-top:4px; }
.if-sidebar-label { color:#75849E;font-size:10px;font-weight:700;letter-spacing:.13em;text-transform:uppercase;margin:.5rem .25rem .25rem; }
.if-sidebar-status {
  padding:.7rem .76rem;border:1px solid rgba(255,255,255,.075);border-radius:12px;
  background:rgba(255,255,255,.035);font-size:11px;line-height:1.65;color:#AEBBD1;
}
.if-page-head {
  display:flex;justify-content:space-between;align-items:flex-end;gap:1.5rem;
  padding:.2rem 0 1.28rem;margin-bottom:.35rem;
}
.if-eyebrow { color:#5267F8;font-size:11px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;margin-bottom:.42rem; }
.if-page-title { margin:0;color:#111827;font-size:clamp(1.72rem,2.45vw,2.38rem);font-weight:780;letter-spacing:-.04em;line-height:1.1; }
.if-page-desc { color:#667085;font-size:14px;line-height:1.65;margin:.5rem 0 0;max-width:780px; }
.if-page-chip {
  flex:0 0 auto;color:#3F51D9;background:#EEF1FF;border:1px solid #DCE2FF;
  padding:.5rem .72rem;border-radius:999px;font-size:11px;font-weight:700;white-space:nowrap;
}
.if-trust-strip {
  display:flex;align-items:center;gap:.7rem;flex-wrap:wrap;
  padding:.72rem .9rem;margin:.15rem 0 1.15rem;border:1px solid #E1E7F2;border-radius:13px;
  background:rgba(255,255,255,.74);box-shadow:0 8px 24px rgba(23,34,61,.035);
}
.if-trust-dot { width:8px;height:8px;border-radius:50%;background:#5267F8;box-shadow:0 0 0 5px rgba(82,103,248,.10); }
.if-trust-text { color:#536076;font-size:12px;line-height:1.5; }
.if-trust-text strong { color:#27324A; }
.if-section-head { display:flex;align-items:end;justify-content:space-between;gap:1rem;margin:1.35rem 0 .78rem; }
.if-section-title { color:#1A2335;font-size:16px;font-weight:740;letter-spacing:-.015em; }
.if-section-note { color:#8791A3;font-size:11px; }
.if-insight-card {
  border:1px solid #E4E9F2;border-left:3px solid var(--if-accent,#5267F8);border-radius:12px;
  background:#fff;padding:.78rem .86rem;margin:.52rem 0;box-shadow:0 5px 17px rgba(21,31,55,.035);
}
.if-insight-severity { font-size:9px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--if-accent,#5267F8);margin-bottom:.22rem; }
.if-insight-title { color:#202A3D;font-size:13px;font-weight:720;margin-bottom:.24rem; }
.if-insight-body { color:#687386;font-size:11.5px;line-height:1.58; }
div[data-testid="stMetric"] {
  background:rgba(255,255,255,.92);
  border:1px solid var(--if-line);
  border-radius:16px;
  padding:1rem 1.05rem .92rem;
  min-height:116px;
  box-shadow:var(--if-shadow);
  position:relative;
  overflow:hidden;
}
div[data-testid="stMetric"]:before {
  content:"";position:absolute;left:0;right:0;top:0;height:3px;
  background:linear-gradient(90deg,#5267F8,#38BDF8);
  opacity:.9;
}
[data-testid="stMetricLabel"] { color:#7A8598 !important;font-size:11px !important;font-weight:680 !important;letter-spacing:.015em; }
[data-testid="stMetricValue"] { color:#182235 !important;font-weight:760 !important;letter-spacing:-.035em;font-size:clamp(1.5rem,2.05vw,2rem) !important; }
[data-testid="stMetricDelta"] { font-size:11px !important;font-weight:650 !important; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius:16px; }
[data-testid="stPlotlyChart"], [data-testid="stDataFrame"], [data-testid="stTable"] {
  background:rgba(255,255,255,.92);
  border:1px solid var(--if-line);
  border-radius:16px;
  box-shadow:var(--if-shadow);
  overflow:hidden;
}
[data-testid="stPlotlyChart"] { padding:.24rem .4rem .1rem; }
[data-testid="stDataFrame"] { padding:.25rem; }
.stTabs [data-baseweb="tab-list"] {
  gap:.38rem;background:#EBEFF6;padding:.34rem;border-radius:13px;width:max-content;max-width:100%;
}
.stTabs [data-baseweb="tab"] {
  height:35px;border-radius:9px;padding:0 .8rem;color:#69758A;font-size:12px;font-weight:650;
}
.stTabs [aria-selected="true"] {
  background:#FFFFFF;color:#27324A;box-shadow:0 4px 12px rgba(21,31,55,.09);
}
.stTabs [data-baseweb="tab-highlight"] { display:none; }
.stButton > button, .stDownloadButton > button {
  border-radius:11px;border:1px solid #DCE2ED;font-weight:680;min-height:40px;
  transition:all .16s ease;background:#fff;color:#344054;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  border-color:#AEBBFF;color:#3F51D9;transform:translateY(-1px);box-shadow:0 7px 17px rgba(63,81,217,.10);
}
.stButton > button[kind="primary"] {
  border:0;color:#fff;background:linear-gradient(135deg,#5267F8,#3F51D9 56%,#438EDB);
  box-shadow:0 8px 18px rgba(63,81,217,.22);
}
[data-testid="stAlert"] { border-radius:13px;border-width:1px;box-shadow:0 5px 16px rgba(21,31,55,.035); }
[data-testid="stExpander"] {
  background:rgba(255,255,255,.86);border:1px solid var(--if-line);border-radius:13px;box-shadow:0 5px 18px rgba(21,31,55,.03);
}
[data-testid="stSelectbox"] [data-baseweb="select"] > div,
[data-testid="stMultiSelect"] [data-baseweb="select"] > div,
[data-testid="stTextInput"] [data-baseweb="input"] > div,
[data-testid="stNumberInput"] [data-baseweb="input"] > div,
[data-testid="stDateInput"] [data-baseweb="input"] > div {
  border-radius:10px;border-color:#DDE3EC;background:rgba(255,255,255,.92);
}
h1,h2,h3 { color:#172033;letter-spacing:-.025em; }
h2 { font-size:1.1rem !important;margin-top:1.25rem !important; }
h3 { font-size:.98rem !important; }
p, li { color:#5F6B7D; }
code { border-radius:7px !important; }
[data-testid="stCaptionContainer"] { color:#8791A3; }
[data-testid="stDecoration"] { display:none; }
footer { visibility:hidden; }
@media (max-width: 920px) {
  [data-testid="stAppViewContainer"] > .main .block-container { padding-left:1rem;padding-right:1rem; }
  .if-page-head { align-items:flex-start;flex-direction:column;gap:.65rem; }
  .if-page-chip { align-self:flex-start; }
  div[data-testid="stMetric"] { min-height:104px; }
}
</style>
"""


def apply_design_system() -> None:
    _configure_plotly()
    st.markdown(_DESIGN_CSS, unsafe_allow_html=True)


def page_header(
    title: str,
    description: str,
    *,
    eyebrow: str = "INSIGHTFLOW / BUSINESS INTELLIGENCE",
    chip: str | None = None,
) -> None:
    chip_html = f'<div class="if-page-chip">{escape(chip)}</div>' if chip else ""
    st.markdown(
        f"""
        <div class="if-page-head">
          <div>
            <div class="if-eyebrow">{escape(eyebrow)}</div>
            <h1 class="if-page-title">{escape(title)}</h1>
            <p class="if-page-desc">{escape(description)}</p>
          </div>
          {chip_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_header(title: str, note: str | None = None) -> None:
    note_html = f'<div class="if-section-note">{escape(note)}</div>' if note else ""
    st.markdown(
        f'<div class="if-section-head"><div class="if-section-title">{escape(title)}</div>{note_html}</div>',
        unsafe_allow_html=True,
    )


def render_issue_card(severity: str, title: str, body: str) -> None:
    color = {
        "P0": PALETTE["danger"],
        "P1": PALETTE["orange"],
        "P2": PALETTE["gold"],
        "P3": PALETTE["teal"],
    }.get(severity, PALETTE["blue"])
    st.markdown(
        f"""
        <div class="if-insight-card" style="--if-accent:{color}">
          <div class="if-insight-severity">{escape(severity)}</div>
          <div class="if-insight-title">{escape(title)}</div>
          <div class="if-insight-body">{escape(body)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def ensure_demo_warehouse(db_path: Path = DEFAULT_DB_PATH) -> None:
    if table_exists(db_path, "fact_transactions") and table_exists(db_path, "metric_catalog"):
        return
    if is_read_only():
        raise FileNotFoundError(
            "当前为只读模式，但数据仓库不存在。请先运行 python scripts/bootstrap.py，"
            "或将 INSIGHTFLOW_READ_ONLY=false 后初始化。"
        )
    from .config import DEFAULT_RAW_PATH

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


def render_app_brand() -> str:
    st.sidebar.markdown(
        """
        <div class="if-brand">
          <div class="if-brand-mark">I</div>
          <div>
            <div class="if-brand-name">InsightFlow</div>
            <div class="if-brand-sub">Decision Intelligence</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
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


def sidebar_filters(db_path: Path = DEFAULT_DB_PATH) -> FilterSpec:
    try:
        ensure_demo_warehouse(db_path)
    except FileNotFoundError as exc:
        st.error(str(exc))
        st.stop()
    (min_date, max_date), _options, _option_counts, profile = _cached_sidebar_metadata(
        str(db_path.resolve()), database_version(db_path)
    )
    st.sidebar.markdown(
        f'<div class="if-sidebar-label">{escape(t("filters.scope"))}</div>',
        unsafe_allow_html=True,
    )
    max_day = date.fromisoformat(max_date)
    min_day = date.fromisoformat(min_date)
    default_start = max(min_day, max_day - timedelta(days=89))
    selected = st.sidebar.date_input(
        t("filters.period"),
        value=(default_start, max_day),
        min_value=min_day,
        max_value=max_day,
        key="global_analysis_period",
    )
    if isinstance(selected, tuple) and len(selected) == 2:
        start, end = selected
    else:
        start = end = selected

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
            use_container_width=True,
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
            use_container_width=True,
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
                f"{region_label(value, current_language())} · {region_counts.get(value, 0):,}"
            ),
        )
        countries = st.multiselect(
            t("filters.country"),
            countries_options,
            key="filter_countries",
            format_func=lambda value: (
                f"{country_label(value, current_language())} · {country_counts.get(value, 0):,}"
            ),
        )
        categories = st.multiselect(
            t("filters.category"),
            categories_options,
            key="filter_categories",
            format_func=lambda value: f"{value} · {category_counts.get(value, 0):,}",
        )
        channels = st.multiselect(
            t("filters.channel"),
            channels_options,
            key="filter_channels",
            format_func=lambda value: f"{value} · {channel_counts.get(value, 0):,}",
        )

    current_filters = FilterSpec(
        start_date=start_iso,
        end_date=end_iso,
        countries=tuple(countries),
        categories=tuple(categories),
        channels=tuple(channels),
        regions=tuple(regions),
    )
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
    st.sidebar.markdown(
        f'<div class="if-sidebar-label">{escape(t("environment"))}</div>',
        unsafe_allow_html=True,
    )
    mode = t("mode.read_only") if is_read_only() else t("mode.local_edit")
    profile_name = escape(str(profile.get("profile_name", "Unknown")))
    transaction = escape(_trust_display(str(profile.get("transaction_status", "Mixed"))))
    economic = escape(_trust_display(str(profile.get("economic_status", "Mixed"))))
    inventory = escape(_trust_display(str(profile.get("inventory_status", "Mixed"))))
    st.sidebar.markdown(
        f"""
        <div class="if-sidebar-status">
          <strong style="color:#F5F7FF">{profile_name}</strong><br>
          {escape(t("status.transaction"))} {transaction} · {escape(t("status.economic"))} {economic} · {escape(t("status.inventory"))} {inventory}<br>
          {escape(mode)} · SQLite · v0.4.3.3
        </div>
        """,
        unsafe_allow_html=True,
    )
    return current_filters


def render_trust_banner(db_path: Path = DEFAULT_DB_PATH) -> None:
    _, _, _, profile = _cached_sidebar_metadata(str(db_path.resolve()), database_version(db_path))
    mode = str(profile.get("data_mode", "Mixed"))
    message = (
        f"<strong>{escape(str(profile.get('profile_name', 'Unknown')))}</strong> · "
        f"整体 {escape(trust_label(mode))} · "
        f"交易 {escape(trust_label(str(profile.get('transaction_status', 'Mixed'))))} · "
        f"成本 {escape(trust_label(str(profile.get('economic_status', 'Mixed'))))} · "
        f"库存 {escape(trust_label(str(profile.get('inventory_status', 'Mixed'))))}"
    )
    if is_read_only():
        message += " · 只读访客"
    st.markdown(
        f'<div class="if-trust-strip"><span class="if-trust-dot"></span><div class="if-trust-text">{message}</div></div>',
        unsafe_allow_html=True,
    )


def compact_number(value: float) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:,.0f}"


def card_container(*, border: bool = True) -> Any:
    return st.container(border=border)
