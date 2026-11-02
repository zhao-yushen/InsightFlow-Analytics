from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

# The default warehouse path is read once at import, so it must be set before any
# insightflow module loads. Tests can then never touch a real warehouse.
_DEFAULT_DB = Path(tempfile.mkdtemp(prefix="insightflow-tests-")) / "default.db"
os.environ["INSIGHTFLOW_DB_PATH"] = str(_DEFAULT_DB)

from insightflow.demo_data import DemoConfig, generate_demo_transactions  # noqa: E402
from insightflow.etl import clean_transactions  # noqa: E402
from insightflow.metrics import FilterSpec  # noqa: E402
from insightflow.warehouse import build_warehouse  # noqa: E402

DEMO = DemoConfig(
    start="2024-01-01",
    end="2025-12-31",
    base_daily_orders=14,
    min_daily_orders=6,
    n_customers=500,
    n_products=60,
)


@pytest.fixture(scope="session")
def demo_warehouse(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A two-year simulated warehouse shared by read-only tests."""
    db = tmp_path_factory.mktemp("warehouse") / "demo.db"
    result = clean_transactions(
        generate_demo_transactions(DEMO), source_profile="demo_generated"
    )
    build_warehouse(result, db, source_name="demo")
    return db


@pytest.fixture(scope="session")
def page_warehouse(demo_warehouse: Path) -> Path:
    """Copy the demo into the path pages read by default."""
    shutil.copy(demo_warehouse, _DEFAULT_DB)
    return _DEFAULT_DB


@pytest.fixture(scope="session")
def last_quarter() -> FilterSpec:
    return FilterSpec("2025-10-03", "2025-12-31")
