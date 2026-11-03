# Olist Multi-table Import

Place the original Olist CSV files in one directory. InsightFlow expects at least:

- `olist_orders_dataset.csv`
- `olist_order_items_dataset.csv`
- `olist_customers_dataset.csv`
- `olist_products_dataset.csv`
- optional `product_category_name_translation.csv`

Run:

```bash
python scripts/import_olist.py --directory "/path/to/olist" --db data/warehouse/olist.db
```

The adapter uses validated many-to-one joins and converts the source to the canonical order-line grain. Procurement cost, marketing and elasticity are never presented as verified, so metrics built on them read as Estimated. The source holds no stock levels, so inventory is labelled Missing and stockout analysis is not shown.

Olist amounts are in Brazilian reais, so the warehouse reports in BRL. Cancelled and unavailable orders are recorded as a sale plus its reversal, which nets to zero while still counting toward the return rate.
