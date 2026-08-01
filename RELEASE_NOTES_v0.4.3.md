# InsightFlow Pro v0.4.3

v0.4.3 focuses on data onboarding, dimension coverage, multilingual navigation, and runtime stability.

## Fixed

- Converted `due_date` from persisted SQLite text to pandas datetime before rendering `st.data_editor`.
- Added datetime conversion for first/last-seen timestamps and explicit numeric/boolean editor dtypes.
- Localized action-status display while preserving stable internal workflow values.
- Retained unique Streamlit URL paths introduced in v0.4.2.1.

## Data and filters

- Expanded the built-in demonstration model to 18 countries/regions, 12 product categories, and 6 sales channels.
- Updated cost, elasticity, discount, payment, marketing, and logistics assumptions for the new dimensions.
- Updated the data contract to accept all six standard channels.
- Added dimension value counts, search, select-all, and clear-all controls.
- Raised sales and root-cause breakdown limits so broader imported datasets are not silently truncated at 15–20 values.
- Confirmed that previously unseen countries, categories, and channels appear automatically after incremental loading.

## Data Hub and near-real-time operation

- Added a Data Hub page for CSV, Excel, and Parquet upload.
- Added validation preview, quality score, contract issues, cleaned-row preview, incremental import, template download, and ETL history.
- Added `insightflow watch --interval 30` for polling `data/incoming`.
- Successful files move to `data/archive`; rejected files move to `data/rejected` with an error JSON record.

## Languages

- Added a global language selector.
- Simplified Chinese and English cover the core interface and static analytical labels.
- Japanese, Korean, Spanish, French, German, and Portuguese provide navigation-level beta localization with English analytical fallback.
- Added English natural-language classification and English answers for the governed analytics assistant.

## Validation

- 22 automated tests pass.
- Added tests for Streamlit-compatible action-editor dtypes.
- Added tests for dimension breadth and normalized dimension weights.
- Added a regression test confirming that new dimension values appear after incremental import.
