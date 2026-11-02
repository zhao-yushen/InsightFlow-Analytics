# Portfolio Guide

## Recommended order

1. One sentence explaining the business problem.
2. A screenshot of the money river.
3. A 90-second demo video.
4. A case study showing a decision, not only charts.
5. Architecture and metric definitions.
6. Test results and the data-trust statement.

## Claims that are safe to make

- Built an end-to-end analytics platform from messy source files to governed metrics, diagnostics, forecasting, experiments and management reports.
- Fixed a measured bias in elasticity estimation by replacing a quantity-weighted log model with a Poisson fixed-effects estimator.
- Validated a churn model out of time, with a fallback when it fails the standard.
- Reconciled a price-volume-mix bridge to within rounding, enforced by a test.
- Rendered every page in automated tests, with coverage measured across the whole package.

## Claims to avoid

- "Improved company profit" without a real company deployment.
- Quoting the demo's churn AUC as real-world accuracy. The customer lifecycle is simulated.
- "Causal price effect". The elasticity estimate is observational.
- "AI-powered analytics". Analysis is statistical and rule-based; only the optional summary uses an LLM.
- "Production-grade" without identity, authorization, monitoring, backups and operational ownership.
