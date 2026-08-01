from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pandas as pd

from insightflow.config import DEFAULT_DB_PATH

EXPORT_OBJECTS = [
    "fact_transactions",
    "dim_customer",
    "dim_product",
    "dim_country",
    "dim_date",
    "v_monthly_kpis",
    "inventory_snapshot",
    "business_targets",
    "metric_catalog",
    "data_profiles",
    "data_contract_issues",
    "experiment_catalog",
    "experiment_assignments",
]


def main() -> None:
    output = ROOT / "exports" / "powerbi"
    output.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DEFAULT_DB_PATH) as conn:
        for name in EXPORT_OBJECTS:
            df = pd.read_sql_query(f'SELECT * FROM "{name}"', conn)
            path = output / f"{name}.csv"
            df.to_csv(path, index=False)
            print(f"{name}: {len(df):,} rows -> {path}")


if __name__ == "__main__":
    main()
