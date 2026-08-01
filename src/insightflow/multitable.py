from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd

from .demo_data import DemoConfig, generate_demo_transactions


TABLE_FILES = {
    "orders": "orders.csv",
    "order_items": "order_items.csv",
    "customers": "customers.csv",
    "products": "products.csv",
    "payments": "payments.csv",
    "shipments": "shipments.csv",
    "inventory": "inventory.csv",
}


def generate_multitable_demo(output_dir: str | Path, config: DemoConfig | None = None) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    base = config or DemoConfig(n_customers=1600, n_products=100, base_daily_orders=18)
    transactions = generate_demo_transactions(replace(base, seed=base.seed + 17))
    transactions = transactions.reset_index(drop=True)
    transactions["order_item_id"] = transactions.groupby("invoice_no").cumcount() + 1

    customers = (
        transactions.dropna(subset=["customer_id"])
        .groupby("customer_id", as_index=False)
        .agg(country=("country", "last"), acquisition_channel=("channel", "last"))
    )
    customers["customer_segment"] = customers["customer_id"].astype(int).mod(4).map(
        {0: "Value", 1: "Growth", 2: "Core", 3: "Occasional"}
    )

    orders = (
        transactions.groupby("invoice_no", as_index=False)
        .agg(
            customer_id=("customer_id", "last"),
            order_date=("invoice_date", "min"),
            country=("country", "last"),
            channel=("channel", "last"),
            order_status=("quantity", lambda x: "Cancelled" if (x < 0).any() else "Delivered"),
        )
    )
    orders["campaign_id"] = orders["order_date"].astype(str).str[:7].str.replace("-", "")

    item_columns = [
        "invoice_no",
        "order_item_id",
        "stock_code",
        "quantity",
        "unit_price",
        "discount_rate",
        "unit_cost",
        "marketing_cost",
        "return_processing_cost",
    ]
    items = transactions[item_columns].rename(columns={"invoice_no": "order_id"})
    orders = orders.rename(columns={"invoice_no": "order_id"})

    products = (
        transactions.groupby("stock_code", as_index=False)
        .agg(
            description=("description", "last"),
            category=("category", "last"),
            price_elasticity=("price_elasticity", "last"),
            supplier=("supplier", "last"),
        )
    )
    payments = (
        transactions.groupby("invoice_no", as_index=False)
        .agg(payment_fee=("payment_fee", "sum"), gross_order_value=("unit_price", "sum"))
        .rename(columns={"invoice_no": "order_id"})
    )
    shipments = (
        transactions.groupby("invoice_no", as_index=False)
        .agg(shipping_cost=("shipping_cost", "sum"), supplier_lead_days=("supplier_lead_days", "max"))
        .rename(columns={"invoice_no": "order_id"})
    )
    shipments["delivery_days"] = (shipments["supplier_lead_days"].fillna(14) * 0.55).round().clip(1, 30)
    inventory = (
        transactions.groupby("stock_code", as_index=False)
        .agg(
            inventory_on_hand=("inventory_on_hand", "max"),
            reorder_point=("reorder_point", "max"),
            supplier_lead_days=("supplier_lead_days", "max"),
        )
    )

    frames = {
        "orders": orders,
        "order_items": items,
        "customers": customers,
        "products": products,
        "payments": payments,
        "shipments": shipments,
        "inventory": inventory,
    }
    paths: dict[str, Path] = {}
    for name, frame in frames.items():
        path = output / TABLE_FILES[name]
        frame.to_csv(path, index=False)
        paths[name] = path
    return paths


def load_multitable_directory(directory: str | Path) -> pd.DataFrame:
    root = Path(directory)
    tables = {name: pd.read_csv(root / filename) for name, filename in TABLE_FILES.items()}
    merged = tables["order_items"].merge(tables["orders"], on="order_id", how="left", validate="many_to_one")
    merged = merged.merge(tables["customers"], on="customer_id", how="left", validate="many_to_one", suffixes=("", "_customer"))
    merged = merged.merge(tables["products"], on="stock_code", how="left", validate="many_to_one")
    merged = merged.merge(tables["payments"][["order_id", "payment_fee"]], on="order_id", how="left", validate="many_to_one")
    merged = merged.merge(tables["shipments"][["order_id", "shipping_cost"]], on="order_id", how="left", validate="many_to_one")
    merged = merged.merge(tables["inventory"], on="stock_code", how="left", validate="many_to_one")
    order_lines = merged.groupby("order_id")["order_item_id"].transform("count").clip(lower=1)
    merged["payment_fee"] = merged["payment_fee"] / order_lines
    merged["shipping_cost"] = merged["shipping_cost"] / order_lines
    canonical = pd.DataFrame(
        {
            "invoice_no": merged["order_id"],
            "stock_code": merged["stock_code"],
            "description": merged["description"],
            "category": merged["category"],
            "quantity": merged["quantity"],
            "invoice_date": merged["order_date"],
            "unit_price": merged["unit_price"],
            "customer_id": merged["customer_id"],
            "country": merged["country"],
            "channel": merged["channel"],
            "discount_rate": merged["discount_rate"],
            "unit_cost": merged["unit_cost"],
            "shipping_cost": merged["shipping_cost"],
            "payment_fee": merged["payment_fee"],
            "marketing_cost": merged["marketing_cost"],
            "return_processing_cost": merged["return_processing_cost"],
            "price_elasticity": merged["price_elasticity"],
            "supplier": merged["supplier"],
            "supplier_lead_days": merged["supplier_lead_days"],
            "inventory_on_hand": merged["inventory_on_hand"],
            "reorder_point": merged["reorder_point"],
        }
    )
    return canonical


def load_olist_directory(directory: str | Path) -> pd.DataFrame:
    """Load the public Olist multi-table schema into InsightFlow's canonical grain.

    Expected filenames follow the original Olist dataset naming convention. Cost, inventory,
    marketing and elasticity fields are intentionally left absent and will be labelled Estimated
    or Simulated by the ETL provenance layer.
    """
    root = Path(directory)
    orders = pd.read_csv(root / "olist_orders_dataset.csv")
    items = pd.read_csv(root / "olist_order_items_dataset.csv")
    customers = pd.read_csv(root / "olist_customers_dataset.csv")
    products = pd.read_csv(root / "olist_products_dataset.csv")
    translation_path = root / "product_category_name_translation.csv"
    if translation_path.exists():
        translation = pd.read_csv(translation_path)
        products = products.merge(translation, on="product_category_name", how="left")
        products["category"] = products["product_category_name_english"].fillna(products["product_category_name"])
    else:
        products["category"] = products["product_category_name"].fillna("Uncategorized")
    merged = items.merge(orders, on="order_id", how="left", validate="many_to_one")
    merged = merged.merge(customers, on="customer_id", how="left", validate="many_to_one")
    merged = merged.merge(products[["product_id", "category"]], on="product_id", how="left", validate="many_to_one")
    cancelled = merged["order_status"].isin(["canceled", "unavailable"])
    quantity = pd.Series(1, index=merged.index).mask(cancelled, -1)
    return pd.DataFrame(
        {
            "invoice_no": merged["order_id"].mask(cancelled, "C" + merged["order_id"].astype(str)),
            "stock_code": merged["product_id"],
            "description": merged["category"].fillna("PRODUCT"),
            "category": merged["category"].fillna("Uncategorized"),
            "quantity": quantity,
            "invoice_date": merged["order_purchase_timestamp"],
            "unit_price": merged["price"],
            "customer_id": merged["customer_unique_id"],
            "country": "Brazil",
            "channel": "Marketplace",
            "shipping_cost": merged["freight_value"],
        }
    )
