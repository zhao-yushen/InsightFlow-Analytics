# InsightFlow Power BI DAX Measure Pack

```DAX
Net Revenue = CALCULATE(SUM(fact_transactions[net_revenue]), fact_transactions[data_valid] = 1)
Gross Revenue = CALCULATE(SUM(fact_transactions[gross_revenue]), fact_transactions[sale_valid] = 1)
Discount Amount = CALCULATE(SUM(fact_transactions[discount_amount]), fact_transactions[sale_valid] = 1)
Refunds = CALCULATE(-SUM(fact_transactions[net_revenue]), fact_transactions[data_valid] = 1, fact_transactions[is_cancellation] = 1)
Gross Profit = CALCULATE(SUM(fact_transactions[gross_profit]), fact_transactions[data_valid] = 1)
Contribution Profit = CALCULATE(SUM(fact_transactions[contribution_profit]), fact_transactions[data_valid] = 1)
Gross Margin = DIVIDE([Gross Profit], [Net Revenue])
Contribution Margin = DIVIDE([Contribution Profit], [Net Revenue])
Orders = CALCULATE(DISTINCTCOUNT(fact_transactions[invoice_no]), fact_transactions[sale_valid] = 1)
Return Orders = CALCULATE(DISTINCTCOUNT(fact_transactions[invoice_no]), fact_transactions[data_valid] = 1, fact_transactions[is_cancellation] = 1)
Return Rate = DIVIDE([Return Orders], [Orders])
Active Customers = CALCULATE(DISTINCTCOUNT(fact_transactions[customer_id]), fact_transactions[sale_valid] = 1)
Units = CALCULATE(SUM(fact_transactions[quantity]), fact_transactions[sale_valid] = 1)
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

Reversal lines carry negative amounts, so net revenue and profit are already after returns. The report should show `data_status` and `confidence` from `metric_catalog` near financial KPIs so estimated or simulated values cannot be mistaken for audited company values.
