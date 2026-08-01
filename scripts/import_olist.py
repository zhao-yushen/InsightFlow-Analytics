from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from insightflow.config import DEFAULT_DB_PATH, ensure_directories
from insightflow.etl import clean_transactions
from insightflow.multitable import load_olist_directory
from insightflow.warehouse import build_warehouse


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the public Olist multi-table dataset")
    parser.add_argument("--directory", required=True, help="Directory containing Olist CSV tables")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Target SQLite database")
    args = parser.parse_args()
    ensure_directories()
    canonical = load_olist_directory(args.directory)
    result = clean_transactions(canonical, source_profile="olist_public", transaction_status="Verified")
    stats = build_warehouse(result, Path(args.db), source_name="olist_public")
    print(result.quality_summary.to_string(index=False))
    print(f"Inserted {stats['inserted_rows']:,} canonical rows into {args.db}")


if __name__ == "__main__":
    main()
