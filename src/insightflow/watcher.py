from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import (
    ARCHIVE_DIR,
    DEFAULT_DB_PATH,
    INCOMING_DIR,
    PROCESSING_DIR,
    REJECTED_DIR,
    ensure_directories,
)
from .data_contracts import contract_block_message
from .etl import clean_transactions, load_source
from .warehouse import build_warehouse

SUPPORTED_SUFFIXES = {".csv", ".xlsx", ".xls", ".parquet"}


def process_incoming_file(source: Path, db_path: Path = DEFAULT_DB_PATH) -> dict[str, object]:
    ensure_directories()
    source = Path(source)
    if source.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported file type: {source.suffix}")
    processing = PROCESSING_DIR / source.name
    if source.resolve() != processing.resolve():
        shutil.move(str(source), processing)
    started = datetime.now(timezone.utc)
    try:
        result = clean_transactions(
            load_source(processing),
            source_profile="watched_incremental_import",
            transaction_status="Verified",
        )
        block_message = contract_block_message(result.contract_issues)
        if block_message:
            raise ValueError(block_message)
        stats = build_warehouse(
            result,
            db_path,
            load_mode="append",
            source_name=processing.name,
        )
        stamp = started.strftime("%Y%m%dT%H%M%SZ")
        target = ARCHIVE_DIR / f"{stamp}_{processing.name}"
        shutil.move(str(processing), target)
        return {
            "status": "archived",
            "source": source.name,
            "archive": str(target),
            **stats,
        }
    except Exception as exc:
        stamp = started.strftime("%Y%m%dT%H%M%SZ")
        target = REJECTED_DIR / f"{stamp}_{processing.name}"
        if processing.exists():
            shutil.move(str(processing), target)
        error_path = target.with_suffix(target.suffix + ".error.json")
        error_path.write_text(
            json.dumps(
                {
                    "source": source.name,
                    "error": str(exc),
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        raise


def scan_once(db_path: Path = DEFAULT_DB_PATH) -> list[dict[str, object]]:
    ensure_directories()
    results: list[dict[str, object]] = []
    for source in sorted(INCOMING_DIR.iterdir()):
        if not source.is_file() or source.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        try:
            results.append(process_incoming_file(source, db_path))
        except Exception as exc:
            results.append({"status": "rejected", "source": source.name, "error": str(exc)})
    return results


def watch(db_path: Path = DEFAULT_DB_PATH, interval: int = 30, once: bool = False) -> None:
    ensure_directories()
    interval = max(5, int(interval))
    print(f"Watching {INCOMING_DIR} every {interval}s. Press Ctrl+C to stop.")
    while True:
        for result in scan_once(db_path):
            print(json.dumps(result, ensure_ascii=False))
        if once:
            return
        time.sleep(interval)
