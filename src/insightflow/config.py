from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # The core backend can still run without optional .env loading.
    load_dotenv = None


def _discover_root() -> Path:
    explicit = os.getenv("INSIGHTFLOW_ROOT_DIR")
    candidates = [Path(explicit).expanduser()] if explicit else []
    candidates.extend([Path.cwd(), Path(__file__).resolve().parents[2]])
    for candidate in candidates:
        resolved = candidate.resolve()
        if (resolved / "streamlit_app.py").exists() or (resolved / "pyproject.toml").exists():
            return resolved
    return Path.cwd().resolve()


ROOT_DIR = _discover_root()
if load_dotenv is not None:
    load_dotenv(ROOT_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable with explicit, predictable semantics."""
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"环境变量 {name} 必须是 true/false，当前值为 {raw!r}")


DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
WAREHOUSE_DIR = DATA_DIR / "warehouse"
REPORTS_DIR = ROOT_DIR / "reports"
CONTRACTS_DIR = ROOT_DIR / "contracts"
POWERBI_DIR = ROOT_DIR / "powerbi"
INCOMING_DIR = DATA_DIR / "incoming"
PROCESSING_DIR = DATA_DIR / "processing"
ARCHIVE_DIR = DATA_DIR / "archive"
REJECTED_DIR = DATA_DIR / "rejected"
DEFAULT_DB_PATH = ROOT_DIR / os.getenv("INSIGHTFLOW_DB_PATH", "data/warehouse/insightflow.db")
DEFAULT_RAW_PATH = RAW_DIR / "demo_transactions.csv"
DEFAULT_CURATED_PATH = PROCESSED_DIR / "transactions_curated.csv"
DEFAULT_CONTRACT_PATH = CONTRACTS_DIR / "retail_transactions.json"
DEFAULT_MULTITABLE_DIR = RAW_DIR / "multitable_demo"
DEFAULT_MULTITABLE_DB_PATH = WAREHOUSE_DIR / "insightflow_multitable.db"
READ_ONLY = env_bool("INSIGHTFLOW_READ_ONLY", default=False)
APP_ENV = os.getenv("INSIGHTFLOW_APP_ENV", "local").strip().lower()
CACHE_TTL_SECONDS = int(os.getenv("INSIGHTFLOW_CACHE_TTL_SECONDS", "300"))
SERVER_ADDRESS = os.getenv("INSIGHTFLOW_SERVER_ADDRESS", "127.0.0.1").strip() or "127.0.0.1"
SERVER_PORT = int(os.getenv("INSIGHTFLOW_SERVER_PORT", "8501"))


def is_read_only() -> bool:
    """Return the current application write policy.

    The value is read dynamically so tests and process launchers can override the
    environment without re-importing the whole package.
    """
    return env_bool("INSIGHTFLOW_READ_ONLY", default=READ_ONLY)


def ensure_directories(*, allow_write: bool = True) -> None:
    if not allow_write:
        return
    for path in (
        RAW_DIR,
        PROCESSED_DIR,
        WAREHOUSE_DIR,
        REPORTS_DIR,
        CONTRACTS_DIR,
        POWERBI_DIR,
        INCOMING_DIR,
        PROCESSING_DIR,
        ARCHIVE_DIR,
        REJECTED_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
