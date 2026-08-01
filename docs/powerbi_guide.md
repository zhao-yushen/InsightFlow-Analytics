# Power BI 接入指南

运行：

```bash
python scripts/export_powerbi.py
```

推荐关系：

- `fact_transactions[customer_id]` → `dim_customer[customer_id]`
- `fact_transactions[stock_code]` → `dim_product[stock_code]`
- `fact_transactions[country]` → `dim_country[country]`
- `fact_transactions[date]` → `dim_date[date]`

推荐DAX指标：

```DAX
Net Revenue = SUM(fact_transactions[net_revenue])
Gross Profit = SUM(fact_transactions[gross_profit])
Contribution Profit = SUM(fact_transactions[contribution_profit])
Gross Margin = DIVIDE([Gross Profit], [Net Revenue])
Contribution Margin = DIVIDE([Contribution Profit], [Net Revenue])
Orders = DISTINCTCOUNT(fact_transactions[invoice_no])
Active Customers = DISTINCTCOUNT(fact_transactions[customer_id])
```

Power BI用于企业BI建模和DAX展示；Streamlit保留预测、模拟、受控问答和自动报告能力。
