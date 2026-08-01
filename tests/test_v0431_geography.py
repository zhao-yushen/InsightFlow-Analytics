from __future__ import annotations

import numpy as np
import pandas as pd

from insightflow.demo_data import COUNTRIES, COUNTRY_WEIGHTS
from insightflow.etl import clean_transactions
from insightflow.geography import (
    canonical_country,
    country_label,
    market_region,
    region_label,
    shipping_multiplier,
)
from insightflow.metrics import FilterSpec, available_filters, kpi_summary
from insightflow.warehouse import build_warehouse


def _row(invoice_no: str, country: str) -> dict[str, object]:
    return {
        "invoice_no": invoice_no,
        "stock_code": "SKU1",
        "description": "Example item",
        "category": "Electronics",
        "quantity": 1,
        "invoice_date": "2025-01-01",
        "unit_price": 20.0,
        "customer_id": f"C-{invoice_no}",
        "country": country,
        "channel": "Web",
    }


def test_china_and_apac_are_core_demo_markets() -> None:
    assert "China" in COUNTRIES
    assert "Hong Kong SAR" in COUNTRIES
    assert "Macao SAR" in COUNTRIES
    assert "Japan" in COUNTRIES
    assert "South Korea" in COUNTRIES
    assert "Singapore" in COUNTRIES
    assert len(COUNTRIES) >= 28
    assert np.isclose(COUNTRY_WEIGHTS.sum(), 1.0)
    assert COUNTRY_WEIGHTS[COUNTRIES.index("China")] >= 0.07


def test_country_aliases_are_canonicalized_and_localized() -> None:
    assert canonical_country("中国") == "China"
    assert canonical_country("PRC") == "China"
    assert canonical_country("中国香港") == "Hong Kong SAR"
    assert canonical_country("澳门") == "Macao SAR"
    assert canonical_country("Korea") == "South Korea"
    assert country_label("China", "zh-CN") == "中国"
    assert country_label("Hong Kong SAR", "zh-CN") == "中国香港"
    assert region_label("Greater China", "zh-CN") == "大中华区"
    assert market_region("中国") == "Greater China"
    assert shipping_multiplier("中国") == shipping_multiplier("China")


def test_imported_chinese_country_names_feed_region_filter(tmp_path) -> None:
    db = tmp_path / "china.db"
    frame = pd.DataFrame([_row("1001", "中国"), _row("1002", "Japan")])
    result = clean_transactions(frame, transaction_status="Verified")
    assert set(result.curated["country"]) == {"China", "Japan"}
    assert set(result.curated["market_region"]) == {"Greater China", "East Asia"}
    build_warehouse(result, db, load_mode="replace")
    options = available_filters(db)
    assert "China" in options["countries"]
    assert "Greater China" in options["regions"]
    china = kpi_summary(
        db,
        FilterSpec(
            start_date="2025-01-01",
            end_date="2025-01-01",
            regions=("Greater China",),
        ),
    )
    assert china["orders"] == 1
