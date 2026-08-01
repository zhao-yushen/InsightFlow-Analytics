# InsightFlow Power BI DAX Measure Pack

```DAX
Net Revenue = SUM(fact_transactions[net_revenue])
Gross Revenue = SUM(fact_transactions[gross_revenue])
Discount Amount = SUM(fact_transactions[discount_amount])
Gross Profit = SUM(fact_transactions[gross_profit])
Contribution Profit = SUM(fact_transactions[contribution_profit])
Gross Margin = DIVIDE([Gross Profit], [Net Revenue])
Contribution Margin = DIVIDE([Contribution Profit], [Net Revenue])
Orders = DISTINCTCOUNT(fact_transactions[invoice_no])
Active Customers = DISTINCTCOUNT(fact_transactions[customer_id])
Units = SUM(fact_transactions[quantity])
Average Order Value = DIVIDE([Net Revenue], [Orders])
Revenue MoM =
VAR PreviousMonth = CALCULATE([Net Revenue], DATEADD(dim_date[date], -1, MONTH))
RETURN DIVIDE([Net Revenue] - PreviousMonth, PreviousMonth)
Revenue YoY =
VAR PreviousYear = CALCULATE([Net Revenue], SAMEPERIODLASTYEAR(dim_date[date]))
RETURN DIVIDE([Net Revenue] - PreviousYear, PreviousYear)
Rolling 3M Revenue = CALCULATE([Net Revenue], DATESINPERIOD(dim_date[date], MAX(dim_date[date]), -3, MONTH))
Target Value = MAX(business_targets[target_value])
Target Attainment = DIVIDE([Net Revenue], [Target Value])
Experiment Profit Lift =
VAR Treatment = CALCULATE(AVERAGE(experiment_assignments[contribution_profit]), experiment_assignments[assignment] = "Treatment")
VAR Control = CALCULATE(AVERAGE(experiment_assignments[contribution_profit]), experiment_assignments[assignment] = "Control")
RETURN Treatment - Control
```

The report should show `data_status` and `confidence` from `metric_catalog` near financial KPIs so estimated or simulated values cannot be mistaken for audited company values.
