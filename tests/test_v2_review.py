"""Regressions for defects found while reviewing the 2.0 code."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from insightflow.basket import association_rules
from insightflow.diagnostics import generate_diagnostics, monthly_anomalies
from insightflow.etl import clean_transactions, load_source, read_excel_transactions
from insightflow.experiments import MAX_BOOTSTRAP_ROWS, _bootstrap_difference
from insightflow.forecasting import forecast_metric
from insightflow.ingest import parse_datetime, parse_number, read_table
from insightflow.metrics import FilterSpec, kpi_summary
from insightflow.reporting import render_html_report
from insightflow.warehouse import build_warehouse


def _ledger_rows(year: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Invoice": [f"{year}-1", f"{year}-2"],
            "StockCode": ["A", "B"],
            "Description": ["Mug", "Plate"],
            "Quantity": [1, 2],
            "InvoiceDate": [f"{year}-03-01", f"{year}-03-02"],
            "Price": [10.0, 5.0],
            "Customer ID": [1, 2],
            "Country": ["United Kingdom", "France"],
        }
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("EUR 45", 45.0),
        ("Price 45", 45.0),
        ("USD 1,299.00", 1299.0),
        ("12.50-", -12.5),
        ("−12.5", -12.5),
        ("１２．５", 12.5),
        ("1.234.567", 1234567.0),
        ("1,234,567", 1234567.0),
        ("n/a", np.nan),
        ("1.5e3", 1500.0),
    ],
)
def test_numbers_survive_letters_and_regional_marks(raw, expected):
    parsed = parse_number(pd.Series([raw], dtype="object")).iloc[0]
    assert (np.isnan(parsed) and np.isnan(expected)) or parsed == pytest.approx(expected)


def test_number_columns_mixing_clean_and_messy_cells():
    parsed = parse_number(pd.Series(["10.5", "¥20", None, "bad"], dtype="object"))
    assert parsed.iloc[0] == 10.5
    assert parsed.iloc[1] == 20
    assert parsed.iloc[2:].isna().all()


@pytest.mark.parametrize(
    "value",
    [20250301, 45717, 1740787200, 1740787200000],
)
def test_numeric_dates_cover_common_export_forms(value):
    parsed = parse_datetime(pd.Series([value])).iloc[0]
    assert parsed.normalize() == pd.Timestamp("2025-03-01")


def test_multi_year_workbooks_keep_every_sheet(tmp_path: Path):
    path = tmp_path / "ledger.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        _ledger_rows(2024).to_excel(writer, sheet_name="Year 2024", index=False)
        _ledger_rows(2025).to_excel(writer, sheet_name="Year 2025", index=False)
        pd.DataFrame({"Field": ["Invoice"], "Meaning": ["Order"]}).to_excel(
            writer, sheet_name="Notes", index=False
        )
    assert len(load_source(path)) == 4
    assert len(read_excel_transactions(path)) == 4
    assert len(read_table(path)) == 4


def test_forecast_treats_an_empty_month_as_zero(tmp_path: Path):
    rows = [
        {
            "invoice_no": f"{month}",
            "stock_code": "S",
            "description": "Item",
            "quantity": 1,
            "invoice_date": f"2025-{month:02d}-28",
            "unit_price": 100.0,
            "country": "China",
        }
        for month in (1, 2, 3, 4, 6, 7, 8, 9)
    ]
    db = tmp_path / "gap.db"
    build_warehouse(clean_transactions(pd.DataFrame(rows), transaction_status="Verified"), db)
    result = forecast_metric(db, "orders", horizon=1)
    months = result.history.set_index("month")["orders"]
    assert months["2025-05"] == 0
    assert len(months) == 9


def test_a_spike_stands_out_against_the_months_before(tmp_path: Path):
    rows = [
        {
            "invoice_no": f"{index}",
            "stock_code": "S",
            "description": "Item",
            "quantity": 1,
            "invoice_date": f"{date}-15",
            "unit_price": 1000.0 if date == "2025-09" else 100.0 + index,
            "country": "China",
        }
        for index, date in enumerate(pd.period_range("2024-11", "2025-11", freq="M").astype(str))
    ]
    db = tmp_path / "spike.db"
    build_warehouse(clean_transactions(pd.DataFrame(rows), transaction_status="Verified"), db)
    anomalies = monthly_anomalies(db)
    assert "2025-09" in set(anomalies["month"])


def test_large_experiments_stay_in_memory_bounds():
    rng = np.random.default_rng(1)
    size = MAX_BOOTSTRAP_ROWS + 1
    control = rng.normal(10, 2, size)
    treatment = rng.normal(10.2, 2, size)
    low, high, probability = _bootstrap_difference(control, treatment)
    assert low < 0.2 < high
    assert high - low < 0.1
    assert probability > 0.99


def test_category_baskets_name_categories(demo_warehouse):
    rules = association_rules(demo_warehouse, FilterSpec(), level="category", min_pair_orders=8)
    assert not rules.empty
    assert (rules["antecedent_name"] == rules["antecedent"]).all()
    product = association_rules(demo_warehouse, FilterSpec(), min_pair_orders=8)
    assert (product["antecedent_name"] != product["antecedent"]).any()


def test_report_escapes_text_that_came_from_data(demo_warehouse, last_quarter):
    kpi = kpi_summary(demo_warehouse, last_quarter)
    issues, drivers = generate_diagnostics(demo_warehouse, last_quarter)
    issues[0].title = "<script>alert('x')</script>"
    html = render_html_report("2025 Q4", kpi, issues, drivers, pd.DataFrame())
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
    assert "<table" in html
