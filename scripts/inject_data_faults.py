from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from insightflow.etl import load_source
from insightflow.fault_injection import FaultPlan, inject_faults


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a deliberately corrupted dataset for data-quality demos")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--no-remove-month", action="store_true")
    args = parser.parse_args()
    source = load_source(args.input)
    corrupted = inject_faults(source, FaultPlan(remove_month=not args.no_remove_month))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    corrupted.to_csv(output, index=False)
    print(f"Wrote {len(corrupted):,} rows to {output}")


if __name__ == "__main__":
    main()
