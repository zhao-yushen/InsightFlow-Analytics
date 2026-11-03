# InsightFlow 2.0.0

## Corrected definitions

These change reported numbers. Re-import real data after upgrading.

- Net revenue now deducts refunds, and contribution profit now includes returns. Returns are signed reversal lines.
- Return rate is return orders divided by sale orders.
- Only negative quantity marks a return. An order number starting with `C` no longer does.
- Metric status and quality scores describe the whole warehouse, not the latest batch.
- A missing discount column means the price is what was paid. No discount is invented, so net revenue reconciles to the source file.
- Postage, fees, adjustments and vouchers are set aside as non-merchandise and no longer count as sales or refunds.
- Stock levels and suppliers the source does not hold stay empty instead of being simulated.
- Daily demand is net of returns.
- Each product takes the name it most often sold under.
- Default targets follow the last three months for every metric, and are prorated in an unfinished month.
- The data contract checks raw values before any rule clips them. Lines that break it are set aside, with consent, instead of refusing the whole file.
- Experiments call a result only when the evidence supports it, and inconclusive is now a possible outcome.
- Actions keep one identity across date windows, and alerts that stop firing leave the default view.

## New

- Animated money river, tide gauges, simulation drop and draggable market globe.
- Global Markets and Pricing Lab pages.
- Price elasticity estimated from orders and followed per sales stream, with errors clustered by product, and category price moves with a profit range at both ends of the interval.
- A 245-plan search with guardrails, which leaves out discount cuts that cannot be made.
- Price-volume-mix profit bridge that reconciles to within rounding.
- Churn model with out-of-time validation and a rule-score fallback.
- Inventory policy with ABC-XYZ classes, service-level safety stock and an order list.
- Market-basket analysis.
- Forecasting adds damped Holt, Holt-Winters, seasonal drift and an ensemble, with 80% and 95% bands.
- A/B analysis adds a sample ratio check, minimum detectable lift, required sample size and real-data import.
- The assistant covers twelve question types and declines the rest.
- Import accepts TSV and JSON, GBK encoding, Chinese headers, regional number formats, Excel serial dates and order statuses, with a field-mapping step.
- Reporting currency, with explicit exchange rates and refusal of unconverted amounts.
- Workbooks split across yearly sheets are read whole.
- Product families derived from names when the source has no categories.
- 132 countries and territories, with UCI spellings such as EIRE and RSA.
- Comparison against the previous period or the same period last year.
- Shareable links that carry the filters and comparison basis.
- Money-river drill-down by category and market.
- A backup before every import, with restore in Data Hub.
- An optional shared access code.

## Interface

- Dark hydrographic visual system with a self-hosted typeface and a colour-blind validated palette.
- Every page opens with a generated sentence stating what happened.
- Every chart has a table view, and animations honour the reduced-motion setting.
- The river and the globe work from the keyboard.
- An unfinished month is drawn dashed on trend charts.

## Engineering

- All pages are rendered in automated tests, and coverage spans the whole package.
- Version is defined once.
- CI runs on Python 3.11 and 3.13.
- The demo generator now has customer lifecycles, price-responsive demand, complementary products and real return lines.
- Validated end to end on UCI Online Retail II, including a real browser upload. See the validation record.
- Viewing the action list no longer writes to the warehouse, so caches survive and repeat page visits stay under a second.
