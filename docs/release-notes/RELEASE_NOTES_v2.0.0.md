# InsightFlow 2.0.0

## Corrected definitions

These change reported numbers. Re-import real data after upgrading.

- Net revenue now deducts refunds, and contribution profit now includes returns. Returns are signed reversal lines.
- Return rate is return orders divided by sale orders.
- Only negative quantity marks a return. An order number starting with `C` no longer does.
- Metric status and quality scores describe the whole warehouse, not the latest batch.
- Net revenue reads as Estimated when the discount was estimated.
- The data contract checks raw values before any rule clips them.
- Experiments call a result only when the evidence supports it, and inconclusive is now a possible outcome.
- Actions keep one identity across date windows, and alerts that stop firing leave the default view.

## New

- Animated money river, tide gauges, simulation drop and draggable market globe.
- Global Markets and Pricing Lab pages.
- Price elasticity estimated from orders, category price moves, and a 245-plan search with guardrails.
- Price-volume-mix profit bridge that reconciles to within rounding.
- Churn model with out-of-time validation and a rule-score fallback.
- Inventory policy with ABC-XYZ classes, service-level safety stock and an order list.
- Market-basket analysis.
- Forecasting adds damped Holt, Holt-Winters, seasonal drift and an ensemble, with 80% and 95% bands.
- A/B analysis adds a sample ratio check, minimum detectable lift, required sample size and real-data import.
- The assistant covers twelve question types and declines the rest.
- Import accepts TSV and JSON, GBK encoding, Chinese headers, regional number formats, Excel serial dates and order statuses, with a field-mapping step.
- Reporting currency, with explicit exchange rates and refusal of unconverted amounts.

## Interface

- Dark hydrographic visual system with a self-hosted typeface and a colour-blind validated palette.
- Every page opens with a generated sentence stating what happened.
- Every chart has a table view, and animations honour the reduced-motion setting.

## Engineering

- All pages are rendered in automated tests, and coverage spans the whole package.
- Version is defined once.
- CI runs on Python 3.11 and 3.13.
- The demo generator now has customer lifecycles, price-responsive demand, complementary products and real return lines.
