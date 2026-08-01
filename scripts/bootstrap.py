import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from insightflow.config import (
    DEFAULT_CURATED_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_RAW_PATH,
    ensure_directories,
)
from insightflow.demo_data import write_demo_csv
from insightflow.etl import clean_transactions, load_source
from insightflow.warehouse import build_warehouse


def main() -> None:
    ensure_directories()
    print("[1/5] Generating reproducible demo transactions with cost and inventory fields...")
    write_demo_csv(DEFAULT_RAW_PATH)
    print(f"      {DEFAULT_RAW_PATH}")

    print("[2/5] Cleaning, auditing and deriving unit economics...")
    result = clean_transactions(
        load_source(DEFAULT_RAW_PATH),
        source_profile="demo_generated",
        transaction_status="Simulated",
    )
    result.curated.to_csv(DEFAULT_CURATED_PATH, index=False)
    print(result.quality_summary.to_string(index=False))
    print(result.quality_dimensions.to_string(index=False))

    print("[3/5] Building SQLite warehouse, governance tables and inventory snapshot...")
    stats = build_warehouse(
        result, DEFAULT_DB_PATH, load_mode="replace", source_name="demo_generator"
    )
    print(f"      {DEFAULT_DB_PATH}")
    print(f"      inserted={stats['inserted_rows']:,}, skipped={stats['skipped_rows']:,}")

    print("[4/5] Metric catalog, business targets and data lineage created.")
    print("[5/5] Bootstrap completed.")
    print("Run: streamlit run streamlit_app.py")


if __name__ == "__main__":
    main()
