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

# Market centres used to place each country on the globe (latitude, longitude).
COORDINATES = {
    "United Kingdom": (54.0, -2.0),
    "China": (35.0, 105.0),
    "Germany": (51.0, 10.0),
    "France": (46.5, 2.5),
    "United States": (39.5, -98.0),
    "Netherlands": (52.2, 5.3),
    "Spain": (40.2, -3.6),
    "Italy": (42.8, 12.6),
    "Japan": (36.5, 138.0),
    "India": (21.0, 78.5),
    "Poland": (52.0, 19.5),
    "South Korea": (36.5, 127.8),
    "Australia": (-25.5, 134.5),
    "Ireland": (53.2, -8.0),
    "Belgium": (50.6, 4.6),
    "Canada": (56.0, -106.0),
    "Hong Kong SAR": (22.3, 114.2),
    "Singapore": (1.35, 103.8),
    "Portugal": (39.6, -8.0),
    "Malaysia": (3.8, 102.0),
    "Thailand": (15.5, 101.0),
    "Indonesia": (-2.5, 118.0),
    "Sweden": (62.0, 15.0),
    "Austria": (47.6, 14.1),
    "Denmark": (56.0, 10.0),
    "Switzerland": (46.8, 8.2),
    "United Arab Emirates": (24.2, 54.4),
    "Norway": (61.0, 8.5),
    "New Zealand": (-41.5, 172.5),
    "Macao SAR": (22.2, 113.55),
    "Brazil": (-14.0, -51.0),
}

# The rest of the world, for ledgers that reach beyond the demo markets:
# ISO code, English name, Chinese name, region, latitude, longitude.
WORLD = (
    ("AL", "Albania", "阿尔巴尼亚", "Europe", 41.0, 20.0),
    ("AD", "Andorra", "安道尔", "Europe", 42.5, 1.5),
    ("BY", "Belarus", "白俄罗斯", "Europe", 53.5, 28.0),
    ("BA", "Bosnia and Herzegovina", "波黑", "Europe", 44.0, 17.8),
    ("BG", "Bulgaria", "保加利亚", "Europe", 42.7, 25.3),
    ("HR", "Croatia", "克罗地亚", "Europe", 45.2, 15.5),
    ("CY", "Cyprus", "塞浦路斯", "Europe", 35.1, 33.3),
    ("CZ", "Czech Republic", "捷克", "Europe", 49.8, 15.5),
    ("EE", "Estonia", "爱沙尼亚", "Europe", 58.7, 25.5),
    ("FI", "Finland", "芬兰", "Europe", 64.0, 26.0),
    ("GR", "Greece", "希腊", "Europe", 39.0, 22.0),
    ("HU", "Hungary", "匈牙利", "Europe", 47.2, 19.4),
    ("IS", "Iceland", "冰岛", "Europe", 64.9, -18.6),
    ("LV", "Latvia", "拉脱维亚", "Europe", 56.9, 24.6),
    ("LI", "Liechtenstein", "列支敦士登", "Europe", 47.2, 9.5),
    ("LT", "Lithuania", "立陶宛", "Europe", 55.2, 23.9),
    ("LU", "Luxembourg", "卢森堡", "Europe", 49.8, 6.1),
    ("MT", "Malta", "马耳他", "Europe", 35.9, 14.4),
    ("MD", "Moldova", "摩尔多瓦", "Europe", 47.2, 28.5),
    ("MC", "Monaco", "摩纳哥", "Europe", 43.7, 7.4),
    ("ME", "Montenegro", "黑山", "Europe", 42.8, 19.3),
    ("MK", "North Macedonia", "北马其顿", "Europe", 41.6, 21.7),
    ("RO", "Romania", "罗马尼亚", "Europe", 45.9, 25.0),
    ("RU", "Russia", "俄罗斯", "Europe", 61.0, 97.0),
    ("RS", "Serbia", "塞尔维亚", "Europe", 44.0, 21.0),
    ("SK", "Slovakia", "斯洛伐克", "Europe", 48.7, 19.5),
    ("SI", "Slovenia", "斯洛文尼亚", "Europe", 46.1, 14.8),
    ("UA", "Ukraine", "乌克兰", "Europe", 49.0, 32.0),
    ("", "Channel Islands", "海峡群岛", "Europe", 49.4, -2.4),
    ("MX", "Mexico", "墨西哥", "North America", 23.6, -102.5),
    ("BM", "Bermuda", "百慕大", "North America", 32.3, -64.8),
    ("AR", "Argentina", "阿根廷", "Latin America", -34.0, -64.0),
    ("BO", "Bolivia", "玻利维亚", "Latin America", -16.3, -63.6),
    ("BR", "Brazil", "巴西", "Latin America", -14.0, -51.0),
    ("CL", "Chile", "智利", "Latin America", -35.7, -71.5),
    ("CO", "Colombia", "哥伦比亚", "Latin America", 4.6, -74.3),
    ("CR", "Costa Rica", "哥斯达黎加", "Latin America", 9.7, -83.8),
    ("CU", "Cuba", "古巴", "Latin America", 21.5, -77.8),
    ("DO", "Dominican Republic", "多米尼加", "Latin America", 18.7, -70.2),
    ("EC", "Ecuador", "厄瓜多尔", "Latin America", -1.8, -78.2),
    ("SV", "El Salvador", "萨尔瓦多", "Latin America", 13.8, -88.9),
    ("GT", "Guatemala", "危地马拉", "Latin America", 15.8, -90.2),
    ("HN", "Honduras", "洪都拉斯", "Latin America", 15.2, -86.2),
    ("JM", "Jamaica", "牙买加", "Latin America", 18.1, -77.3),
    ("NI", "Nicaragua", "尼加拉瓜", "Latin America", 12.9, -85.2),
    ("PA", "Panama", "巴拿马", "Latin America", 8.5, -80.8),
    ("PY", "Paraguay", "巴拉圭", "Latin America", -23.4, -58.4),
    ("PE", "Peru", "秘鲁", "Latin America", -9.2, -75.0),
    ("PR", "Puerto Rico", "波多黎各", "Latin America", 18.2, -66.6),
    ("TT", "Trinidad and Tobago", "特立尼达和多巴哥", "Latin America", 10.7, -61.2),
    ("UY", "Uruguay", "乌拉圭", "Latin America", -32.5, -55.8),
    ("VE", "Venezuela", "委内瑞拉", "Latin America", 6.4, -66.6),
    ("", "West Indies", "西印度群岛", "Latin America", 18.2, -66.5),
    ("BH", "Bahrain", "巴林", "Middle East", 26.0, 50.5),
    ("IR", "Iran", "伊朗", "Middle East", 32.4, 53.7),
    ("IQ", "Iraq", "伊拉克", "Middle East", 33.2, 43.7),
    ("IL", "Israel", "以色列", "Middle East", 31.0, 34.9),
    ("JO", "Jordan", "约旦", "Middle East", 31.0, 36.2),
    ("KW", "Kuwait", "科威特", "Middle East", 29.3, 47.5),
    ("LB", "Lebanon", "黎巴嫩", "Middle East", 33.9, 35.9),
    ("OM", "Oman", "阿曼", "Middle East", 21.5, 55.9),
    ("QA", "Qatar", "卡塔尔", "Middle East", 25.4, 51.2),
    ("SA", "Saudi Arabia", "沙特阿拉伯", "Middle East", 23.9, 45.1),
    ("TR", "Turkey", "土耳其", "Middle East", 39.0, 35.2),
    ("DZ", "Algeria", "阿尔及利亚", "Africa", 28.0, 1.7),
    ("AO", "Angola", "安哥拉", "Africa", -11.2, 17.9),
    ("CM", "Cameroon", "喀麦隆", "Africa", 7.4, 12.4),
    ("EG", "Egypt", "埃及", "Africa", 26.8, 30.8),
    ("ET", "Ethiopia", "埃塞俄比亚", "Africa", 9.1, 40.5),
    ("GH", "Ghana", "加纳", "Africa", 7.9, -1.0),
    ("CI", "Ivory Coast", "科特迪瓦", "Africa", 7.5, -5.5),
    ("KE", "Kenya", "肯尼亚", "Africa", 0.0, 37.9),
    ("MU", "Mauritius", "毛里求斯", "Africa", -20.3, 57.6),
    ("MA", "Morocco", "摩洛哥", "Africa", 31.8, -7.1),
    ("NG", "Nigeria", "尼日利亚", "Africa", 9.1, 8.7),
    ("SN", "Senegal", "塞内加尔", "Africa", 14.5, -14.5),
    ("ZA", "South Africa", "南非", "Africa", -30.6, 22.9),
    ("TZ", "Tanzania", "坦桑尼亚", "Africa", -6.4, 34.9),
    ("TN", "Tunisia", "突尼斯", "Africa", 33.9, 9.5),
    ("UG", "Uganda", "乌干达", "Africa", 1.4, 32.3),
    ("ZM", "Zambia", "赞比亚", "Africa", -13.1, 27.8),
    ("ZW", "Zimbabwe", "津巴布韦", "Africa", -19.0, 29.2),
    ("KZ", "Kazakhstan", "哈萨克斯坦", "Central Asia", 48.0, 66.9),
    ("KG", "Kyrgyzstan", "吉尔吉斯斯坦", "Central Asia", 41.2, 74.8),
    ("TJ", "Tajikistan", "塔吉克斯坦", "Central Asia", 38.9, 71.3),
    ("TM", "Turkmenistan", "土库曼斯坦", "Central Asia", 39.0, 59.6),
    ("UZ", "Uzbekistan", "乌兹别克斯坦", "Central Asia", 41.4, 64.6),
    ("AF", "Afghanistan", "阿富汗", "South Asia", 33.9, 67.7),
    ("BD", "Bangladesh", "孟加拉国", "South Asia", 23.7, 90.4),
    ("LK", "Sri Lanka", "斯里兰卡", "South Asia", 7.9, 80.8),
    ("MV", "Maldives", "马尔代夫", "South Asia", 3.2, 73.2),
    ("NP", "Nepal", "尼泊尔", "South Asia", 28.4, 84.1),
    ("PK", "Pakistan", "巴基斯坦", "South Asia", 30.4, 69.3),
    ("KH", "Cambodia", "柬埔寨", "Southeast Asia", 12.6, 105.0),
    ("LA", "Laos", "老挝", "Southeast Asia", 19.9, 102.5),
    ("MM", "Myanmar", "缅甸", "Southeast Asia", 21.9, 95.9),
    ("PH", "Philippines", "菲律宾", "Southeast Asia", 12.9, 121.8),
    ("VN", "Vietnam", "越南", "Southeast Asia", 14.1, 108.3),
    ("TW", "Taiwan", "中国台湾", "Greater China", 23.7, 121.0),
    ("MN", "Mongolia", "蒙古", "East Asia", 46.9, 103.8),
    ("FJ", "Fiji", "斐济", "Oceania", -17.7, 178.1),
    ("PG", "Papua New Guinea", "巴布亚新几内亚", "Oceania", -6.3, 143.9),
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
    "Latin America": {"zh-CN": "拉丁美洲"},
    "Africa": {"zh-CN": "非洲"},
    "Central Asia": {"zh-CN": "中亚"},
    "Other": {"zh-CN": "其他地区"},
}
# Freight index for places without their own entry in MARKETS.
REGION_SHIPPING = {
    "Europe": 1.45,
    "North America": 2.15,
    "Latin America": 2.40,
    "Middle East": 2.20,
    "Africa": 2.60,
    "Central Asia": 2.30,
    "South Asia": 2.20,
    "Southeast Asia": 2.15,
    "Greater China": 2.10,
    "East Asia": 2.20,
    "Oceania": 2.60,
}
UNKNOWN_COUNTRY_VALUES = frozenset(
    {"nan", "none", "<na>", "n/a", "unknown", "unspecified", "未知", "不详", "未指定"}
)


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
_register("Ireland", "EIRE", "Republic of Ireland")
_register("South Africa", "RSA")
_register("Czech Republic", "Czechia")
_register("Channel Islands", "Jersey", "Guernsey")
_register("Ivory Coast", "Cote d'Ivoire", "Côte d'Ivoire")
_register("Turkey", "Türkiye", "Turkiye")
_register("Vietnam", "Viet Nam")
_register("Russia", "Russian Federation")
_register("South Korea", "Korea, Republic of")
_register("Germany", "DEU")
_register("France", "FRA")
_register("Spain", "ESP")
_register("Italy", "ITA")
_register("Netherlands", "NLD", "The Netherlands")
_register("Japan", "JPN")
_register("China", "CHN")
_register("Australia", "AUS")
_register("Canada", "CAN")
_register("India", "IND")
_register("Brazil", "BRA", "Brasil")
_register("Mexico", "MEX")
_register("Russia", "RUS")

for _code, _name, _chinese, _region, _lat, _lon in WORLD:
    _register(_name, _chinese, *((_code,) if _code else ()))
    COORDINATES[_name] = (_lat, _lon)

REGIONS = {name: str(meta["region"]) for name, meta in MARKETS.items()}
REGIONS.update({row[1]: row[3] for row in WORLD})
REGIONS["European Community"] = "Europe"
CHINESE_NAMES = {name: str(meta["zh-CN"]) for name, meta in MARKETS.items()}
CHINESE_NAMES.update({row[1]: row[2] for row in WORLD})
CHINESE_NAMES["European Community"] = "欧洲共同体"

COUNTRIES = list(MARKETS)
COUNTRY_WEIGHTS = [float(MARKETS[name]["weight"]) for name in COUNTRIES]
SHIPPING_MULTIPLIERS = {name: float(meta["shipping"]) for name, meta in MARKETS.items()}


def canonical_country(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.casefold() in UNKNOWN_COUNTRY_VALUES:
        return "Unknown"
    return ALIASES.get(_key(text), text)


def market_region(country: object) -> str:
    return REGIONS.get(canonical_country(country), "Other")


def market_coordinates(country: object) -> tuple[float, float] | None:
    return COORDINATES.get(canonical_country(country))


def shipping_multiplier(country: object, default: float = 1.25) -> float:
    canonical = canonical_country(country)
    if canonical in SHIPPING_MULTIPLIERS:
        return SHIPPING_MULTIPLIERS[canonical]
    return REGION_SHIPPING.get(REGIONS.get(canonical, ""), default)


def country_label(country: object, language: str = "en") -> str:
    canonical = canonical_country(country)
    if canonical == "Unknown":
        return "未知" if language == "zh-CN" else "Unknown"
    if language == "zh-CN":
        return CHINESE_NAMES.get(canonical, canonical)
    return canonical


def region_label(region: object, language: str = "en") -> str:
    value = str(region or "Other")
    if language == "zh-CN":
        return str(REGION_LABELS.get(value, {}).get("zh-CN", value))
    return value
