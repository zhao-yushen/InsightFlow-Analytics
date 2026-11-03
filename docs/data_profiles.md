# Data Profiles and Trust Labels

InsightFlow separates software capability from data truth. Every line records independent transaction, discount, economic and inventory statuses:

- **Verified**: supplied by the source and checked by deterministic validation rules.
- **Estimated**: derived from a documented rule because the source lacks the field.
- **Simulated**: generated only for demonstration, testing or scenario planning.
- **Missing**: the source does not hold this data, so nothing is shown in its place.
- **Mixed**: the warehouse holds lines with different statuses, for example a demo warehouse with real rows appended.

A metric takes the status of its weakest input, and its confidence is weighted by rows. Net revenue depends only on the transaction status: with no discount column the price is what was paid, so nothing about revenue has been estimated.

## What is estimated and what stays empty

| Field missing from the source | What happens |
|---|---|
| Discount | Treated as zero. Revenue still reconciles to the file |
| Product cost, shipping, payment, marketing, return handling | Estimated by a documented rule, and every profit figure says so |
| Price elasticity prior | Taken from the category, then replaced by the estimate where the data allows |
| Stock on hand, reorder point | Left empty. Stockout and reorder analysis is not shown, and demand analysis still is |
| Supplier | Recorded as Unknown |
| Supplier lead time | Assumed to be 14 days, used only when stock on hand is supplied |
| Category | Grouped into families from product names when at least 100 products support it |

## Included profiles

### `demo_generated`

All transaction, cost and inventory fields are reproducibly simulated. This profile demonstrates the entire product without pretending that the values are company actuals.

### `multitable_demo`

Seven source tables demonstrate multi-table joins, keys, join validation and canonical modelling. All values remain simulated.

### `uci_online_retail`

Transaction fields are public source observations. Costs and marketing are estimated. Stock levels and suppliers are missing, because the source holds neither.

### `olist_public`

The Olist adapter validates a public multi-table order schema. Orders, customers, products, prices and freight are source observations. Procurement cost and marketing are estimated, and inventory is missing.

## Presentation rule

Financial KPIs must show source status and confidence. Estimated contribution profit must never be described as audited profit. Simulated experiment results must be described as a demonstration of methodology, not a real business outcome.

## Geographic canonicalization

Country and region values are normalized before loading. For example, `中国`, `PRC`, `CN` and `Mainland China` are stored as `China`, while the interface can display `中国`. Known markets receive a governed `market_region`; unknown imported values are preserved and assigned to `Other`. See [Geography and Market-Region Model](geography.md).
