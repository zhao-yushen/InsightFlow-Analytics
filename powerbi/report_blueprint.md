# Power BI Report Blueprint

## Page 1 — Executive Overview

- Net Revenue, Contribution Profit, Contribution Margin, Orders and Target Attainment cards.
- Visible data-status chips from `metric_catalog`.
- Monthly revenue/profit trend and target variance.
- Top three open actions.

## Page 2 — Profit Diagnosis

- Contribution-profit waterfall.
- Product revenue versus margin quadrant.
- Country and category contribution decomposition.
- Drill-through to SKU detail.

## Page 3 — Customer and Experiment

- RFM/CLV segments.
- Retention cohort.
- Experiment treatment/control comparison with profit guardrail.

## Page 4 — Inventory and Trust

- Reorder and overstock matrix.
- Data-quality dimensions.
- Contract failures, ETL freshness and data lineage.

## Model Requirements

- One-direction relationships from dimensions to facts.
- Mark `dim_date[date]` as the date table.
- Hide technical keys and raw component columns from report view.
- Add a tooltip page explaining metric definition, source status and confidence.
- Demonstrate row-level security with country or business-owner roles when a real identity source is connected.
