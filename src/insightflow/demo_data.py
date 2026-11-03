from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .geography import (
    COUNTRIES,
    market_region,
    shipping_multiplier,
)
from .geography import (
    COUNTRY_WEIGHTS as COUNTRY_WEIGHT_VALUES,
)


@dataclass(frozen=True)
class DemoConfig:
    seed: int = 20260801
    start: str = "2024-01-01"
    end: str = "2025-12-31"
    n_customers: int = 3000
    n_products: int = 180
    base_daily_orders: int = 45
    min_daily_orders: int = 20


CATEGORIES = {
    "Home Decor": (6.0, 42.0),
    "Kitchen": (4.0, 28.0),
    "Gifts": (2.0, 24.0),
    "Stationery": (1.2, 12.0),
    "Seasonal": (3.0, 35.0),
    "Wellness": (5.0, 32.0),
    "Electronics": (18.0, 160.0),
    "Beauty": (4.0, 48.0),
    "Apparel": (7.0, 75.0),
    "Sports & Outdoors": (8.0, 95.0),
    "Pet Supplies": (3.0, 55.0),
    "Books & Media": (2.0, 36.0),
}
CATEGORY_COST_RATIO = {
    "Home Decor": 0.48,
    "Kitchen": 0.52,
    "Gifts": 0.44,
    "Stationery": 0.39,
    "Seasonal": 0.56,
    "Wellness": 0.46,
    "Electronics": 0.67,
    "Beauty": 0.43,
    "Apparel": 0.51,
    "Sports & Outdoors": 0.57,
    "Pet Supplies": 0.49,
    "Books & Media": 0.45,
}
CATEGORY_ELASTICITY = {
    "Home Decor": -1.35,
    "Kitchen": -1.15,
    "Gifts": -1.55,
    "Stationery": -1.80,
    "Seasonal": -1.95,
    "Wellness": -1.10,
    "Electronics": -1.25,
    "Beauty": -1.45,
    "Apparel": -1.70,
    "Sports & Outdoors": -1.40,
    "Pet Supplies": -1.05,
    "Books & Media": -1.60,
}
COUNTRY_WEIGHTS = np.array(COUNTRY_WEIGHT_VALUES, dtype=float)
COUNTRY_WEIGHTS /= COUNTRY_WEIGHTS.sum()
CHANNELS = ["Web", "Marketplace", "Wholesale", "Mobile App", "Retail Store", "Social Commerce"]
CHANNEL_WEIGHTS = np.array([0.43, 0.19, 0.10, 0.16, 0.08, 0.04], dtype=float)
CHANNEL_WEIGHTS /= CHANNEL_WEIGHTS.sum()


def _product_catalog(rng: np.random.Generator, n_products: int) -> pd.DataFrame:
    cats = rng.choice(list(CATEGORIES), size=n_products)
    records = []
    suppliers = ["Northstar Supply", "BluePeak Trading", "Oakline Goods", "Meridian Wholesale"]
    for idx, category in enumerate(cats, start=1):
        lo, hi = CATEGORIES[category]
        base_price = float(np.round(rng.uniform(lo, hi), 2))
        cost_ratio = float(np.clip(rng.normal(CATEGORY_COST_RATIO[category], 0.035), 0.28, 0.72))
        unit_cost = round(base_price * cost_ratio, 2)
        popularity = float(rng.lognormal(mean=0.0, sigma=0.85))
        lead_days = int(rng.integers(7, 35))
        on_hand = int(np.clip(rng.lognormal(5.1, 0.75), 35, 1700))
        reorder_point = int(max(15, on_hand * rng.uniform(0.14, 0.32)))
        records.append(
            {
                "stock_code": f"SKU{idx:04d}",
                "description": f"{category.upper()} ITEM {idx:04d}",
                "category": category,
                "base_price": base_price,
                "unit_cost": unit_cost,
                "price_elasticity": CATEGORY_ELASTICITY[category] + rng.normal(0, 0.12),
                "supplier": rng.choice(suppliers),
                "supplier_lead_days": lead_days,
                "inventory_on_hand": on_hand,
                "reorder_point": reorder_point,
                "popularity": popularity,
            }
        )
    catalog = pd.DataFrame(records)
    catalog["product_weight"] = catalog["popularity"] / catalog["popularity"].sum()
    return catalog


def _discount_rate(
    rng: np.random.Generator,
    date: pd.Timestamp,
    channel: str,
    category: str,
) -> float:
    base = {
        "Web": 0.025,
        "Marketplace": 0.055,
        "Wholesale": 0.085,
        "Mobile App": 0.035,
        "Retail Store": 0.020,
        "Social Commerce": 0.070,
    }[channel]
    if date.month in (11, 12):
        base += 0.025
    if category == "Seasonal" and date.month in (1, 2):
        base += 0.055
    return float(np.clip(rng.normal(base, 0.018), 0, 0.22))


def _customer_book(
    rng: np.random.Generator, n_customers: int, n_days: int
) -> dict[str, np.ndarray]:
    """Give customers a start, a lifetime and a buying rate, so churn is learnable."""
    return {
        "join_day": rng.integers(-240, max(2, int(n_days * 0.85)), size=n_customers),
        "lifetime": rng.exponential(460.0, size=n_customers) + 30,
        "rate": rng.lognormal(0.0, 0.9, size=n_customers),
        "country": rng.choice(len(COUNTRIES), size=n_customers, p=COUNTRY_WEIGHTS),
        "channel": rng.choice(len(CHANNELS), size=n_customers, p=CHANNEL_WEIGHTS),
    }


def _active_weights(book: dict[str, np.ndarray], day: int) -> np.ndarray:
    active = (book["join_day"] <= day) & (day < book["join_day"] + book["lifetime"])
    weights = book["rate"] * active
    total = weights.sum()
    if total <= 0:
        return book["rate"] / book["rate"].sum()
    return weights / total


def _complement_pairs(rng: np.random.Generator, products: pd.DataFrame) -> np.ndarray:
    """Pair some products within a category so baskets carry a real attachment signal."""
    partner = np.full(len(products), -1, dtype=int)
    for _, group in products.groupby("category"):
        members = rng.permutation(group.index.to_numpy())
        for left, right in zip(members[:-1:2], members[1::2], strict=False):
            if rng.random() < 0.55:
                partner[left], partner[right] = right, left
    return partner


def generate_demo_transactions(config: DemoConfig | None = None) -> pd.DataFrame:
    config = config or DemoConfig()
    rng = np.random.default_rng(config.seed)
    dates = pd.date_range(config.start, config.end, freq="D")
    last_date = dates[-1]
    products = _product_catalog(rng, config.n_products)
    book = _customer_book(rng, config.n_customers, len(dates))
    partner = _complement_pairs(rng, products)

    # Weekly promotions move price, and price moves demand through each product's
    # elasticity. Estimating elasticity from this ledger therefore recovers real signal.
    n_weeks = len(dates) // 7 + 2
    on_promotion = rng.random((config.n_products, n_weeks)) < 0.14
    depth = rng.uniform(0.80, 0.94, size=(config.n_products, n_weeks))
    price_index = np.where(on_promotion, depth, 1.0)
    elasticity = products["price_elasticity"].to_numpy()
    popularity = products["product_weight"].to_numpy()
    pick_weights = popularity[:, None] * price_index ** elasticity[:, None]
    pick_weights = pick_weights / pick_weights.sum(axis=0, keepdims=True)

    catalog = products.to_dict("records")
    rows: list[dict] = []
    invoice_counter = 100000

    for day, date in enumerate(dates):
        month = date.month
        weekday = date.weekday()
        seasonal = 1.0
        if month in (10, 11, 12):
            seasonal *= 1.38
        elif month in (1, 2):
            seasonal *= 0.82
        if weekday >= 5:
            seasonal *= 0.83

        # Deliberate final-quarter slowdown and cost pressure for diagnostic demos.
        if date >= pd.Timestamp("2025-10-01"):
            seasonal *= 0.91
        if date >= pd.Timestamp("2025-12-01"):
            seasonal *= 0.87

        n_orders = max(
            config.min_daily_orders, int(rng.poisson(config.base_daily_orders * seasonal))
        )
        buyers = rng.choice(config.n_customers, size=n_orders, p=_active_weights(book, day))
        week = day // 7
        for buyer in buyers:
            invoice_counter += 1
            country = COUNTRIES[int(book["country"][buyer])]
            channel = (
                CHANNELS[int(book["channel"][buyer])]
                if rng.random() < 0.8
                else str(rng.choice(CHANNELS, p=CHANNEL_WEIGHTS))
            )
            customer_id = 10000 + int(buyer)
            n_lines = int(np.clip(rng.poisson(2.3) + 1, 1, min(10, config.n_products)))
            picked = list(
                rng.choice(
                    config.n_products, size=n_lines, replace=False, p=pick_weights[:, week]
                )
            )
            for product_idx in list(picked):
                companion = int(partner[product_idx])
                if companion >= 0 and companion not in picked and rng.random() < 0.4:
                    picked.append(companion)

            cancel_prob = 0.022
            if country == "Germany" and date >= pd.Timestamp("2025-11-01"):
                cancel_prob = 0.09
            is_returned = bool(rng.random() < cancel_prob)
            ordered_at = date + pd.to_timedelta(int(rng.integers(8, 21)), unit="h")
            shared = {
                "customer_id": customer_id,
                "country": country,
                "market_region": market_region(country),
                "channel": channel,
            }
            order_rows: list[dict] = []
            for product_idx in picked:
                product = catalog[int(product_idx)]
                category = str(product["category"])
                quantity = int(np.clip(rng.geometric(0.42), 1, 18))
                if channel == "Wholesale":
                    quantity = int(np.clip(quantity * rng.integers(2, 6), 2, 60))
                price_noise = rng.normal(1.0, 0.012)
                unit_price = round(
                    max(
                        0.2,
                        float(product["base_price"])
                        * float(price_index[int(product_idx), week])
                        * price_noise,
                    ),
                    2,
                )
                discount_rate = _discount_rate(rng, date, channel, category)

                # Cost pressure is intentionally introduced in late 2025.
                cost_pressure = 1.0
                if date >= pd.Timestamp("2025-09-01") and category in {"Seasonal", "Home Decor"}:
                    cost_pressure = 1.10
                unit_cost = round(float(product["unit_cost"]) * cost_pressure, 2)

                gross_value = quantity * unit_price
                country_shipping = shipping_multiplier(country)
                channel_shipping = {
                    "Web": 1.00,
                    "Marketplace": 1.08,
                    "Wholesale": 0.72,
                    "Mobile App": 1.00,
                    "Retail Store": 0.45,
                    "Social Commerce": 1.12,
                }[channel]
                shipping_cost = round(
                    (1.15 + 0.16 * quantity) * country_shipping * channel_shipping, 2
                )
                payment_fee_rate = {
                    "Web": 0.018,
                    "Marketplace": 0.026,
                    "Wholesale": 0.008,
                    "Mobile App": 0.020,
                    "Retail Store": 0.012,
                    "Social Commerce": 0.030,
                }[channel]
                marketing_rate = {
                    "Web": 0.052,
                    "Marketplace": 0.036,
                    "Wholesale": 0.012,
                    "Mobile App": 0.046,
                    "Retail Store": 0.028,
                    "Social Commerce": 0.080,
                }[channel]
                payment_fee = round(gross_value * (1 - discount_rate) * payment_fee_rate, 2)
                marketing_cost = round(gross_value * marketing_rate * rng.uniform(0.85, 1.15), 2)
                order_rows.append(
                    {
                        "invoice_no": str(invoice_counter),
                        "stock_code": product["stock_code"],
                        "description": product["description"],
                        "category": category,
                        "quantity": quantity,
                        "invoice_date": ordered_at,
                        "unit_price": unit_price,
                        "discount_rate": round(discount_rate, 4),
                        "unit_cost": unit_cost,
                        "shipping_cost": shipping_cost,
                        "payment_fee": payment_fee,
                        "marketing_cost": marketing_cost,
                        "return_processing_cost": 0.0,
                        "price_elasticity": round(float(product["price_elasticity"]), 3),
                        "supplier": product["supplier"],
                        "supplier_lead_days": int(product["supplier_lead_days"]),
                        "inventory_on_hand": int(product["inventory_on_hand"]),
                        "reorder_point": int(product["reorder_point"]),
                        **shared,
                    }
                )
            rows.extend(order_rows)
            if is_returned:
                # A return arrives later and undoes the sale; only handling is new money.
                returned_at = min(
                    ordered_at + pd.to_timedelta(int(rng.integers(1, 15)), unit="D"),
                    last_date + pd.to_timedelta(20, unit="h"),
                )
                for line in order_rows:
                    rows.append(
                        {
                            **line,
                            "invoice_no": f"C{invoice_counter}",
                            "quantity": -int(line["quantity"]),
                            "invoice_date": returned_at,
                            "shipping_cost": 0.0,
                            "payment_fee": 0.0,
                            "marketing_cost": 0.0,
                            "return_processing_cost": round(float(rng.uniform(2.0, 6.5)), 2),
                        }
                    )

    df = pd.DataFrame(rows)

    # Add realistic quality issues for the audit layer.
    if len(df) > 100:
        missing_idx = rng.choice(df.index, size=max(20, len(df) // 120), replace=False)
        df.loc[missing_idx, "customer_id"] = np.nan
        zero_price_idx = rng.choice(df.index, size=max(5, len(df) // 3000), replace=False)
        df.loc[zero_price_idx, "unit_price"] = 0.0
        typo_idx = rng.choice(df.index, size=max(10, len(df) // 1600), replace=False)
        df.loc[typo_idx, "description"] = df.loc[typo_idx, "description"].str.lower()
        duplicate_sample = df.sample(n=max(25, len(df) // 1200), random_state=config.seed)
        df = pd.concat([df, duplicate_sample], ignore_index=True)

    return df.sample(frac=1, random_state=config.seed).reset_index(drop=True)


def write_demo_csv(path: str | Path, config: DemoConfig | None = None) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    df = generate_demo_transactions(config)
    df.to_csv(output, index=False)
    return output
