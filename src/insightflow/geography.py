from __future__ import annotations

import re
import unicodedata
from collections import OrderedDict

# Canonical market model used by demo generation, imports, filters and BI exports.
# We keep countries and special administrative regions distinct while grouping them
# into a stable market_region for management analysis.
MARKETS = OrderedDict(
    [
        (
            "United Kingdom",
            {"region": "Europe", "weight": 0.300, "shipping": 1.00, "zh-CN": "英国"},
        ),
        ("China", {"region": "Greater China", "weight": 0.090, "shipping": 2.10, "zh-CN": "中国"}),
        ("Germany", {"region": "Europe", "weight": 0.055, "shipping": 1.35, "zh-CN": "德国"}),
        ("France", {"region": "Europe", "weight": 0.050, "shipping": 1.28, "zh-CN": "法国"}),
        (
            "United States",
            {"region": "North America", "weight": 0.040, "shipping": 2.10, "zh-CN": "美国"},
        ),
        ("Netherlands", {"region": "Europe", "weight": 0.032, "shipping": 1.30, "zh-CN": "荷兰"}),
        ("Spain", {"region": "Europe", "weight": 0.028, "shipping": 1.42, "zh-CN": "西班牙"}),
        ("Italy", {"region": "Europe", "weight": 0.028, "shipping": 1.46, "zh-CN": "意大利"}),
        ("Japan", {"region": "East Asia", "weight": 0.025, "shipping": 2.22, "zh-CN": "日本"}),
        ("India", {"region": "South Asia", "weight": 0.024, "shipping": 2.18, "zh-CN": "印度"}),
        ("Poland", {"region": "Europe", "weight": 0.018, "shipping": 1.38, "zh-CN": "波兰"}),
        (
            "South Korea",
            {"region": "East Asia", "weight": 0.018, "shipping": 2.16, "zh-CN": "韩国"},
        ),
        (
            "Australia",
            {"region": "Oceania", "weight": 0.018, "shipping": 2.55, "zh-CN": "澳大利亚"},
        ),
        ("Ireland", {"region": "Europe", "weight": 0.017, "shipping": 1.18, "zh-CN": "爱尔兰"}),
        ("Belgium", {"region": "Europe", "weight": 0.017, "shipping": 1.32, "zh-CN": "比利时"}),
        (
            "Canada",
            {"region": "North America", "weight": 0.014, "shipping": 2.18, "zh-CN": "加拿大"},
        ),
        (
            "Hong Kong SAR",
            {"region": "Greater China", "weight": 0.012, "shipping": 2.08, "zh-CN": "中国香港"},
        ),
        (
            "Singapore",
            {"region": "Southeast Asia", "weight": 0.012, "shipping": 2.05, "zh-CN": "新加坡"},
        ),
        ("Portugal", {"region": "Europe", "weight": 0.011, "shipping": 1.48, "zh-CN": "葡萄牙"}),
        (
            "Malaysia",
            {"region": "Southeast Asia", "weight": 0.010, "shipping": 2.14, "zh-CN": "马来西亚"},
        ),
        (
            "Thailand",
            {"region": "Southeast Asia", "weight": 0.010, "shipping": 2.12, "zh-CN": "泰国"},
        ),
        (
            "Indonesia",
            {"region": "Southeast Asia", "weight": 0.010, "shipping": 2.24, "zh-CN": "印度尼西亚"},
        ),
        ("Sweden", {"region": "Europe", "weight": 0.010, "shipping": 1.52, "zh-CN": "瑞典"}),
        ("Austria", {"region": "Europe", "weight": 0.010, "shipping": 1.36, "zh-CN": "奥地利"}),
        ("Denmark", {"region": "Europe", "weight": 0.009, "shipping": 1.40, "zh-CN": "丹麦"}),
        ("Switzerland", {"region": "Europe", "weight": 0.009, "shipping": 1.58, "zh-CN": "瑞士"}),
        (
            "United Arab Emirates",
            {"region": "Middle East", "weight": 0.009, "shipping": 2.20, "zh-CN": "阿联酋"},
        ),
        ("Norway", {"region": "Europe", "weight": 0.008, "shipping": 1.62, "zh-CN": "挪威"}),
        (
            "New Zealand",
            {"region": "Oceania", "weight": 0.006, "shipping": 2.62, "zh-CN": "新西兰"},
        ),
        (
            "Macao SAR",
            {"region": "Greater China", "weight": 0.003, "shipping": 2.08, "zh-CN": "中国澳门"},
        ),
    ]
)

REGION_LABELS = {
    "Europe": {"zh-CN": "欧洲"},
    "Greater China": {"zh-CN": "大中华区"},
    "East Asia": {"zh-CN": "东亚"},
    "Southeast Asia": {"zh-CN": "东南亚"},
    "South Asia": {"zh-CN": "南亚"},
    "North America": {"zh-CN": "北美"},
    "Oceania": {"zh-CN": "大洋洲"},
    "Middle East": {"zh-CN": "中东"},
    "Other": {"zh-CN": "其他地区"},
}


def _key(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", text)


ALIASES: dict[str, str] = {}


def _register(canonical: str, *aliases: str) -> None:
    for alias in (canonical, *aliases):
        ALIASES[_key(alias)] = canonical


_register(
    "China",
    "CN",
    "PRC",
    "People's Republic of China",
    "Mainland China",
    "中国",
    "中国大陆",
    "中华人民共和国",
)
_register("Hong Kong SAR", "Hong Kong", "HK", "HKSAR", "中国香港", "香港", "香港特别行政区")
_register("Macao SAR", "Macao", "Macau", "MO", "澳门", "中国澳门", "澳门特别行政区")
_register("South Korea", "Korea", "Republic of Korea", "KR", "KOR", "韩国", "大韩民国")
_register("United Kingdom", "UK", "GB", "GBR", "Great Britain", "Britain", "英国")
_register("United States", "US", "USA", "United States of America", "美国")
_register("United Arab Emirates", "UAE", "AE", "阿联酋", "阿拉伯联合酋长国")
_register("Germany", "DE", "Deutschland", "德国")
_register("France", "FR", "法国")
_register("Netherlands", "NL", "Holland", "荷兰")
_register("Spain", "ES", "西班牙")
_register("Belgium", "BE", "比利时")
_register("Italy", "IT", "意大利")
_register("Portugal", "PT", "葡萄牙")
_register("Ireland", "IE", "爱尔兰")
_register("Denmark", "DK", "丹麦")
_register("Sweden", "SE", "瑞典")
_register("Norway", "NO", "挪威")
_register("Poland", "PL", "波兰")
_register("Austria", "AT", "奥地利")
_register("Switzerland", "CH", "瑞士")
_register("Canada", "CA", "加拿大")
_register("Australia", "AU", "澳大利亚", "澳洲")
_register("Japan", "JP", "日本")
_register("India", "IN", "印度")
_register("Singapore", "SG", "新加坡")
_register("Malaysia", "MY", "马来西亚")
_register("Thailand", "TH", "泰国")
_register("Indonesia", "ID", "印度尼西亚", "印尼")
_register("New Zealand", "NZ", "新西兰")


COUNTRIES = list(MARKETS)
COUNTRY_WEIGHTS = [float(MARKETS[name]["weight"]) for name in COUNTRIES]
SHIPPING_MULTIPLIERS = {name: float(meta["shipping"]) for name, meta in MARKETS.items()}


def canonical_country(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.casefold() in {"nan", "none", "<na>", "unknown"}:
        return "Unknown"
    return ALIASES.get(_key(text), text)


def market_region(country: object) -> str:
    canonical = canonical_country(country)
    return str(MARKETS.get(canonical, {}).get("region", "Other"))


def shipping_multiplier(country: object, default: float = 1.25) -> float:
    return float(SHIPPING_MULTIPLIERS.get(canonical_country(country), default))


def country_label(country: object, language: str = "en") -> str:
    canonical = canonical_country(country)
    if canonical == "Unknown":
        return "未知" if language == "zh-CN" else "Unknown"
    if language == "zh-CN":
        return str(MARKETS.get(canonical, {}).get("zh-CN", canonical))
    return canonical


def region_label(region: object, language: str = "en") -> str:
    value = str(region or "Other")
    if language == "zh-CN":
        return str(REGION_LABELS.get(value, {}).get("zh-CN", value))
    return value
