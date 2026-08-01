from __future__ import annotations

import numpy as np
import pandas as pd

from insightflow.action_center import prepare_action_editor_frame
from insightflow.demo_data import CATEGORIES, CHANNEL_WEIGHTS, CHANNELS, COUNTRIES, COUNTRY_WEIGHTS
from insightflow.etl import clean_transactions
from insightflow.metrics import available_filters
from insightflow.warehouse import build_warehouse


def test_action_editor_frame_uses_compatible_dtypes() -> None:
    raw = pd.DataFrame(
        {
            "due_date": ["2026-08-05"],
            "first_seen_at": ["2026-08-01T06:00:00+00:00"],
            "last_seen_at": ["2026-08-01T07:00:00+00:00"],
            "confidence": ["0.91"],
            "is_active": [1],
        }
    )
    prepared = prepare_action_editor_frame(raw)
    assert pd.api.types.is_datetime64_any_dtype(prepared["due_date"])
    assert pd.api.types.is_datetime64_any_dtype(prepared["first_seen_at"])
    assert pd.api.types.is_float_dtype(prepared["confidence"])
    assert pd.api.types.is_bool_dtype(prepared["is_active"])


def test_demo_dimensions_are_broad_and_weights_reconcile() -> None:
    assert len(COUNTRIES) >= 28
    assert "China" in COUNTRIES
    assert len(CATEGORIES) >= 10
    assert len(CHANNELS) >= 5
    assert np.isclose(COUNTRY_WEIGHTS.sum(), 1.0)
    assert np.isclose(CHANNEL_WEIGHTS.sum(), 1.0)


def test_new_dimension_values_are_discoverable_after_incremental_load(tmp_path) -> None:
    db = tmp_path / "dimensions.db"
    base = pd.DataFrame(
        [
            {
                "invoice_no": "1001",
                "stock_code": "SKU1",
                "description": "Base item",
                "category": "Kitchen",
                "quantity": 1,
                "invoice_date": "2025-01-01",
                "unit_price": 10.0,
                "customer_id": "C1",
                "country": "United Kingdom",
                "channel": "Web",
            }
        ]
    )
    incoming = pd.DataFrame(
        [
            {
                "invoice_no": "1002",
                "stock_code": "SKU2",
                "description": "New dimension item",
                "category": "Luxury Accessories",
                "quantity": 2,
                "invoice_date": "2025-01-02",
                "unit_price": 30.0,
                "customer_id": "C2",
                "country": "Singapore",
                "channel": "Partner Portal",
            }
        ]
    )
    build_warehouse(clean_transactions(base), db, load_mode="replace")
    build_warehouse(clean_transactions(incoming), db, load_mode="append")
    options = available_filters(db)
    assert "Singapore" in options["countries"]
    assert "Southeast Asia" in options["regions"]
    assert "Luxury Accessories" in options["categories"]
    assert "Partner Portal" in options["channels"]
