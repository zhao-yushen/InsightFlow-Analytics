from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

import insightflow.watcher as watcher
from insightflow.etl import clean_transactions, load_source, read_excel_transactions
from insightflow.warehouse import connect, query_df


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


def _watch_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    incoming = tmp_path / "incoming"
    processing = tmp_path / "processing"
    archive = tmp_path / "archive"
    rejected = tmp_path / "rejected"
    for directory in (incoming, processing, archive, rejected):
        directory.mkdir()
    monkeypatch.setattr(watcher, "PROCESSING_DIR", processing)
    monkeypatch.setattr(watcher, "ARCHIVE_DIR", archive)
    monkeypatch.setattr(watcher, "REJECTED_DIR", rejected)
    return incoming, archive, rejected


def test_watcher_rejects_a_file_that_is_mostly_bad(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    incoming, archive, rejected = _watch_folders(tmp_path, monkeypatch)
    bad = _valid_rows()
    bad.loc[0, "unit_price"] = 0
    source = incoming / "bad.csv"
    bad.to_csv(source, index=False)
    with pytest.raises(ValueError, match="不符合契约"):
        watcher.process_incoming_file(source, tmp_path / "warehouse.db")
    assert not list(archive.glob("*"))
    assert list(rejected.glob("*_bad.csv"))
    assert list(rejected.glob("*.error.json"))


def test_watcher_sets_a_few_bad_rows_aside_and_keeps_the_feed_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    incoming, archive, _ = _watch_folders(tmp_path, monkeypatch)
    rows = pd.concat(
        [_valid_rows().assign(invoice_no=f"INV-{index}") for index in range(5)], ignore_index=True
    )
    rows.loc[0, "unit_price"] = 0
    source = incoming / "mixed.csv"
    rows.to_csv(source, index=False)
    result = watcher.process_incoming_file(source, tmp_path / "warehouse.db")
    assert result["status"] == "archived"
    assert list(archive.glob("*_mixed.csv"))
    kept = query_df(tmp_path / "warehouse.db", "SELECT COUNT(*) FROM v_ledger").iloc[0, 0]
    set_aside = query_df(
        tmp_path / "warehouse.db",
        "SELECT reject_reason FROM fact_transactions WHERE data_valid = 0",
    )
    assert kept == 4
    assert set_aside["reject_reason"].tolist() == ["unit_price/min_exclusive"]


def test_strict_mode_refuses_any_contract_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    incoming, _, _ = _watch_folders(tmp_path, monkeypatch)
    monkeypatch.setenv("INSIGHTFLOW_STRICT_IMPORT", "true")
    rows = pd.concat(
        [_valid_rows().assign(invoice_no=f"INV-{index}") for index in range(5)], ignore_index=True
    )
    rows.loc[0, "unit_price"] = 0
    source = incoming / "strict.csv"
    rows.to_csv(source, index=False)
    with pytest.raises(ValueError, match="数据契约阻止导入"):
        watcher.process_incoming_file(source, tmp_path / "warehouse.db")


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
