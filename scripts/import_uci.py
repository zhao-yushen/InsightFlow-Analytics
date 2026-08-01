from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from insightflow.config import DEFAULT_CURATED_PATH, DEFAULT_DB_PATH, ensure_directories
from insightflow.etl import clean_transactions, load_source
from insightflow.warehouse import build_warehouse


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import UCI Online Retail/Online Retail II Excel or CSV"
    )
    parser.add_argument(
        "--input", required=True, help="Path to online_retail_II.xlsx or compatible CSV"
    )
    args = parser.parse_args()
    ensure_directories()
    source = Path(args.input)
    if not source.exists():
        raise FileNotFoundError(source)
    print(f"Reading {source} ...")
    df = load_source(source)
    print(f"Rows loaded: {len(df):,}")
    result = clean_transactions(
        df, source_profile="uci_online_retail", transaction_status="Verified"
    )
    result.curated.to_csv(DEFAULT_CURATED_PATH, index=False)
    build_warehouse(result, DEFAULT_DB_PATH)
    print(result.quality_summary.to_string(index=False))
    print(f"Warehouse updated: {DEFAULT_DB_PATH}")


if __name__ == "__main__":
    main()
