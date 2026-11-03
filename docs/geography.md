# Geography and Market-Region Model

InsightFlow stores a canonical English market value for stable joins and uses localized labels only in the interface.

## Canonical storage

Examples:

| Imported value | Stored value | Market region | Chinese display |
|---|---|---|---|
| 中国 / PRC / CN / Mainland China | China | Greater China | 中国 |
| 香港 / HK / Hong Kong | Hong Kong SAR | Greater China | 中国香港 |
| 澳门 / Macau / MO | Macao SAR | Greater China | 中国澳门 |
| Korea / KR / 韩国 | South Korea | East Asia | 韩国 |
| EIRE / IE / 爱尔兰 | Ireland | Europe | 爱尔兰 |
| RSA / ZA / 南非 | South Africa | Africa | 南非 |
| USA / US / 美国 | United States | North America | 美国 |
| Unspecified / N/A / 未知 | Unknown | Other | 未知 |

This design prevents duplicate markets caused by spelling and language differences while keeping the UI localized.

About 130 countries and territories are known, by English name, Chinese name and ISO code. Each has a region and a position on the globe.

## Included market regions

- Greater China
- East Asia
- Southeast Asia
- South Asia
- Central Asia
- Europe
- North America
- Latin America
- Middle East
- Africa
- Oceania
- Other, for imported markets without a predefined mapping

## Imported data

The `country` field is required. `market_region` is optional because InsightFlow derives it automatically for known markets. Unknown country values are preserved rather than rejected and receive `Other` as the region until a mapping is added. A market with no known position stays in the ranking table, and the Markets page states what share of revenue is missing from the globe.
