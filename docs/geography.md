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

This design prevents duplicate markets caused by spelling and language differences while keeping the UI localized.

## Included market regions

- Greater China
- East Asia
- Southeast Asia
- South Asia
- Europe
- North America
- Oceania
- Middle East
- Other, for imported markets without a predefined mapping

## Imported data

The `country` field is required. `market_region` is optional because InsightFlow derives it automatically for known markets. Unknown country values are preserved rather than rejected and receive `Other` as the region until a mapping is added.
