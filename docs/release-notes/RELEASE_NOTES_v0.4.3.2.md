# InsightFlow Pro v0.4.3.2

This patch improves filter reliability, small-sample safeguards, customer retention stability, and action-workflow clarity.

## Fixed

- Fixed `AttributeError: 'DatetimeIndex' object has no attribute 'dt'` in customer cohort retention.
- Prevented impossible filter combinations through cascading region → country → category → channel options.
- Option counts now reflect the active date range and upstream filters instead of global warehouse totals.
- Added current filter coverage: transaction rows, orders, and customers.
- Suppressed misleading percentage deltas and diagnostic alerts when the current or comparison period has fewer than five orders.
- Zero-match selections now show a clear no-data message instead of KPI cards showing `0` and `-100%`.
- Renamed the action KPI from “In progress” to “Unresolved” because it includes Open, In Progress, and Blocked items.
- Added an in-product workflow explanation for Open, In Progress, Blocked, Done, and Dismissed.

## Data Hub

- Added two import modes:
  - Append new records.
  - Replace the current transaction warehouse.
- Replace mode is recommended when testing a standalone uploaded dataset without mixing it with the built-in demo history.

## Validation

- 28 automated tests passed.
- Python compilation passed for all source modules.
