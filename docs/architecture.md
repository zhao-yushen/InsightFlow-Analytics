# Architecture

```text
Sources         CSV, TSV, Excel, Parquet, JSON, seven-table demo, UCI, Olist
   |
Ingest          ingest.py: decoding, tolerant parsing, field mapping, derivations
   |
Contract        data_contracts.py: checks the raw values, blocks P0 and P1
   |
ETL             etl.py: rule-based filling, line provenance, signed line economics
   |
Warehouse       warehouse.py: SQLite fact and dimensions, v_ledger, v_sales, governance
   |
Analytics       metrics, pvm, diagnostics, forecasting, elasticity, churn, supply, basket
   |
Decisions       decision_lab, optimizer, experiments, action_center
   |
Delivery        pages (Streamlit), narrative, reporting, query_assistant, Power BI package
```

## Key ideas

**One signed ledger.** `v_ledger` holds every valid line, with reversals negative. Money metrics read it, so results after returns are automatic at any grain. `v_sales` holds positive sales only, for order counts and demand.

**Trust is computed from rows.** Provenance is stored per line. `metric_catalog` and `data_profiles` are rebuilt from the whole warehouse after every load, and never copied from the latest batch.

**Display logic stays out of the analytics.** Analysis modules return data frames and numbers. `narrative.py` turns them into sentences and payloads, `viz.py` into charts, and `live.py` into animated instruments.

## Interface modules

| Module | Role |
|---|---|
| `design.py` | Colour tokens, Plotly template, global CSS |
| `viz.py` | Chart builders that share one rulebook |
| `live.py` | Money river, gauges, simulation drop and globe, hand-built on canvas and SVG |
| `narrative.py` | Page ledes and component payloads |
| `ui.py` | Page furniture, filters, trust sentences |

Colour is semantic. Aqua is money in play, gold is profit kept, coral is money leaving. Series colours identify entities and were validated for colour-blind separation on both dark surfaces.

The animated components use no external libraries, so the app works offline. They pause off screen and honour the reduced-motion setting. Every animated chart has a table view.

## Controls

- Joins in the multi-table adapters validate many-to-one cardinality.
- Filter values reach SQL only as bound parameters, and dimension names come from allowlists.
- Fault injection runs in memory and cannot touch the warehouse.
- Read-only mode blocks action writes, imports, drills and server-side report files.
- The LLM summary is optional and never calculates a metric.
- The warehouse records its schema version. Demo warehouses rebuild themselves after a definition change, and real ones ask for a re-import.
