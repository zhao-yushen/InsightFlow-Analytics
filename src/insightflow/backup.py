"""Point-in-time copies of the warehouse, taken before anything can overwrite it.

An import can replace every row, so the app keeps the last few warehouses beside the live
one. A restore first backs up what it is about to replace, which makes it undoable too.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .warehouse import clear_query_cache

KEEP_BACKUPS = 3
_NAME = re.compile(r"^insightflow-\d{8}T\d{12}Z\.db$")


def _directory(db_path: str | Path) -> Path:
    return Path(db_path).parent / "backups"


def _copy(source: Path, target: Path) -> None:
    """Copy through SQLite's backup API, which stays consistent in WAL mode."""
    with closing(sqlite3.connect(source)) as origin, closing(sqlite3.connect(target)) as copy:
        origin.backup(copy)


def list_backups(db_path: str | Path) -> list[Path]:
    """Return backups of this warehouse, newest first."""
    directory = _directory(db_path)
    if not directory.exists():
        return []
    found = [path for path in directory.iterdir() if _NAME.match(path.name)]
    return sorted(found, key=lambda path: path.name, reverse=True)


def create_backup(db_path: str | Path, *, keep: int = KEEP_BACKUPS) -> Path | None:
    """Copy the warehouse aside and drop the oldest copies beyond `keep`."""
    source = Path(db_path)
    if not source.exists():
        return None
    directory = _directory(source)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = directory / f"insightflow-{stamp}.db"
    _copy(source, target)
    for stale in list_backups(source)[keep:]:
        stale.unlink()
    return target


def restore_backup(name: str, db_path: str | Path) -> None:
    """Put a listed backup back in place. Only names from list_backups are accepted."""
    chosen = next((path for path in list_backups(db_path) if path.name == name), None)
    if chosen is None:
        raise ValueError(f"找不到备份: {name}")
    # One extra slot, so saving the current state cannot rotate out the file being restored.
    create_backup(db_path, keep=KEEP_BACKUPS + 1)
    _copy(chosen, Path(db_path))
    clear_query_cache()
