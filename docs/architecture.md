# InsightFlow Pro v0.4 Architecture

## Layers

1. **Sources** — single-file transaction sources, a seven-table demonstration profile, and a public Olist adapter.
2. **Contracts** — required fields, business key, types, ranges, enumerations and future-date controls.
3. **ETL** — canonical mapping, deterministic cleaning, economic derivation, provenance labels and record-hash incremental loading.
4. **Warehouse** — SQLite star schema, monthly KPI views, targets, inventory, experiment tables, metadata, contract results and ETL history.
5. **Semantic and trust layer** — metric definition, owner, status, confidence, source note and lineage.
6. **Analytics** — KPI reconciliation, RFM/CLV baseline, cohorts, root-cause bridges, forecasting, deterministic scenarios, Monte Carlo simulation and A/B analysis.
7. **Action layer** — prioritised issues, evidence, recommended action, owner, due date and downloadable action register.
8. **Delivery** — Streamlit application, Word/HTML/Markdown reports and a Power BI model/DAX package.

## Key controls

- Many-to-one joins use validation in the multi-table adapters.
- Core financial arithmetic is deterministic and covered by reconciliation tests.
- LLM output does not calculate core metrics or execute arbitrary write SQL.
- Estimated and simulated values are visible in the UI and reports.
- Fault injection runs in memory and cannot contaminate the production warehouse.
