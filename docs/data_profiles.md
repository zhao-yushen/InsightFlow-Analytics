# Data Profiles and Trust Labels

InsightFlow separates software capability from data truth. Every loaded warehouse records three independent statuses:

- **Verified**: supplied by the source and checked by deterministic validation rules.
- **Estimated**: derived from a documented rule because the source lacks the field.
- **Simulated**: generated only for demonstration, testing or scenario planning.
- **Mixed**: the displayed metric combines more than one status.

## Included profiles

### `demo_generated`

All transaction, cost and inventory fields are reproducibly simulated. This profile demonstrates the entire product without pretending that the values are company actuals.

### `multitable_demo`

Seven source tables demonstrate multi-table joins, keys, join validation and canonical modelling. All values remain simulated.

### `uci_online_retail`

Transaction fields can be treated as public source observations. Cost, marketing, elasticity, supplier and inventory fields are estimated or simulated because the source does not contain them.

### `olist_public`

The Olist adapter validates a public multi-table order schema. Orders, customers, products, prices and freight are source observations; procurement cost, marketing, inventory and elasticity remain estimated or simulated.

## Presentation rule

Financial KPIs must show source status and confidence. Estimated contribution profit must never be described as audited profit. Simulated experiment results must be described as a demonstration of methodology, not a real business outcome.

## Geographic canonicalization

Country and region values are normalized before loading. For example, `中国`, `PRC`, `CN` and `Mainland China` are stored as `China`, while the interface can display `中国`. Known markets receive a governed `market_region`; unknown imported values are preserved and assigned to `Other`. See [Geography and Market-Region Model](geography.md).
