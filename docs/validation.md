# Validation Record: 2.0.0

Recorded on 2 November 2026 on Windows 11, on branch `feat/platform-v2`.

## Automated checks

| Check | Result |
|---|---|
| Tests on Python 3.13.5 | 150 passed |
| Tests on Python 3.11.16 | 150 passed |
| Coverage, whole package including pages | 92.94% |
| Ruff | Passed |
| Bandit, high severity | Passed |
| pip-audit | Passed |
| Wheel contains assets and pages | Confirmed |

Tests render all 17 pages headlessly on a two-year warehouse, and also cover these click paths: importing a GBK file, saving actions, running the fault drill, importing an experiment and asking the assistant.

## Demo warehouse

| Item | Value |
|---|---|
| Fact rows | 135,071 |
| Markets, regions, categories, channels | 30, 8, 12, 6 |
| Overall quality score | 97.9 |
| Lines failing the unit-price rule, kept for the demo | 45 |
| Last 90 days: net revenue | £1.60M |
| Last 90 days: contribution profit and margin | £493.9K, 30.8% |
| Profit bridge, unexplained amount | £0.00 |
| Rebuild from scratch | About 15 seconds |
| Overview analytics, cold cache | About 1.4 seconds |

## Defects measured in 1.0 and now covered by regression tests

| Defect | 1.0 behaviour | 2.0 behaviour |
|---|---|---|
| Appending 5 clean rows to a simulated warehouse | All 10 metrics became Verified 0.95; quality rows fell from 107,950 to 5 | Metrics read Mixed with confidence under 0.6; quality rows accumulate |
| Discount of 90% or negative cost | Silently clipped, contract passed | Two P1 issues block the import |
| No discount field in the source | Estimated discount, net revenue labelled Verified | Net revenue labelled Estimated |
| Returns | Excluded from net revenue and profit | Signed ledger nets them out at every grain |
| Order number starting with `C` | Counted as a return | Only negative quantity is a return |
| Changing the date filter | Stale actions stayed listed | One identity per issue; stale alerts leave the default view |
| Region filter on elasticity | Ignored | Applied |
| Concentration alert under filters | Used the global figure | Uses the filtered scope, and stays silent with few products |
| Small negative A/B estimate | Called profit damage | Inconclusive |
| Unrelated assistant question | Answered with profit drivers | Declined, with a list of supported questions |
| Currency | Hard-coded as pounds | Reporting currency, explicit rates, refusal of unconverted amounts |

## Checked in a real browser

- All 17 pages opened with no uncaught script errors. The console only shows the 404s Streamlit produces when probing its health path on a directly opened sub-page.
- The money river, gauges and simulation drop animate, and render correctly at 1440 × 900.
- Hovering and clicking a globe market opens that market's detail.
- Decision Lab simulation and plan search work.
- The assistant answers a supported question and declines an unrelated one.
- Switching to English gives an English overview with no Chinese text in the narrative.
- At phone width, the sidebar collapses and charts and gauges reflow.

## Not verified

- **Docker image:** the build could not run because the Docker daemon was off. The Dockerfile and `.dockerignore` were reviewed but not executed.
- **Real datasets:** no UCI or Olist file was available, so those adapters are tested only on small fixtures.
- **Real-world model accuracy:** the churn AUC and elasticity results come from a simulated ledger.
- **File upload in a real browser:** the upload flow is tested headlessly with a stubbed uploader.
- **Reduced motion and keyboard use:** implemented, but not tested with assistive settings.
- **Other languages:** Japanese, Korean, Spanish, French, German and Portuguese translate navigation only, and analysis text falls back to English.
