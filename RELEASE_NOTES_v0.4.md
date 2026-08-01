# InsightFlow Pro v0.4 Release Notes

## Release focus

v0.4 upgrades InsightFlow from a feature-rich operating dashboard into a more trustworthy and recruiter-ready analytics product. The release focuses on provenance, validation, uncertainty, experimentation, actionability and portfolio presentation.

## Major additions

- Verified / Estimated / Simulated / Mixed data-status labels at source and metric level.
- JSON data contract with schema, required-field, business-key, range, enum and future-date checks.
- In-memory data fault injection for duplicates, null IDs, negative prices, future dates, unknown channels and missing periods.
- Seven-table commerce profile plus an Olist public-data adapter.
- Monte Carlo scenario analysis with 90% ranges, downside probabilities and sensitivity ranking.
- A/B experiment analysis with conversion, revenue, contribution-profit and returns guardrails.
- Business action register with evidence, priority, owner, due date and status.
- Expanded forecast validation using WAPE, sMAPE, MASE and Bias.
- Power BI delivery pack containing model-ready CSVs, DAX measures, relationship diagram and report blueprint.
- Recruiter portfolio landing page, 90-second demo script and business case study.

## Validation performed

- Main curated warehouse: 107,394 rows.
- Seven-table canonical warehouse: 51,137 rows.
- Automated tests: 13 passed.
- Profit and revenue reconciliations passed.
- Incremental-load idempotency passed.
- Data-contract and Olist string-ID regression tests passed.
- HTML and Word reports generated successfully.
- The three-page Word report was rendered and visually checked for clipping, overflow and blank pages.

## Known limitations

- The current environment did not have Streamlit installed, so the browser application was not launched here; all Python modules compiled and backend tests passed.
- A native `.pbix` cannot be generated without Power BI Desktop. The release includes the import tables, DAX, model schema and page blueprint required to build it.
- Demo costs, inventory, targets and experiments remain explicitly labelled as simulated or estimated.
- Enterprise deployment still requires authentication, role-based access, privacy controls, monitoring, backups and approved source owners.
