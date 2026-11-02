# InsightFlow Pro v0.4.3.1

v0.4.3.1 is a geographic coverage and localization patch focused on China and the Asia-Pacific market model.

## Geographic model

- Added **China** as a core demonstration market rather than an edge case.
- Expanded the built-in model to **30 countries and regions** across eight market regions.
- Added Hong Kong SAR and Macao SAR as separate operating regions grouped under Greater China.
- Added Japan, South Korea, Singapore, India, Malaysia, Thailand, Indonesia, New Zealand and the United Arab Emirates.
- Rebalanced demonstration weights so China represents a material share of transactions while the United Kingdom remains the largest single market.
- Rebuilt country-specific logistics assumptions for all included markets.

## Canonicalization and imports

- Added canonical country-name normalization for English names, ISO-style abbreviations and common Chinese aliases.
- Values such as `中国`, `PRC`, `CN`, `Mainland China` and `中华人民共和国` are normalized to `China`.
- Values such as `中国香港`, `Hong Kong`, `HK` and `HKSAR` are normalized to `Hong Kong SAR`.
- Imported rows automatically receive a governed `market_region` value.
- Previously unseen countries remain supported and are grouped into `Other` until mapped.

## Interface and BI

- Added a **Market region** filter above country/region filters.
- Added localized Chinese labels such as 中国、中国香港、中国澳门 and 大中华区 while preserving canonical English values in storage.
- Data Hub now reports market-region, country/region, category and channel coverage separately.
- `dim_country` and Power BI exports now include `market_region`.

## Validation

- Rebuilt the ready-to-run warehouse with 107,861 curated transaction rows.
- The warehouse contains 30 countries/regions and eight market regions.
- China contains 10,749 transaction rows in the bundled demonstration data.
- 25 automated tests pass, including country-alias, localization and region-filter regression tests.
