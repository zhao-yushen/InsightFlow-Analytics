from __future__ import annotations

from pathlib import Path

from .config import DEFAULT_CURRENCY

SYMBOLS = {
    "GBP": "£",
    "USD": "$",
    "EUR": "€",
    "CNY": "¥",
    "JPY": "¥",
    "KRW": "₩",
    "BRL": "R$",
    "HKD": "HK$",
    "SGD": "S$",
    "AUD": "A$",
    "CAD": "C$",
    "INR": "₹",
    "CHF": "CHF ",
    "AED": "AED ",
}
# Public datasets have one known settlement currency, so the label comes from the source.
PROFILE_CURRENCY = {"olist_public": "BRL", "uci_online_retail": "GBP"}


def normalize_code(code: object, default: str = DEFAULT_CURRENCY) -> str:
    text = str(code).strip().upper()
    if text in {"", "NAN", "NONE", "<NA>"}:
        return default
    return {"RMB": "CNY", "CNH": "CNY", "人民币": "CNY", "英镑": "GBP", "美元": "USD"}.get(text, text)


def symbol(code: str) -> str:
    return SYMBOLS.get(code, f"{code} ")


def compact(value: float) -> str:
    """Shorten large magnitudes while keeping the sign, for tight labels."""
    absolute = abs(value)
    if absolute >= 1e9:
        return f"{value / 1e9:.2f}B"
    if absolute >= 1e6:
        return f"{value / 1e6:.2f}M"
    if absolute >= 1e3:
        return f"{value / 1e3:.1f}K"
    return f"{value:,.0f}"


def money(value: float, code: str = DEFAULT_CURRENCY, *, decimals: int = 0, short: bool = False) -> str:
    sign = "−" if value < 0 else ""
    amount = compact(abs(value)) if short else f"{abs(value):,.{decimals}f}"
    return f"{sign}{symbol(code)}{amount}"


def warehouse_currency(db_path: str | Path) -> str:
    """Return the reporting currency recorded when the warehouse was last built."""
    from .warehouse import query_df, table_exists

    if not table_exists(db_path, "data_profiles"):
        return DEFAULT_CURRENCY
    frame = query_df(db_path, "SELECT * FROM data_profiles ORDER BY created_at DESC LIMIT 1")
    if frame.empty or "currency" not in frame.columns:
        return DEFAULT_CURRENCY
    return normalize_code(frame.iloc[0]["currency"])
