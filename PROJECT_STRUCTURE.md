# Project Structure

```text
InsightFlow/
├─ .github/workflows/       # CI
├─ .streamlit/              # Theme and server configuration
├─ contracts/               # Data contract
├─ data/                    # Runtime data (kept empty in git)
├─ docs/                    # Architecture, methods, metrics, release notes
├─ powerbi/                 # Power BI model and DAX measures
├─ reports/                 # Generated reports
├─ scripts/                 # Bootstrap, import, export and benchmark scripts
├─ src/insightflow/         # Application package
│  ├─ assets/               # Logo and globe land dots
│  └─ pages/                # One module per page
├─ static/fonts/            # Self-hosted Sora typeface
├─ tests/                   # Automated tests
├─ Dockerfile
├─ docker-compose.yml
├─ LICENSE
├─ pyproject.toml
├─ README.md
├─ run_windows.bat
└─ streamlit_app.py
```
