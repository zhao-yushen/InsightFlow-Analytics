from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from insightflow.config import DEFAULT_CONTRACT_PATH
from insightflow.data_contracts import contract_score, load_contract, validate_contract
from insightflow.etl import load_source, normalize_columns


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate a source file against the InsightFlow data contract"
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT_PATH))
    args = parser.parse_args()
    frame = normalize_columns(load_source(args.input))
    issues = validate_contract(frame, load_contract(args.contract))
    print(issues.to_string(index=False))
    print(f"Contract score: {contract_score(issues):.1f}/100")
    if issues["severity"].isin(["P0", "P1"]).any():
        raise SystemExit(2)


if __name__ == "__main__":
    main()
