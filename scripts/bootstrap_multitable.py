from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from insightflow.config import DEFAULT_MULTITABLE_DB_PATH, DEFAULT_MULTITABLE_DIR, ensure_directories
from insightflow.etl import clean_transactions
from insightflow.multitable import generate_multitable_demo, load_multitable_directory
from insightflow.warehouse import build_warehouse


def main() -> None:
    ensure_directories()
    paths = generate_multitable_demo(DEFAULT_MULTITABLE_DIR)
    print(f"Generated {len(paths)} source tables in {DEFAULT_MULTITABLE_DIR}")
    canonical = load_multitable_directory(DEFAULT_MULTITABLE_DIR)
    result = clean_transactions(
        canonical,
        source_profile="multitable_demo",
        transaction_status="Simulated",
    )
    stats = build_warehouse(result, DEFAULT_MULTITABLE_DB_PATH, source_name="multitable_demo")
    print(f"Warehouse: {DEFAULT_MULTITABLE_DB_PATH}")
    print(f"Inserted: {stats['inserted_rows']:,}")


if __name__ == "__main__":
    main()
