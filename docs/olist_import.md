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

The adapter uses validated many-to-one joins and converts the source to the canonical order-line grain. Procurement cost, inventory, marketing and elasticity are intentionally not fabricated as verified fields; downstream metrics label them Estimated or Simulated.
