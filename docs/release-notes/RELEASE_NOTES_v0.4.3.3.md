# InsightFlow Pro v0.4.3.3

This release candidate is the final pre-v1.0 validation and ingestion-hardening patch.

## Fixed

- Multi-sheet Excel files are no longer concatenated. InsightFlow selects a sheet named `transactions`, or the first sheet containing all required transaction fields.
- Duplicate fields created by alias mapping now raise a clear validation error instead of failing later with an attribute error.
- P0/P1 contract issues now block import in Data Hub, `incremental_load.py`, and the watched-folder pipeline.
- Watched files with blocking issues move to `data/rejected` and receive a sidecar `.error.json` file.
- P2 unknown-category/channel issues remain non-blocking warnings.
- SQLite connections are deterministically closed, removing resource-leak warnings.
- `insightflow run` binds to `127.0.0.1` by default for safer local use.
- Docker now uses `/app` as an explicit root, an absolute database path, and `0.0.0.0` only inside the container.
- Added `xlrd` for legacy `.xls` support.

## Validation

- 33 automated tests passed.
- Core backend coverage: 83.8%.
- Multi-sheet clean Excel: 5,000/5,000 rows recognized as valid sales.
- Invalid watched CSV: rejected; no rows inserted.
- Financial and dimensional reconciliation checks passed.
