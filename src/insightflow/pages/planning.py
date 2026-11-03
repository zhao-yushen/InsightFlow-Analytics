from __future__ import annotations

import pandas as pd
import streamlit as st

from insightflow.config import DEFAULT_DB_PATH
from insightflow.currency import money, symbol
from insightflow.forecasting import forecast_metric
from insightflow.i18n import t, tr
from insightflow.metrics import target_status
from insightflow.narrative import target_table
from insightflow.ui import (
    currency_code,
    note,
    page_header,
    period_meta,
    section_header,
    sidebar_filters,
    subhead,
    table_view,
)
from insightflow.viz import forecast_fan, show


def render() -> None:
    filters = sidebar_filters(DEFAULT_DB_PATH)
    code = currency_code()
    prefix = symbol(code)
    metrics = {
        "revenue": tr("净销售额", "Net revenue"),
        "contribution_profit": tr("贡献利润", "Contribution profit"),
        "orders": tr("订单量", "Orders"),
    }
    metric = st.session_state.get("planning_metric") or "revenue"
    horizon = st.session_state.get("planning_horizon", 3)
    try:
        result = forecast_metric(DEFAULT_DB_PATH, metric, horizon=horizon, filters=filters.undated())
    except ValueError:
        page_header(
            t("page.planning.title"),
            tr("至少需要 6 个月数据才能预测。", "Forecasting needs six months of data."),
            meta=period_meta(filters),
        )
        return
    total = float(result.forecast["forecast"].sum())
    is_money = metric != "orders"
    headline = money(total, code, short=True) if is_money else f"{total:,.0f}"
    low = float(result.forecast["lower"].sum())
    high = float(result.forecast["upper"].sum())
    span = (
        f"{money(low, code, short=True)} ~ {money(high, code, short=True)}"
        if is_money
        else f"{low:,.0f} ~ {high:,.0f}"
    )
    page_header(
        t("page.planning.title"),
        tr(
            f"未来 {horizon} 个月{metrics[metric]}预计 {headline}，较保守和较乐观的情形在 {span} 之间。",
            f"{metrics[metric]} over the next {horizon} months is expected at {headline}, "
            f"with a plausible range of {span}.",
        ),
        meta=period_meta(filters),
    )

    section_header(tr("预测", "Forecast"))
    controls = st.columns([2, 3])
    with controls[0]:
        st.segmented_control(
            tr("指标", "Metric"),
            list(metrics),
            default="revenue",
            format_func=metrics.get,
            key="planning_metric",
        )
    with controls[1]:
        st.slider(tr("预测月数", "Months ahead"), 1, 6, 3, key="planning_horizon")
    show(
        forecast_fan(
            result.history,
            result.forecast,
            metric,
            labels={
                "actual": tr("实际", "Actual"),
                "forecast": tr("预测", "Forecast"),
                "band80": tr("80% 区间", "80% band"),
                "band95": tr("95% 区间", "95% band"),
            },
            money_prefix=prefix if is_money else "",
            height=400,
        ),
        key="planning_forecast",
    )
    if result.dropped_partial_month:
        note(
            tr(
                f"{result.dropped_partial_month} 尚未结束，未计入训练，否则会被误判为下滑。",
                f"{result.dropped_partial_month} is unfinished and left out of training, "
                "as it would otherwise read as a decline.",
            )
        )

    left, right = st.columns([1.3, 1], gap="large")
    with left:
        subhead(tr("模型回测成绩", "Model backtest results"))
        board = result.leaderboard[["model", "wape", "mase", "bias", "n_backtest"]].copy()
        st.dataframe(
            board.rename(
                columns={
                    "model": tr("模型", "Model"),
                    "wape": tr("加权误差", "WAPE"),
                    "mase": "MASE",
                    "bias": tr("偏差", "Bias"),
                    "n_backtest": tr("回测次数", "Backtests"),
                }
            ),
            hide_index=True,
            column_config={
                tr("加权误差", "WAPE"): st.column_config.NumberColumn(format="percent"),
                "MASE": st.column_config.NumberColumn(format="%.2f"),
                tr("偏差", "Bias"): st.column_config.NumberColumn(format="%,.0f"),
            },
        )
        skill = result.skill_vs_naive
        note(
            tr(
                "每个模型都用过去的数据逐月预测下一个月。MASE 小于 1 代表比“沿用上月”更准"
                + (f"，选中模型的误差低 {skill:.0%}。" if skill and skill > 0 else "。"),
                "Each model predicts one month ahead using only earlier data. MASE below 1 beats "
                "repeating last month"
                + (f"; the chosen model is {skill:.0%} more accurate." if skill and skill > 0 else "."),
            )
        )
    with right:
        subhead(tr("预测明细", "Forecast detail"))
        st.dataframe(
            result.forecast[["month", "forecast", "lower", "upper"]].rename(
                columns={
                    "month": tr("月份", "Month"),
                    "forecast": tr("预测值", "Forecast"),
                    "lower": tr("95% 下限", "95% low"),
                    "upper": tr("95% 上限", "95% high"),
                }
            ),
            hide_index=True,
            column_config={
                tr("预测值", "Forecast"): st.column_config.NumberColumn(format="%,.0f"),
                tr("95% 下限", "95% low"): st.column_config.NumberColumn(format="%,.0f"),
                tr("95% 上限", "95% high"): st.column_config.NumberColumn(format="%,.0f"),
            },
        )

    month = str(pd.Timestamp(filters.end_date).to_period("M"))
    section_header(tr(f"{month} 目标完成情况", f"{month} target attainment"))
    target = target_status(DEFAULT_DB_PATH, month)
    if target.empty:
        note(tr("该月份没有目标记录。", "No targets recorded for this month."))
    else:
        attainment = tr("完成度", "Attainment")
        st.dataframe(
            target_table(target, code),
            hide_index=True,
            column_config={
                attainment: st.column_config.ProgressColumn(
                    attainment, min_value=0.0, max_value=1.2, format="percent"
                )
            },
        )
        table_view(target.round(3), tr("查看目标原始记录", "View raw target records"))
