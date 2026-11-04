"""Visual language: money moves like water.

Colour is semantic before it is decorative. Flow is money still in play, profit is what
remains, leak is what left. Series colours identify entities and were validated for
colour-blind separation on both dark surfaces; status colours mean good or bad and are
never reused for identity.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

COLORS = {
    "page": "#0A1F3D",
    "panel": "#0F2747",
    "raised": "#17345C",
    "line": "#274A78",
    "grid": "#1C3A63",
    "ink": "#EAF4FF",
    "ink_soft": "#B4C7DF",
    "muted": "#8BA3C2",
    "flow": "#38D6C4",
    "profit": "#FFC44D",
    "leak": "#FF7B6B",
}
# Fixed order: validated adjacent-pair separation depends on it. Scatter and bubble charts
# use only the first three, the set that also clears the all-pairs check.
SERIES = ["#3D8FE6", "#D8722A", "#14A88C", "#BC8A0C", "#D65F9E", "#55A332", "#9A7DEB", "#E25B5B"]
SEQUENTIAL = ["#14325A", "#1C4B80", "#2A6BB0", "#3D8FE6", "#7FB7F1", "#C3DEF9"]
DIVERGING = [
    [0.0, "#E25B5B"],
    [0.25, "#A25A68"],
    [0.5, "#34486A"],
    [0.75, "#3A6FB0"],
    [1.0, "#7FB7F1"],
]
STATUS = {"good": "#2DBE6C", "warning": "#FAB219", "serious": "#EC835A", "critical": "#F0616D"}
SEVERITY = {
    "P0": STATUS["critical"],
    "P1": STATUS["serious"],
    "P2": STATUS["warning"],
    "P3": STATUS["good"],
}
FONT_STACK = (
    "Sora, 'HarmonyOS Sans SC', MiSans, 'PingFang SC', 'Microsoft YaHei UI', "
    "'Microsoft YaHei', sans-serif"
)


def configure_plotly() -> None:
    axis = {
        "gridcolor": COLORS["grid"],
        "gridwidth": 1,
        "griddash": "solid",
        "linecolor": COLORS["line"],
        "zerolinecolor": COLORS["line"],
        "tickfont": {"color": COLORS["muted"], "size": 12},
        "title": {"font": {"color": COLORS["muted"], "size": 12}, "standoff": 10},
        "automargin": True,
        "ticks": "",
    }
    template = go.layout.Template(
        layout=go.Layout(
            font={"family": FONT_STACK, "color": COLORS["ink_soft"], "size": 13},
            colorway=SERIES,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin={"l": 8, "r": 12, "t": 36, "b": 8},
            hoverlabel={
                "bgcolor": COLORS["raised"],
                "bordercolor": COLORS["line"],
                "font": {"color": COLORS["ink"], "size": 13, "family": FONT_STACK},
            },
            legend={
                "orientation": "h",
                "yanchor": "bottom",
                "y": 1.02,
                "xanchor": "left",
                "x": 0,
                "title": {"text": ""},
                "font": {"color": COLORS["ink_soft"], "size": 12},
                "bgcolor": "rgba(0,0,0,0)",
            },
            xaxis=axis,
            yaxis=axis,
            bargap=0.28,
            bargroupgap=0.08,
            transition={"duration": 420, "easing": "cubic-in-out"},
        )
    )
    pio.templates["insightflow"] = template
    pio.templates.default = "insightflow"


GLOBAL_CSS = """
<style>
html, body, [class*="css"], [data-testid="stAppViewContainer"] {
  font-family: Sora, 'HarmonyOS Sans SC', MiSans, 'PingFang SC', 'Microsoft YaHei UI',
    'Microsoft YaHei', sans-serif;
  font-feature-settings: "tnum" 0;
}
.stApp {
  background:
    radial-gradient(90rem 34rem at 62% -14rem, rgba(56, 214, 196, .07), transparent 70%),
    linear-gradient(180deg, #0C2546 0%, #0A1F3D 34rem);
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"] { right: .6rem; }
[data-testid="stDecoration"], footer { display: none; }
[data-testid="stMainBlockContainer"], .block-container {
  max-width: 1480px;
  padding: 2.4rem clamp(1rem, 3vw, 3.2rem) 5rem;
}

/* Sidebar: the instrument rail */
[data-testid="stSidebar"] { border-right: 1px solid #1C3A63; }
[data-testid="stSidebarNav"] { padding-top: .25rem; }
[data-testid="stSidebarNav"] a {
  border-radius: 4px;
  transition: background-color .16s ease;
}
[data-testid="stSidebarNav"] a:hover { background: rgba(124, 196, 255, .08); }
[data-testid="stSidebarNav"] a[aria-current="page"] {
  background: rgba(56, 214, 196, .10);
  box-shadow: inset 2px 0 0 #38D6C4;
}
[data-testid="stSidebarNavSeparator"] { border-color: #1C3A63; }
[data-testid="stSidebar"] [data-testid="stExpander"] details {
  border-color: #1C3A63;
  background: transparent;
}
.if-brand { display: flex; align-items: center; gap: .7rem; padding: .3rem .15rem 1rem; }
.if-brand svg { flex: 0 0 auto; }
.if-brand-name { color: #EAF4FF; font-weight: 600; font-size: 1.02rem; letter-spacing: -.01em; }
.if-brand-sub { color: #8BA3C2; font-size: .74rem; margin-top: .1rem; }
.if-rail-title { color: #8BA3C2; font-size: .76rem; margin: 1rem 0 .3rem; }
.if-rail-status { color: #B4C7DF; font-size: .76rem; line-height: 1.7; }
.if-rail-status b { color: #EAF4FF; font-weight: 600; }

/* Page and section headings */
.if-page-title {
  margin: 0;
  color: #EAF4FF;
  font-size: clamp(1.7rem, 2.6vw, 2.5rem);
  font-weight: 600;
  letter-spacing: -.03em;
  line-height: 1.16;
}
.if-page-lede {
  margin: .7rem 0 0;
  max-width: 62rem;
  color: #B4C7DF;
  font-size: 1.04rem;
  line-height: 1.7;
}
.if-page-meta { margin-top: .75rem; color: #8BA3C2; font-size: .82rem; line-height: 1.6; }
.if-page-meta b { color: #B4C7DF; font-weight: 500; }
.if-section {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1.5rem;
  margin: 2.5rem 0 .75rem;
  padding-top: 1rem;
  border-top: 1px solid #1C3A63;
}
.if-section-title { color: #EAF4FF; font-size: 1.1rem; font-weight: 600; letter-spacing: -.015em; }
.if-section-note { color: #8BA3C2; font-size: .82rem; text-align: right; }
.if-subhead { color: #EAF4FF; font-size: .96rem; font-weight: 600; margin: .4rem 0 .2rem; }
.if-note { color: #8BA3C2; font-size: .82rem; line-height: 1.65; margin: .25rem 0 .9rem; }

/* Signals: a ledger of findings, not a stack of cards */
.if-signal {
  display: grid;
  grid-template-columns: 4.6rem 1fr;
  gap: .3rem .9rem;
  padding: .85rem 0;
  border-bottom: 1px solid #1C3A63;
}
.if-signal:last-child { border-bottom: 0; }
.if-signal-level {
  display: inline-flex;
  align-items: center;
  gap: .4rem;
  color: #EAF4FF;
  font-size: .78rem;
  font-weight: 600;
  height: 1.4rem;
}
.if-signal-level i {
  width: .55rem;
  height: .55rem;
  border-radius: 50%;
  background: var(--level);
  flex: 0 0 auto;
}
.if-signal-title { color: #EAF4FF; font-size: .92rem; font-weight: 500; line-height: 1.45; }
.if-signal-body { color: #B4C7DF; font-size: .84rem; line-height: 1.6; margin-top: .15rem; }

/* Verdicts close a piece of analysis with a plain statement */
.if-verdict {
  display: flex;
  gap: .8rem;
  align-items: baseline;
  padding: .85rem 1rem;
  margin: .6rem 0 1rem;
  border-left: 3px solid var(--tone);
  background: rgba(23, 52, 92, .55);
  border-radius: 0 6px 6px 0;
}
.if-verdict b { color: #EAF4FF; font-weight: 600; white-space: nowrap; }
.if-verdict span { color: #B4C7DF; font-size: .9rem; line-height: 1.6; }

/* Controls */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  font-weight: 500;
  transition: background-color .16s ease, border-color .16s ease, color .16s ease;
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
  background: #38D6C4;
  border-color: #38D6C4;
  color: #06213B;
  font-weight: 600;
}
.stButton > button[kind="primary"]:hover { background: #63E2D4; border-color: #63E2D4; }
/* A disabled button must look disabled, or a step that is still waiting reads as ready. */
.stButton > button:disabled, .stDownloadButton > button:disabled,
.stFormSubmitButton > button:disabled, .stButton > button[kind="primary"]:disabled,
.stFormSubmitButton > button[kind="primary"]:disabled {
  background: #17345C;
  border-color: #274A78;
  color: #8BA3C2;
  cursor: not-allowed;
}
:is(a, button, [role="tab"], input, [tabindex]):focus-visible {
  outline: 2px solid #38D6C4 !important;
  outline-offset: 2px;
}
.stTabs [data-baseweb="tab-list"] { gap: 1.6rem; border-bottom: 1px solid #1C3A63; }
.stTabs [data-baseweb="tab"] { padding: .5rem 0; color: #8BA3C2; font-size: .92rem; }
.stTabs [aria-selected="true"] { color: #EAF4FF; }
.stTabs [data-baseweb="tab-highlight"] { background: #38D6C4; height: 2px; }
.stTabs [data-baseweb="tab-border"] { display: none; }
[data-testid="stExpander"] details { border-color: #1C3A63; }
[data-testid="stExpander"] summary { color: #B4C7DF; font-size: .88rem; }
[data-testid="stMetricValue"] { font-weight: 600; letter-spacing: -.02em; }
[data-testid="stMetricLabel"] { color: #B4C7DF; }
[data-testid="stPlotlyChart"] { background: transparent; }
[data-testid="stAlert"] { border-radius: 6px; }
hr { border-color: #1C3A63; }

/* Time series unroll once, in the direction time moves */
@keyframes if-unroll {
  from { clip-path: inset(-10% 100% -10% 0); opacity: .35; }
  to { clip-path: inset(-10% 0 -10% 0); opacity: 1; }
}
[class*="st-key-unroll_"] .js-plotly-plot {
  animation: if-unroll 1.1s cubic-bezier(.22, .8, .24, 1) both;
}
@media (prefers-reduced-motion: reduce) {
  [class*="st-key-unroll_"] .js-plotly-plot { animation: none; }
  * { transition: none !important; }
}
@media (max-width: 760px) {
  [data-testid="stHeader"] { background: rgba(10, 31, 61, .9); backdrop-filter: blur(10px); }
  [data-testid="stMainBlockContainer"], .block-container { padding-top: 4.4rem; }
  .if-section { flex-direction: column; gap: .25rem; }
  .if-section-note { text-align: left; }
  .if-signal { grid-template-columns: 1fr; }
}
</style>
"""
