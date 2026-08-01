from __future__ import annotations

import pandas as pd

from insightflow.diagnostics import generate_diagnostics
from insightflow.etl import clean_transactions
from insightflow.metrics import (
    FilterSpec,
    cohort_retention,
    filter_coverage,
    filter_dimension_counts,
)
from insightflow.warehouse import build_warehouse


def _row(invoice: str, date: str, country: str, customer: str, category: str = "Electronics", channel: str = "Web"):
    return {
        "invoice_no": invoice,
        "stock_code": f"SKU-{invoice}",
        "description": "Example item",
        "category": category,
        "quantity": 1,
        "invoice_date": date,
        "unit_price": 20.0,
        "customer_id": customer,
        "country": country,
        "channel": channel,
    }


def _warehouse(tmp_path):
    frame = pd.DataFrame(
        [
            _row("1001", "2025-01-05", "China", "C1"),
            _row("1002", "2025-02-05", "China", "C1", channel="Mobile App"),
            _row("1003", "2025-02-10", "Japan", "C2"),
            _row("1004", "2025-03-10", "Japan", "C2", category="Beauty"),
            _row("1005", "2025-03-12", "Germany", "C3", category="Beauty"),
            _row("1006", "2025-03-15", "China", "C4"),
        ]
    )
    db = tmp_path / "filters.db"
    build_warehouse(clean_transactions(frame, transaction_status="Verified"), db, load_mode="replace")
    return db


def test_cascading_filter_counts_and_coverage(tmp_path):
    db = _warehouse(tmp_path)
    filters = FilterSpec("2025-01-01", "2025-03-31", regions=("Greater China",))
    countries = filter_dimension_counts(db, filters, "country")
    assert set(countries) == {"China"}
    coverage = filter_coverage(
        db,
        FilterSpec(
            "2025-01-01",
            "2025-03-31",
            regions=("Greater China",),
            countries=("China",),
            channels=("Mobile App",),
        ),
    )
    assert coverage["orders"] == 1
    assert coverage["customers"] == 1


def test_cohort_retention_formats_datetime_index_without_dt_accessor(tmp_path):
    db = _warehouse(tmp_path)
    retention = cohort_retention(db, FilterSpec("2025-01-01", "2025-03-31"))
    assert not retention.empty
    assert all(isinstance(value, str) and len(value) == 7 for value in retention.index)
    assert "2025-01" in retention.index


def test_diagnostics_are_suppressed_for_tiny_current_sample(tmp_path):
    db = _warehouse(tmp_path)
    filters = FilterSpec(
        "2025-02-01",
        "2025-02-28",
        regions=("Greater China",),
        countries=("China",),
        channels=("Mobile App",),
    )
    issues, _ = generate_diagnostics(db, filters)
    assert issues == []
