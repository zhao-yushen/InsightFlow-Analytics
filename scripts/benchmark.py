from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from insightflow.config import DEFAULT_DB_PATH
from insightflow.metrics import (
    FilterSpec,
    date_bounds,
    kpi_summary,
    monthly_trend,
    product_profitability,
)
from insightflow.warehouse import query_df


def timed(label: str, fn):
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    return label, elapsed, result


def main() -> None:
    min_date, max_date = date_bounds(DEFAULT_DB_PATH)
    filters = FilterSpec(min_date, max_date)
    checks = [
        timed("kpi_summary", lambda: kpi_summary(DEFAULT_DB_PATH, filters)),
        timed("monthly_trend", lambda: monthly_trend(DEFAULT_DB_PATH, filters)),
        timed(
            "product_profitability",
            lambda: product_profitability(DEFAULT_DB_PATH, filters, limit=100),
        ),
        timed(
            "contract_issues",
            lambda: query_df(DEFAULT_DB_PATH, "SELECT * FROM data_contract_issues"),
        ),
    ]
    rows = int(query_df(DEFAULT_DB_PATH, "SELECT COUNT(*) n FROM fact_transactions").iloc[0, 0])
    output = {
        "database": str(DEFAULT_DB_PATH),
        "fact_rows": rows,
        "benchmarks": [
            {
                "operation": label,
                "seconds": round(elapsed, 4),
                "result_rows": len(result) if hasattr(result, "__len__") else None,
            }
            for label, elapsed, result in checks
        ],
    }
    path = ROOT / "reports" / "performance_benchmark.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
