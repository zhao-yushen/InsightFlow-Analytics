from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from insightflow.config import DEFAULT_DB_PATH
from insightflow.data_contracts import contract_block_message
from insightflow.etl import clean_transactions, load_source
from insightflow.warehouse import build_warehouse


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Incrementally load transaction data into InsightFlow"
    )
    parser.add_argument("--input", required=True, help="CSV/XLSX/Parquet file")
    args = parser.parse_args()
    source = Path(args.input)
    result = clean_transactions(
        load_source(source),
        source_profile="incremental_import",
        transaction_status="Verified",
    )
    block_message = contract_block_message(result.contract_issues)
    if block_message:
        raise SystemExit(block_message)
    stats = build_warehouse(result, DEFAULT_DB_PATH, load_mode="append", source_name=source.name)
    print(f"Inserted rows: {stats['inserted_rows']:,}")
    print(f"Skipped duplicates: {stats['skipped_rows']:,}")


if __name__ == "__main__":
    main()
