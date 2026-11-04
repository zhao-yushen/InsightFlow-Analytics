# Validation Record: 2.0.0

Recorded on 3 November 2026 on Windows 11, on branch `feat/platform-v2`.

## Automated checks

| Check | Result |
|---|---|
| Tests on Python 3.13.5 | 249 passed |
| Tests on Python 3.11.16 | 249 passed |
| Coverage, whole package including pages | 93.35% |
| Ruff | Passed |
| Bandit, high severity | Passed |
| pip-audit | No known vulnerabilities |

A regression test for the disabled-button style was added after this record. On 4 November 2026, CI on `main` at commit `7a4800a` ran 250 tests on Python 3.11 and 3.13; all passed, with 93.30% coverage.

Tests render all 17 pages on the demo warehouse and on a bare ledger with no costs, stock or categories. They also cover these click paths: importing a GBK file, setting problem rows aside, refusing a mostly broken file, saving actions, running the fault drill, importing an experiment, asking the assistant, the access code, shared links and a half-picked date range.

## Real data: UCI Online Retail II

| Item | Value |
|---|---|
| Source | Two yearly sheets, 1,067,371 lines |
| Exact duplicates removed | 34,335 |
| Lines set aside as problems | 5,959 (0.58%), almost all zero prices |
| Non-merchandise lines set aside | 5,827, worth −£71.8K: postage, marketplace fees, bank charges, manual adjustments |
| Reconciliation | Net revenue £18.93M plus set-aside value −£71.2K equals the deduplicated file to £0.00 |
| Product families derived | 30, plus Other |
| Upload in a real browser | Read 44 s, checks 12 s, import 30 s |
| Same pipeline without the browser | Clean 17 s, warehouse 32 s, 534 MB on disk |
| Pages on the imported warehouse | All 17 open without errors. First visit up to 7.9 s (overview) and 4.8 s (pricing); repeat visits under 0.6 s |
| Revenue forecast, rolling backtest | Seasonal naive, WAPE 6.5%, 55% better than repeating last month |
| Orders forecast, rolling backtest | Seasonal drift, WAPE 3.9%, 76% better than repeating last month |
| Churn model, out of time | AUC 0.79; the top tenth of customers return at 2.1× the average |
| Price elasticity, revenue-weighted | −0.96; 29 of 31 families measured from data |

UCI has no costs, discounts or stock, so its profit figures rest on documented rules and the inventory page reads demand only. Customer analysis covers the 86% of revenue that carries a customer ID.

## Demo warehouse

| Item | Value |
|---|---|
| Fact rows | 135,071 |
| Markets, regions, categories, channels | 30, 8, 12, 6 |
| Overall quality score | 97.9 |
| Zero-price lines set aside, kept to demonstrate the audit | 45 |
| Last 90 days: net revenue | £1.60M |
| Last 90 days: contribution profit and margin | £493.9K, 30.8% |
| Profit bridge, unexplained amount | £0.00 |
| Elasticity against the known truth | Mean bias +0.46, correlation 0.89 |
| Rebuild from scratch | About 19 seconds |

## Defects found on the real ledger, now covered by regression tests

| Defect | Before | Now |
|---|---|---|
| No discount column | A 3% discount was invented, so net revenue fell £565.6K short of the file | The price is what was paid, and revenue reconciles |
| A few zero-price rows | P1 issues refused the whole file | Rows are set aside with consent and can be downloaded |
| Postage, fees and adjustments | Counted as sales, and Amazon fees as £221.5K of refunds | Set aside and listed with their value |
| No stock or suppliers in the source | Invented stock levels and supplier names raised reorder alerts | Left empty; demand analysis only |
| An order placed and cancelled the same day | 80,995 units read as 900 units of daily demand | Demand is net of returns |
| Warehouse notes on zero-price lines | A product named "WEBSITE FIXED" | Each product takes the name it most often sold under |
| Two price lists for one product | Elasticity −0.16 from mixing web and account prices | Each sales stream followed on its own: −0.96 |
| Unsold weeks priced at the stream's usual price | Demo estimates a point too steep (bias −0.94) | Weekly price index from the other streams (bias +0.46) |
| Weeks treated as independent | Standard errors three to five times too small | Clustered by product |
| First real upload | Appended to the simulated demo by default | Replaces the demo by default |
| Sample experiments after a replace | Simulated "ship" verdicts stayed beside real data | Removed on replace |
| Opening the action list | Wrote to the warehouse every time and emptied every cache | Writes only changes; repeat page visits under 0.6 s |
| Unfinished final month | Compared with a full month's target | Amount targets prorated by days elapsed |
| Country spellings | Ten markets, among them EIRE and RSA, off the map and in Other | 132 places with a region and a position |
| Product concentration | Counted within the top 400 products only | Counts every product |
| Half-picked date range | Page error | The single day is used until the range is complete |
| Discount cuts with no discount running | Searched as if possible | Left out of the plan search |

## Defects measured in 1.0, still covered

| Defect | 1.0 behaviour | 2.0 behaviour |
|---|---|---|
| Appending 5 clean rows to a simulated warehouse | All 10 metrics became Verified 0.95; quality rows fell from 107,950 to 5 | Metrics read Mixed with confidence under 0.6; quality rows accumulate |
| Discount of 90% or negative cost | Silently clipped, contract passed | Reported as P1, and those lines are set aside |
| Returns | Excluded from net revenue and profit | Signed ledger nets them out at every grain |
| Order number starting with `C` | Counted as a return | Only negative quantity is a return |
| Changing the date filter | Stale actions stayed listed | One identity per issue; stale alerts leave the default view |
| Region filter on elasticity | Ignored | Applied |
| Concentration alert under filters | Used the global figure | Uses the filtered scope, and stays silent with few products |
| Small negative A/B estimate | Called profit damage | Inconclusive |
| Unrelated assistant question | Answered with profit drivers | Declined, with a list of supported questions |
| Currency | Hard-coded as pounds | Reporting currency, explicit rates, refusal of unconverted amounts |

## Checked in a real browser

- The 45 MB UCI workbook was uploaded through the file input in headless Edge, the consent box was ticked with real mouse input, and the import completed.
- All 17 pages opened on the imported warehouse with no uncaught script errors.
- With reduced motion requested, the overview, markets and decision lab pages stay still between frames. Without it, the river and globe move.
- Keyboard: Tab reaches the river's outflows with a visible focus ring, and Enter opens the drill-down. The globe turns with the left and right arrows, the down arrow names the next market, and Enter opens it.
- At 390 px, the overview, pricing and data hub pages have no sideways scroll.
- The screenshots in `docs/assets` were retaken from the demo warehouse.

## Not verified

- **Docker image:** Docker Desktop started, but pulling `python:3.11-slim` from Docker Hub timed out at the TLS handshake on this network, so the image was not built.
- **Olist:** the dataset needs a Kaggle login, so its adapter is tested only on fixtures.
- **Price response on real data:** the UCI elasticities have no known truth to compare with. On the demo they lean toward zero, and their 95% intervals hold only a third of the true values.
- **Screen readers:** focus order, labels and keyboard paths were checked, not narration. Keyboard users pass about 30 sidebar controls before the first chart.
- **The browser walk's warehouse** was imported before two later fixes, sample-experiment removal and hiding outflows that never happened. Both are covered by tests.
- **Other languages:** Japanese, Korean, Spanish, French, German and Portuguese translate navigation only, and analysis text falls back to English.
