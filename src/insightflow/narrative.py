"""Turn finished analysis into sentences and display payloads.

Pages open with what happened rather than with a chart title. Every figure here comes
from the governed metrics, so a sentence can never drift away from the numbers beside it.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .currency import money, symbol
from .i18n import tr

LEAK_LABELS = (
    ("discount_amount", "折扣", "Discounts"),
    ("returns_value", "退款", "Refunds"),
    ("cogs", "商品成本", "Product cost"),
    ("shipping_cost", "物流", "Shipping"),
    ("payment_fee", "支付", "Payment"),
    ("marketing_cost", "营销", "Marketing"),
    ("return_processing_cost", "退货处理", "Return handling"),
)


def _direction(change: float) -> str:
    return tr("多", "up") if change >= 0 else tr("少", "down")


def overview_story(
    current: dict[str, float],
    previous: dict[str, float],
    bridge: pd.DataFrame | None,
    code: str,
    *,
    comparable: bool = True,
) -> str:
    revenue = money(current["revenue"], code, short=True)
    margin = f"{current['contribution_margin']:.1%}"
    if not comparable or not previous["revenue"]:
        return tr(
            f"本期净销售额 {revenue}，贡献利润率 {margin}。上一周期样本不足，暂不比较。",
            f"Net revenue is {revenue} at a {margin} contribution margin. "
            "The prior period has too few orders to compare.",
        )
    change = current["revenue"] - previous["revenue"]
    rate = change / abs(previous["revenue"])
    gap = money(abs(change), code, short=True)
    opening = tr(
        f"净销售额 {revenue}，比上期{_direction(change)} {gap}（{rate:+.1%}）。",
        f"Net revenue is {revenue}, {_direction(change)} {gap} ({rate:+.1%}) on the prior period.",
    )
    if bridge is None or bridge.empty:
        return opening + tr(f"贡献利润率 {margin}。", f" Contribution margin is {margin}.")
    drag = bridge.sort_values("impact").iloc[0]
    lift = bridge.sort_values("impact").iloc[-1]
    if float(drag["impact"]) >= 0:
        return opening + tr(
            f"贡献利润率 {margin}，各项因素都在推高利润。",
            f" Contribution margin is {margin}, with every driver adding to profit.",
        )
    return opening + tr(
        f"利润最大的助力是{lift['label']}（{money(float(lift['impact']), code, short=True)}），"
        f"最大的拖累是{drag['label']}（{money(float(drag['impact']), code, short=True)}）。",
        f" The biggest profit lift came from {lift['label']} "
        f"({money(float(lift['impact']), code, short=True)}); the biggest drag was "
        f"{drag['label']} ({money(float(drag['impact']), code, short=True)}).",
    )


def river_payload(
    current: dict[str, float], previous: dict[str, float], code: str, *, comparable: bool = True
) -> dict[str, Any]:
    """Describe the money river: where sales start, what leaves, and what stays."""
    gross = max(current["gross_revenue"], 1.0)
    leaks = []
    for key, chinese, english in LEAK_LABELS:
        value = float(current[key])
        before = float(previous.get(key, 0))
        share_of_gross = value / gross
        prior_share = before / max(previous.get("gross_revenue", 0), 1.0)
        change = (share_of_gross - prior_share) * 100
        leaks.append(
            {
                "key": key,
                "label": tr(chinese, english),
                "value": value,
                "display": money(value, code, short=True),
                "share": tr(f"占毛额 {share_of_gross:.1%}", f"{share_of_gross:.1%} of gross"),
                "delta": (
                    tr(f"占比较上期 {change:+.1f} 个百分点", f"{change:+.1f} pts vs prior")
                    if comparable
                    else tr("上期样本不足", "Prior period too small")
                ),
            }
        )
    end = float(current["contribution_profit"])
    return {
        "start": {
            "label": tr("商品毛额", "Gross sales"),
            "value": float(current["gross_revenue"]),
            "display": money(current["gross_revenue"], code, short=True),
        },
        "leaks": leaks,
        "end": {
            "label": tr("贡献利润", "Contribution profit"),
            "value": end,
            "display": money(end, code, short=True),
            "note": tr(
                f"利润率 {current['contribution_margin']:.1%}",
                f"{current['contribution_margin']:.1%} margin",
            ),
        },
        "summary": tr(
            f"商品毛额 {money(gross, code, short=True)}，扣除各项支出后留下贡献利润 "
            f"{money(end, code, short=True)}。",
            f"Gross sales of {money(gross, code, short=True)} leave "
            f"{money(end, code, short=True)} of contribution profit after all outflows.",
        ),
    }


def river_table(current: dict[str, float], code: str) -> pd.DataFrame:
    gross = max(current["gross_revenue"], 1.0)
    rows = [(tr("商品毛额", "Gross sales"), current["gross_revenue"], 1.0)]
    rows += [
        (tr(chinese, english), -current[key], -current[key] / gross)
        for key, chinese, english in LEAK_LABELS
    ]
    rows.append(
        (tr("贡献利润", "Contribution profit"), current["contribution_profit"], current["contribution_profit"] / gross)
    )
    label = tr("项目", "Item")
    amount = tr(f"金额（{code}）", f"Amount ({code})")
    share = tr("占毛额", "Share of gross")
    return pd.DataFrame(rows, columns=[label, amount, share]).round({amount: 0, share: 4})


TARGET_LABELS = {
    "net_revenue": ("净销售额", "Net revenue"),
    "contribution_profit": ("贡献利润", "Contribution profit"),
    "gross_margin": ("毛利率", "Gross margin"),
    "cancellation_rate": ("退货取消率", "Return rate"),
}
STATUS_LABELS = {
    "On Track": ("达标", "On track"),
    "At Risk": ("有风险", "At risk"),
    "Off Track": ("未达标", "Off track"),
}


def target_table(targets: pd.DataFrame, code: str) -> pd.DataFrame:
    """Readable target rows: rates as percents, amounts in the warehouse currency."""

    def shown(metric: str, value: float) -> str:
        return f"{value:.1%}" if metric in {"gross_margin", "cancellation_rate"} else money(value, code, short=True)

    return pd.DataFrame(
        {
            tr("指标", "Metric"): [tr(*TARGET_LABELS.get(m, (m, m))) for m in targets["metric_id"]],
            tr("实际", "Actual"): [
                shown(m, v) for m, v in zip(targets["metric_id"], targets["actual_value"], strict=True)
            ],
            tr("目标", "Target"): [
                shown(m, v) for m, v in zip(targets["metric_id"], targets["target_value"], strict=True)
            ],
            tr("完成度", "Attainment"): targets["attainment"].astype(float).to_numpy(),
            tr("状态", "Status"): [tr(*STATUS_LABELS.get(s, (s, s))) for s in targets["status"]],
        }
    )


def simulation_payload(
    samples: pd.Series, summary: pd.Series, code: str, *, signature: str
) -> dict[str, Any]:
    """Bin simulated outcomes for the drop chart, with the zero line on a bin edge."""
    values = samples.to_numpy(dtype=float)
    low, high = float(values.min()), float(values.max())
    if high <= low:
        high = low + 1.0
    width = (high - low) / 44
    edges = [low + width * i for i in range(45)]
    counts = [0] * 44
    for value in values:
        counts[min(int((value - low) / width), 43)] += 1
    total = len(values)

    def label(value: float) -> str:
        return money(value, code, short=True)

    shares = [
        tr(f"{count / total:.1%} 的模拟落在此区间", f"{count / total:.1%} of simulations")
        for count in counts
    ]
    ranges = [f"{label(edges[i])} ~ {label(edges[i + 1])}" for i in range(44)]
    ticks = [{"value": low + (high - low) * step / 4, "label": label(low + (high - low) * step / 4)} for step in range(5)]
    median = float(summary["median_profit_change"])
    return {
        "edges": edges,
        "counts": counts,
        "median": median,
        "ticks": ticks,
        "binLabels": ranges,
        "binShares": shares,
        "signature": signature,
        "labels": {
            "zero": tr("不变", "No change"),
            "median": tr(f"中位数 {label(median)}", f"Median {label(median)}"),
        },
        "summary": tr(
            f"利润变化中位数 {label(median)}，改善概率 {summary['probability_profit_improves']:.0%}。",
            f"Median profit change {label(median)}, "
            f"{summary['probability_profit_improves']:.0%} chance of improving.",
        ),
    }


def globe_payload(
    markets: pd.DataFrame, labels: pd.Series, code: str, selected: str | None
) -> dict[str, Any]:
    placed = markets.dropna(subset=["lat", "lon"]).sort_values("revenue", ascending=False)
    average = float(placed["contribution_profit"].sum()) / max(float(placed["revenue"].sum()), 1.0)
    rows = [
        {
            "name": row["country"],
            "label": labels.get(row["country"], row["country"]),
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "share": max(float(row["revenue_share"]), 0.0005),
            "strong": bool((row["contribution_margin"] or 0) >= average),
            "revenue": money(float(row["revenue"]), code, short=True),
            "margin": tr(
                f"贡献利润率 {row['contribution_margin']:.1%}",
                f"{row['contribution_margin']:.1%} contribution margin",
            ),
            "shareText": tr(
                f"占净销售额 {row['revenue_share']:.1%}", f"{row['revenue_share']:.1%} of net revenue"
            ),
        }
        for _, row in placed.iterrows()
    ]
    return {
        "markets": rows,
        "selected": selected,
        "symbol": symbol(code),
        "summary": tr(
            f"地球仪显示 {len(rows)} 个市场，气泡大小代表净销售额。",
            f"Globe of {len(rows)} markets; bubble size shows net revenue.",
        ),
    }
