"""Chart builders. Every chart here follows one rulebook.

One y-axis per chart, thin marks, solid hairlines, a legend whenever two or more series
appear, and direct labels only where they earn their place. Colour follows the entity
and meaning, so a filter can never repaint a survivor.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from .design import COLORS, DIVERGING, SEQUENTIAL, SERIES

CHART_CONFIG = {"displayModeBar": False, "responsive": True, "scrollZoom": False}


def show(figure: go.Figure, *, key: str | None = None) -> None:
    """Render with the house template rather than Streamlit's default theme."""
    # Streamlit paints theme colours unless these are set on the figure itself.
    figure.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(figure, theme=None, config=CHART_CONFIG, key=key)


def series_color(name: object, palette: dict[object, str]) -> str:
    """Bind a colour to an entity once, so filtering leaves survivors unchanged."""
    if name not in palette:
        palette[name] = SERIES[len(palette) % len(SERIES)]
    return palette[name]


def _hex_alpha(color: str, alpha: float) -> str:
    red, green, blue = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({red},{green},{blue},{alpha})"


def trend_lines(
    frame: pd.DataFrame,
    x: str,
    series: dict[str, tuple[str, str]],
    *,
    height: int = 340,
    money_prefix: str = "",
    percent: bool = False,
) -> go.Figure:
    """Lines over time. `series` maps a column to its label and colour."""
    figure = go.Figure()
    hover = ".1%" if percent else ",.0f"
    for column, (label, color) in series.items():
        figure.add_scatter(
            x=frame[x],
            y=frame[column],
            name=label,
            mode="lines",
            line={"color": color, "width": 2, "shape": "spline", "smoothing": 0.5},
            hovertemplate=f"{label} {money_prefix}%{{y:{hover}}}<extra></extra>",
        )
        figure.add_scatter(
            x=frame[x].tail(1),
            y=frame[column].tail(1),
            mode="markers",
            marker={"size": 8, "color": color, "line": {"color": COLORS["page"], "width": 2}},
            showlegend=False,
            hoverinfo="skip",
        )
    figure.update_layout(height=height, hovermode="x unified", margin={"t": 40})
    figure.update_yaxes(tickprefix=money_prefix, tickformat=".0%" if percent else "~s")
    figure.update_xaxes(showgrid=False)
    return figure


def forecast_fan(
    history: pd.DataFrame,
    forecast: pd.DataFrame,
    column: str,
    *,
    labels: dict[str, str],
    money_prefix: str = "",
    height: int = 340,
) -> go.Figure:
    """History as a line, the future as widening 80% and 95% bands."""
    recent = history.tail(18)
    bridge_x = [recent["month"].iloc[-1], *forecast["month"]]
    last = float(recent[column].iloc[-1])

    def band(lower: str, upper: str, opacity: float, name: str) -> go.Scatter:
        return go.Scatter(
            x=bridge_x + bridge_x[::-1],
            y=[last, *forecast[upper]] + [*forecast[lower], last][::-1],
            mode="lines",
            fill="toself",
            fillcolor=_hex_alpha(COLORS["flow"], opacity),
            line={"width": 0},
            name=name,
            hoverinfo="skip",
        )

    figure = go.Figure()
    figure.add_trace(band("lower", "upper", 0.12, labels["band95"]))
    figure.add_trace(band("lower_80", "upper_80", 0.22, labels["band80"]))
    figure.add_scatter(
        x=recent["month"],
        y=recent[column],
        name=labels["actual"],
        mode="lines",
        line={"color": COLORS["ink_soft"], "width": 2},
        hovertemplate=f"{money_prefix}%{{y:,.0f}}<extra>{labels['actual']}</extra>",
    )
    figure.add_scatter(
        x=bridge_x,
        y=[last, *forecast["forecast"]],
        name=labels["forecast"],
        mode="lines+markers",
        line={"color": COLORS["flow"], "width": 2},
        marker={"size": 8, "line": {"color": COLORS["page"], "width": 2}},
        hovertemplate=f"{money_prefix}%{{y:,.0f}}<extra>{labels['forecast']}</extra>",
    )
    figure.update_layout(height=height, hovermode="x unified", margin={"t": 40})
    figure.update_yaxes(tickprefix=money_prefix, tickformat="~s")
    figure.update_xaxes(showgrid=False)
    return figure


def cash_waterfall(
    frame: pd.DataFrame,
    *,
    label: str,
    value: str,
    money_prefix: str = "",
    height: int = 380,
    start_is_total: bool = False,
) -> go.Figure:
    """Walk from the first amount to the last. Inflow is aqua, leaks are coral, profit is gold."""
    first = "absolute" if start_is_total else "relative"
    measures = [first] + ["relative"] * (len(frame) - 2) + ["total"]
    figure = go.Figure(
        go.Waterfall(
            x=frame[label],
            y=frame[value],
            measure=measures,
            connector={"line": {"width": 1, "color": COLORS["line"]}},
            increasing={"marker": {"color": COLORS["flow"]}},
            decreasing={"marker": {"color": COLORS["leak"]}},
            totals={"marker": {"color": COLORS["profit"]}},
            text=[f"{money_prefix}{abs(v) / 1000:,.0f}K" for v in frame[value]],
            textposition="outside",
            textfont={"color": COLORS["ink_soft"], "size": 12},
            hovertemplate=f"%{{x}}: {money_prefix}%{{y:,.0f}}<extra></extra>",
        )
    )
    figure.update_layout(height=height, showlegend=False, margin={"t": 24})
    figure.update_yaxes(tickprefix=money_prefix, tickformat="~s", showticklabels=False, showgrid=False)
    figure.update_xaxes(showgrid=False)
    return figure


def bridge(
    start_label: str,
    start: float,
    steps: pd.DataFrame,
    end_label: str,
    end: float,
    *,
    money_prefix: str = "",
    height: int = 400,
) -> go.Figure:
    """Explain a period-on-period change as a walk from one total to the other."""
    labels = [start_label, *steps["label"], end_label]
    values = [start, *steps["impact"], end]
    frame = pd.DataFrame({"label": labels, "value": values})
    figure = cash_waterfall(
        frame,
        label="label",
        value="value",
        money_prefix=money_prefix,
        height=height,
        start_is_total=True,
    )
    span = abs(start) + abs(end)
    floor = min(start, end) - span * 0.12
    figure.update_yaxes(range=[max(0, floor), None])
    return figure


def ranked_bars(
    frame: pd.DataFrame,
    *,
    label: str,
    value: str,
    money_prefix: str = "",
    color: str | None = None,
    percent: bool = False,
    height: int | None = None,
) -> go.Figure:
    """Horizontal bars in one colour. Length already encodes value; colour stays neutral."""
    ordered = frame.sort_values(value)
    figure = go.Figure(
        go.Bar(
            x=ordered[value],
            y=ordered[label].astype(str),
            orientation="h",
            marker={"color": color or SERIES[0], "cornerradius": 3},
            hovertemplate=(
                f"%{{y}}: {money_prefix}%{{x:{'.1%' if percent else ',.0f'}}}<extra></extra>"
            ),
        )
    )
    figure.update_layout(height=height or max(240, 26 * len(ordered) + 60), margin={"t": 8})
    figure.update_xaxes(tickprefix=money_prefix, tickformat=".0%" if percent else "~s")
    figure.update_yaxes(showgrid=False)
    return figure


def signed_bars(
    frame: pd.DataFrame,
    *,
    label: str,
    value: str,
    money_prefix: str = "",
    decimals: str = ",.0f",
    tick_format: str = "~s",
    height: int | None = None,
) -> go.Figure:
    """Gains and losses around zero, with colour carrying the direction."""
    ordered = frame.sort_values(value)
    colors = [COLORS["flow"] if v >= 0 else COLORS["leak"] for v in ordered[value]]
    figure = go.Figure(
        go.Bar(
            x=ordered[value],
            y=ordered[label].astype(str),
            orientation="h",
            marker={"color": colors, "cornerradius": 3},
            hovertemplate=f"%{{y}}: {money_prefix}%{{x:{decimals}}}<extra></extra>",
        )
    )
    figure.update_layout(height=height or max(240, 26 * len(ordered) + 60), margin={"t": 8})
    figure.update_xaxes(tickprefix=money_prefix, tickformat=tick_format, zerolinewidth=1)
    figure.update_yaxes(showgrid=False)
    return figure


def pareto(
    frame: pd.DataFrame, *, value: str, labels: dict[str, str], height: int = 300
) -> go.Figure:
    """Cumulative share of a total by rank, indexed so one axis carries the whole story."""
    ordered = frame[value].clip(lower=0).sort_values(ascending=False).reset_index(drop=True)
    total = float(ordered.sum()) or 1.0
    share = ordered.cumsum() / total
    rank = (ordered.index + 1) / len(ordered)
    figure = go.Figure(
        go.Scatter(
            x=rank,
            y=share,
            mode="lines",
            line={"color": COLORS["flow"], "width": 2},
            fill="tozeroy",
            fillcolor=_hex_alpha(COLORS["flow"], 0.1),
            hovertemplate=f"{labels['x']} %{{x:.0%}}: {labels['y']} %{{y:.0%}}<extra></extra>",
        )
    )
    figure.update_layout(height=height, showlegend=False, margin={"t": 8})
    figure.update_xaxes(title=labels["x"], tickformat=".0%")
    figure.update_yaxes(title=labels["y"], tickformat=".0%", range=[0, 1.02])
    return figure


def quadrant(
    frame: pd.DataFrame,
    *,
    x: str,
    y: str,
    size: str,
    name: str,
    labels: dict[str, str],
    money_prefix: str = "",
    y_percent: bool = True,
    high_is_good: bool = True,
    height: int = 460,
) -> go.Figure:
    """A value map split at the medians. Colour marks the good or bad side of the y median."""
    data = frame.dropna(subset=[x, y]).copy()
    middle_x, middle_y = float(data[x].median()), float(data[y].median())
    magnitude = data[size].clip(lower=0).astype(float)
    scale = 2.0 * float(magnitude.max() or 1.0) / 26**2
    favourable = data[y] >= middle_y if high_is_good else data[y] < middle_y
    colors = np.where(favourable, COLORS["flow"], COLORS["leak"])
    figure = go.Figure(
        go.Scatter(
            x=data[x],
            y=data[y],
            mode="markers",
            text=data[name],
            marker={
                "size": magnitude,
                "sizemode": "area",
                "sizeref": scale,
                "sizemin": 5,
                "color": colors,
                "opacity": 0.8,
                "line": {"color": COLORS["page"], "width": 1.5},
            },
            hovertemplate=(
                f"%{{text}}<br>{labels['x']} {money_prefix}%{{x:,.0f}}"
                f"<br>{labels['y']} %{{y:{'.1%' if y_percent else ',.2f'}}}<extra></extra>"
            ),
        )
    )
    figure.add_hline(y=middle_y, line={"color": COLORS["line"], "width": 1})
    figure.add_vline(x=middle_x, line={"color": COLORS["line"], "width": 1})
    figure.update_layout(height=height, showlegend=False, margin={"t": 12})
    figure.update_xaxes(title=labels["x"], tickprefix=money_prefix, tickformat="~s")
    figure.update_yaxes(title=labels["y"], tickformat=".0%" if y_percent else ".2f")
    return figure


def heatmap(
    frame: pd.DataFrame,
    *,
    x_label: str,
    y_label: str,
    percent: bool = True,
    height: int = 420,
) -> go.Figure:
    """Magnitude on one blue ramp, with values written in the cells that can hold them."""
    scale = [[i / (len(SEQUENTIAL) - 1), color] for i, color in enumerate(SEQUENTIAL)]
    figure = px.imshow(
        frame,
        text_auto=".0%" if percent else ",.0f",
        aspect="auto",
        color_continuous_scale=scale,
        zmin=0,
        zmax=1 if percent else None,
    )
    figure.update_traces(
        xgap=2,
        ygap=2,
        textfont={"size": 11},
        hovertemplate=f"{y_label} %{{y}}<br>{x_label} %{{x}}<br>%{{z:{'.1%' if percent else ',.0f'}}}<extra></extra>",
    )
    figure.update_layout(height=height, coloraxis_showscale=False, margin={"t": 8})
    figure.update_xaxes(title=x_label, showgrid=False, side="bottom")
    figure.update_yaxes(title=y_label, showgrid=False)
    return figure


def segment_treemap(
    frame: pd.DataFrame,
    *,
    label: str,
    value: str,
    palette: dict[object, str],
    money_prefix: str = "",
    height: int = 340,
) -> go.Figure:
    data = frame[frame[value] > 0]
    figure = go.Figure(
        go.Treemap(
            labels=data[label],
            parents=[""] * len(data),
            values=data[value],
            texttemplate=f"%{{label}}<br>{money_prefix}%{{value:,.0f}}",
            textfont={"size": 13, "color": COLORS["ink"]},
            hovertemplate=f"%{{label}}: {money_prefix}%{{value:,.0f}}<extra></extra>",
            marker={
                "colors": [series_color(name, palette) for name in data[label]],
                "line": {"color": COLORS["page"], "width": 2},
                "cornerradius": 3,
            },
            tiling={"pad": 2},
        )
    )
    figure.update_layout(height=height, margin={"l": 0, "r": 0, "t": 4, "b": 0})
    return figure


def frontier(
    plans: pd.DataFrame,
    line: pd.DataFrame,
    chosen: pd.Series | None,
    *,
    labels: dict[str, str],
    money_prefix: str = "",
    height: int = 420,
) -> go.Figure:
    """Every candidate plan by typical and bad-case result, with the best-available edge."""
    figure = go.Figure()
    failing = plans[~plans["passes_guardrails"]]
    passing = plans[plans["passes_guardrails"]]
    figure.add_scatter(
        x=failing["p05_profit_change"],
        y=failing["median_profit_change"],
        mode="markers",
        name=labels["failed"],
        text=failing["plan"],
        marker={"size": 7, "color": COLORS["line"]},
        hovertemplate=f"%{{text}}<br>{money_prefix}%{{y:,.0f}}<extra></extra>",
    )
    figure.add_scatter(
        x=passing["p05_profit_change"],
        y=passing["median_profit_change"],
        mode="markers",
        name=labels["passed"],
        text=passing["plan"],
        marker={"size": 8, "color": SERIES[0], "line": {"color": COLORS["page"], "width": 1}},
        hovertemplate=f"%{{text}}<br>{money_prefix}%{{y:,.0f}}<extra></extra>",
    )
    if len(line) >= 2:
        figure.add_scatter(
            x=line["p05_profit_change"],
            y=line["median_profit_change"],
            mode="lines",
            name=labels["frontier"],
            line={"color": COLORS["flow"], "width": 2},
            hoverinfo="skip",
        )
    if chosen is not None:
        figure.add_scatter(
            x=[chosen["p05_profit_change"]],
            y=[chosen["median_profit_change"]],
            mode="markers",
            name=labels["chosen"],
            text=[chosen["plan"]],
            marker={
                "size": 15,
                "color": COLORS["profit"],
                "line": {"color": COLORS["page"], "width": 2},
            },
            hovertemplate=f"%{{text}}<br>{money_prefix}%{{y:,.0f}}<extra></extra>",
        )
    figure.update_layout(height=height, hovermode="closest")
    figure.update_xaxes(title=labels["x"], tickprefix=money_prefix, tickformat="~s")
    figure.update_yaxes(title=labels["y"], tickprefix=money_prefix, tickformat="~s")
    return figure


def calibration_chart(frame: pd.DataFrame, *, labels: dict[str, str], height: int = 300) -> go.Figure:
    """Predicted against observed; points on the diagonal mean the model is honest."""
    top = float(max(frame["predicted"].max(), frame["actual"].max(), 0.05)) * 1.05
    figure = go.Figure()
    figure.add_scatter(
        x=[0, top],
        y=[0, top],
        mode="lines",
        name=labels["ideal"],
        line={"color": COLORS["line"], "width": 1},
        hoverinfo="skip",
    )
    figure.add_scatter(
        x=frame["predicted"],
        y=frame["actual"],
        mode="lines+markers",
        name=labels["model"],
        line={"color": COLORS["flow"], "width": 2},
        marker={"size": 9, "line": {"color": COLORS["page"], "width": 2}},
        hovertemplate=f"{labels['x']} %{{x:.0%}}<br>{labels['y']} %{{y:.0%}}<extra></extra>",
    )
    figure.update_layout(height=height, margin={"t": 36})
    figure.update_xaxes(title=labels["x"], tickformat=".0%", range=[0, top])
    figure.update_yaxes(title=labels["y"], tickformat=".0%", range=[0, top])
    return figure


def lineage_sankey(frame: pd.DataFrame, *, height: int = 320) -> go.Figure:
    nodes = list(dict.fromkeys([*frame["source_object"], *frame["target_object"]]))
    index = {name: position for position, name in enumerate(nodes)}
    figure = go.Figure(
        go.Sankey(
            arrangement="snap",
            node={
                "label": nodes,
                "color": COLORS["raised"],
                "line": {"color": COLORS["line"], "width": 1},
                "pad": 18,
                "thickness": 12,
            },
            link={
                "source": [index[name] for name in frame["source_object"]],
                "target": [index[name] for name in frame["target_object"]],
                "value": [1] * len(frame),
                "color": _hex_alpha(COLORS["flow"], 0.22),
                "customdata": frame["description"],
                "hovertemplate": "%{customdata}<extra></extra>",
            },
        )
    )
    figure.update_layout(height=height, margin={"l": 4, "r": 4, "t": 8, "b": 8})
    figure.update_traces(textfont={"color": COLORS["ink"], "size": 12})
    return figure


def diverging_heatmap(
    frame: pd.DataFrame, *, x_label: str, y_label: str, height: int = 340
) -> go.Figure:
    """Signed values around zero: warm below, cool above, grey in the middle."""
    limit = float(np.nanmax(np.abs(frame.to_numpy()))) or 1.0
    figure = px.imshow(
        frame,
        aspect="auto",
        color_continuous_scale=DIVERGING,
        zmin=-limit,
        zmax=limit,
        text_auto=".0%",
    )
    figure.update_traces(xgap=2, ygap=2, textfont={"size": 11})
    figure.update_layout(height=height, coloraxis_showscale=False, margin={"t": 8})
    figure.update_xaxes(title=x_label, showgrid=False)
    figure.update_yaxes(title=y_label, showgrid=False)
    return figure
