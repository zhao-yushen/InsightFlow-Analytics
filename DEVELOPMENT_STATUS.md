# InsightFlow Pro v0.4.3.3 Development Status

## Release-candidate hardening completed

- Multi-sheet Excel loader selects `transactions` or the first sheet satisfying the canonical contract.
- Duplicate canonical aliases are rejected with a readable error.
- P0/P1 contract issues block Data Hub import, CLI incremental load, and watched-folder ingestion.
- P2 unregistered categories remain warnings and can be imported.
- Rejected watcher files move to `data/rejected` with a JSON error record.
- SQLite writable and read-only connections close deterministically.
- Local CLI binds to `127.0.0.1` by default; Docker explicitly binds to `0.0.0.0`.
- Docker uses `/app` as the application root and an absolute warehouse path.
- XLS support declares the required `xlrd` dependency.

## Validation

- Automated tests: 33 passed.
- Core backend coverage: 83.8%.
- Python compilation: passed.
- Built-in warehouse reconciliations: passed.
- HTML and Word report generation: passed.
- Watched clean file: archived and inserted.
- Watched P1-invalid file: rejected with error record.

## Remaining external smoke test

The build environment does not include Streamlit, so the final browser smoke test must be run on Windows after installation. The code paths that previously failed at runtime are covered by regression tests.
