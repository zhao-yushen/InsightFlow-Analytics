from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from insightflow.config import DEFAULT_DB_PATH, is_read_only
from insightflow.currency import money, symbol
from insightflow.design import COLORS
from insightflow.experiments import (
    ASSIGNMENT_COLUMNS,
    analyze_experiment,
    experiment_catalog,
    import_experiment,
)
from insightflow.i18n import t, tr
from insightflow.ingest import read_table
from insightflow.live import gauge_strip
from insightflow.ui import (
    currency_code,
    gauge_item,
    note,
    page_header,
    section_header,
    sidebar_filters,
    subhead,
    table_view,
    verdict,
)
from insightflow.viz import show

METRIC_LABELS = {
    "converted": ("转化率", "Conversion"),
    "net_revenue": ("单客收入", "Revenue per customer"),
    "contribution_profit": ("单客贡献利润", "Profit per customer"),
    "returned": ("退货率", "Return rate"),
}
DECISION_TONE = {"ship": "good", "pilot": "warning", "inconclusive": "neutral", "stop": "bad"}
DECISION_EN = {
    "ship": "Ship it",
    "pilot": "Pilot and keep watching",
    "inconclusive": "Not enough evidence yet",
    "stop": "Do not roll out",
}


def _effect_chart(metrics: pd.DataFrame) -> go.Figure:
    """Show effects relative to control so metrics on different scales share one axis."""
    data = metrics.copy()
    base = data["control_mean"].abs().replace(0, 1)
    data["low"] = data["ci_low"] / base
    data["high"] = data["ci_high"] / base
    data["middle"] = data["absolute_lift"] / base
    data["label"] = data["metric"].map(lambda key: tr(*METRIC_LABELS.get(key, (key, key))))
    colors = [
        COLORS["flow"] if low > 0 else COLORS["leak"] if high < 0 else COLORS["ink_soft"]
        for low, high in zip(data["low"], data["high"], strict=True)
    ]
    figure = go.Figure(
        go.Scatter(
            x=data["middle"],
            y=data["label"],
            mode="markers",
            marker={"size": 12, "color": colors, "line": {"color": COLORS["page"], "width": 2}},
            error_x={
                "type": "data",
                "symmetric": False,
                "array": data["high"] - data["middle"],
                "arrayminus": data["middle"] - data["low"],
                "color": COLORS["ink_soft"],
                "thickness": 1.5,
                "width": 0,
            },
            hovertemplate="%{y}: %{x:+.1%}<extra></extra>",
        )
    )
    figure.add_vline(x=0, line={"color": COLORS["muted"], "width": 1})
    figure.update_layout(height=280, showlegend=False, margin={"t": 12})
    figure.update_xaxes(title=tr("相对对照组的变化", "Change against control"), tickformat="+.0%")
    figure.update_yaxes(showgrid=False)
    return figure


def _import_panel() -> None:
    with st.expander(tr("导入真实实验数据", "Import a real experiment")):
        st.caption(
            tr(
                "每位客户一行，需要这些字段：",
                "One row per customer, with these fields: ",
            )
            + ", ".join(ASSIGNMENT_COLUMNS)
        )
        uploaded = st.file_uploader(
            tr("实验结果文件", "Experiment results file"),
            type=["csv", "xlsx", "parquet", "json"],
            label_visibility="collapsed",
            key="experiment_upload",
        )
        name = st.text_input(tr("实验名称", "Experiment name"), key="experiment_name")
        if st.button(
            tr("导入实验", "Import experiment"),
            disabled=is_read_only() or uploaded is None or not name.strip(),
        ):
            try:
                frame = read_table(uploaded.getvalue(), uploaded.name)
                rows = import_experiment(DEFAULT_DB_PATH, frame, name.strip())
            except (ValueError, PermissionError) as error:
                st.error(str(error))
            else:
                st.success(tr(f"已导入 {rows:,} 行。", f"Imported {rows:,} rows."))
                st.rerun()


def render() -> None:
    sidebar_filters(DEFAULT_DB_PATH)
    code = currency_code()
    prefix = symbol(code)
    catalog = experiment_catalog(DEFAULT_DB_PATH)
    if catalog.empty:
        page_header(
            t("page.experiments.title"),
            tr(
                "还没有实验数据。导入一次 A/B 测试的客户级结果后，这里会给出是否推广的判断。",
                "No experiments yet. Import customer-level A/B results to get a rollout decision.",
            ),
        )
        _import_panel()
        return

    names = dict(zip(catalog["experiment_id"], catalog["experiment_name"], strict=False))
    selected = st.session_state.get("experiment_selected") or catalog["experiment_id"].iloc[0]
    summary, metrics, balance = analyze_experiment(DEFAULT_DB_PATH, selected)
    simulated = summary.data_status == "Simulated"
    page_header(
        t("page.experiments.title"),
        tr(
            f"{summary.experiment_name}：{summary.decision}。",
            f"{summary.experiment_name}: {DECISION_EN[summary.decision_code]}.",
        ),
        meta=(
            tr(
                "实验结果为可重复生成的模拟数据，用于展示判断方法。",
                "Results are reproducible simulated data, shown to demonstrate the method.",
            )
            if simulated
            else tr("实验结果来自导入的真实数据。", "Results come from imported experiment data.")
        ),
    )
    st.selectbox(
        tr("选择实验", "Experiment"),
        catalog["experiment_id"].tolist(),
        format_func=lambda value: names[value],
        key="experiment_selected",
    )
    gauge_strip(
        [
            gauge_item(tr("样本量", "Sample size"), summary.sample_size, "count", f"{summary.sample_size:,}", note_text=""),
            gauge_item(tr("单客利润变化", "Profit per customer"), summary.lift, "money", money(summary.lift, code, decimals=2), prefix=prefix, note_text=""),
            gauge_item(tr("利润提升概率", "Chance of a lift"), summary.probability_positive, "percent", f"{summary.probability_positive:.1%}", note_text=""),
            gauge_item(tr("最小可检出变化", "Smallest detectable"), summary.minimum_detectable_lift, "money", money(summary.minimum_detectable_lift, code, decimals=2), prefix=prefix, note_text=tr("80% 把握", "80% power")),
        ],
        key="experiment_gauges",
    )
    verdict(
        tr(summary.decision, DECISION_EN[summary.decision_code]),
        tr(
            f"95% 区间 {money(summary.confidence_low, code, decimals=2)} 至 {money(summary.confidence_high, code, decimals=2)}。",
            f"95% interval {money(summary.confidence_low, code, decimals=2)} to {money(summary.confidence_high, code, decimals=2)}.",
        ),
        DECISION_TONE[summary.decision_code],
    )

    section_header(tr("各指标的变化", "Effect on each metric"), tr("线段是 95% 区间，跨过 0 表示不确定", "Lines are 95% intervals; crossing 0 means unclear"))
    show(_effect_chart(metrics), key=f"experiment_effects_{selected}")

    section_header(tr("这次实验靠得住吗", "Can this experiment be trusted"))
    left, right = st.columns(2, gap="large")
    with left:
        subhead(tr("分组是否均匀", "Was the split even"))
        if summary.sample_ratio_p < 0.001:
            verdict(
                tr("分组异常", "Split looks broken"),
                tr(
                    f"两组人数差异过大（p = {summary.sample_ratio_p:.4f}），先排查分流逻辑再看结果。",
                    f"The groups differ too much (p = {summary.sample_ratio_p:.4f}). Check assignment first.",
                ),
                "bad",
            )
        else:
            verdict(
                tr("分组正常", "Split looks fine"),
                tr(f"人数差异在随机范围内（p = {summary.sample_ratio_p:.2f}）。", f"The difference is within chance (p = {summary.sample_ratio_p:.2f})."),
                "good",
            )
        st.dataframe(
            balance.rename(
                columns={
                    "assignment": tr("分组", "Group"),
                    "customers": tr("客户数", "Customers"),
                    "conversion_rate": tr("转化率", "Conversion"),
                    "return_rate": tr("退货率", "Return rate"),
                }
            ),
            hide_index=True,
            column_config={
                tr("转化率", "Conversion"): st.column_config.NumberColumn(format="percent"),
                tr("退货率", "Return rate"): st.column_config.NumberColumn(format="percent"),
            },
        )
    with right:
        subhead(tr("样本够不够", "Was the sample large enough"))
        if summary.decision_code == "inconclusive":
            note(
                tr(
                    f"要稳定检出 5% 的利润变化，每组约需 {summary.required_sample_per_arm:,} 位客户。",
                    f"To reliably detect a 5% profit change, each group needs about "
                    f"{summary.required_sample_per_arm:,} customers.",
                )
            )
        else:
            note(
                tr(
                    f"这次实验能检出 {money(summary.minimum_detectable_lift, code, decimals=2)} 以上的单客利润变化。",
                    f"This experiment can detect a per-customer change of "
                    f"{money(summary.minimum_detectable_lift, code, decimals=2)} or more.",
                )
            )
        note(
            tr(
                "判断规则：利润明显下降或退货超过护栏就停止；利润区间全部大于 0 才推广；否则继续实验，不下结论。",
                "Rule: stop if profit clearly falls or returns breach the guardrail; ship only when "
                "the whole profit interval is above zero; otherwise keep testing.",
            )
        )
    table_view(metrics.round(4))
    _import_panel()
