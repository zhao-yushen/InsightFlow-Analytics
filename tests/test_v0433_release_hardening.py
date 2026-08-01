from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from insightflow.etl import clean_transactions, load_source, read_excel_transactions
from insightflow.warehouse import connect
import insightflow.watcher as watcher


def _valid_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "invoice_no": "INV-1",
                "stock_code": "SKU-1",
                "description": "TEST PRODUCT",
                "category": "Electronics",
                "quantity": 2,
                "invoice_date": "2025-01-02 10:00:00",
                "unit_price": 20.0,
                "customer_id": "C-1",
                "country": "China",
                "channel": "Web",
            }
        ]
    )


def test_multisheet_excel_selects_transaction_sheet(tmp_path: Path) -> None:
    path = tmp_path / "input.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        _valid_rows().to_excel(writer, sheet_name="transactions", index=False)
        pd.DataFrame({"Field": ["invoice_no"], "Description": ["Order number"]}).to_excel(
            writer, sheet_name="field_dictionary", index=False
        )
    loaded = load_source(path)
    assert len(loaded) == 1
    assert set(_valid_rows().columns).issubset(loaded.columns)
    result = clean_transactions(loaded, source_profile="test_excel", transaction_status="Verified")
    assert result.metadata["valid_sales_rows"] == 1


def test_excel_without_transaction_sheet_raises_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame({"Field": ["invoice_no"], "Description": ["Order number"]}).to_excel(
            writer, sheet_name="dictionary", index=False
        )
    with pytest.raises(ValueError, match="未找到可识别的交易工作表"):
        read_excel_transactions(path)


def test_watcher_rejects_p1_contract_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    incoming = tmp_path / "incoming"
    processing = tmp_path / "processing"
    archive = tmp_path / "archive"
    rejected = tmp_path / "rejected"
    for directory in (incoming, processing, archive, rejected):
        directory.mkdir()
    monkeypatch.setattr(watcher, "PROCESSING_DIR", processing)
    monkeypatch.setattr(watcher, "ARCHIVE_DIR", archive)
    monkeypatch.setattr(watcher, "REJECTED_DIR", rejected)

    bad = _valid_rows()
    bad.loc[0, "unit_price"] = 0
    source = incoming / "bad.csv"
    bad.to_csv(source, index=False)
    with pytest.raises(ValueError, match="数据契约阻止导入"):
        watcher.process_incoming_file(source, tmp_path / "warehouse.db")
    assert not list(archive.glob("*"))
    assert list(rejected.glob("*_bad.csv"))
    assert list(rejected.glob("*.error.json"))


def test_watcher_archives_valid_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    incoming = tmp_path / "incoming"
    processing = tmp_path / "processing"
    archive = tmp_path / "archive"
    rejected = tmp_path / "rejected"
    for directory in (incoming, processing, archive, rejected):
        directory.mkdir()
    monkeypatch.setattr(watcher, "PROCESSING_DIR", processing)
    monkeypatch.setattr(watcher, "ARCHIVE_DIR", archive)
    monkeypatch.setattr(watcher, "REJECTED_DIR", rejected)

    source = incoming / "clean.csv"
    _valid_rows().to_csv(source, index=False)
    result = watcher.process_incoming_file(source, tmp_path / "warehouse.db")
    assert result["status"] == "archived"
    assert result["inserted_rows"] == 1
    assert list(archive.glob("*_clean.csv"))
    assert not list(rejected.glob("*.error.json"))


def test_connect_context_closes_connection(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    with connect(db) as conn:
        conn.execute("CREATE TABLE sample(value INTEGER)")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")
