from pathlib import Path

import pandas as pd

from insightflow.decision_lab import ScenarioInputs, UncertaintyInputs, monte_carlo_scenario
from insightflow.demo_data import DemoConfig, generate_demo_transactions
from insightflow.etl import clean_transactions
from insightflow.experiments import analyze_experiment, experiment_catalog
from insightflow.metrics import FilterSpec
from insightflow.multitable import generate_multitable_demo, load_multitable_directory
from insightflow.provenance import dataset_profile, metric_trust_table
from insightflow.warehouse import build_warehouse, query_df


def _small_db(tmp_path: Path) -> tuple[Path, FilterSpec]:
    db = tmp_path / "v04.db"
    frame = generate_demo_transactions(
        DemoConfig(
            start="2025-01-01",
            end="2025-12-31",
            base_daily_orders=3,
            min_daily_orders=2,
            n_customers=80,
            n_products=20,
        )
    )
    result = clean_transactions(frame, source_profile="demo_test", transaction_status="Simulated")
    build_warehouse(result, db, source_name="demo_test")
    return db, FilterSpec("2025-10-01", "2025-12-31")


def test_provenance_and_contract_tables(tmp_path: Path):
    db, _ = _small_db(tmp_path)
    profile = dataset_profile(db)
    assert profile["data_mode"] == "Simulated"
    trust = metric_trust_table(db)
    assert {"data_status", "confidence", "source_note"}.issubset(trust.columns)
    contract = query_df(db, "SELECT * FROM data_contract_issues")
    assert not contract.empty


def test_monte_carlo_outputs_probability_and_sensitivity(tmp_path: Path):
    db, filters = _small_db(tmp_path)
    summary, samples, sensitivity = monte_carlo_scenario(
        db,
        filters,
        ScenarioInputs(name="Test", price_change_pct=2, unit_cost_change_pct=-2),
        UncertaintyInputs(simulations=700, seed=7),
    )
    assert len(samples) == 700
    assert 0 <= float(summary.iloc[0]["probability_profit_improves"]) <= 1
    assert not sensitivity.empty


def test_experiment_profit_guardrail(tmp_path: Path):
    db, _ = _small_db(tmp_path)
    catalog = experiment_catalog(db)
    assert len(catalog) >= 2
    summary, metrics, _ = analyze_experiment(db, "EXP_BLANKET_DISCOUNT_01")
    assert "不建议推广" in summary.decision
    assert set(metrics["metric"]) >= {"converted", "net_revenue", "contribution_profit", "returned"}


def test_multitable_profile_round_trip(tmp_path: Path):
    directory = tmp_path / "tables"
    generate_multitable_demo(
        directory,
        DemoConfig(
            start="2025-01-01",
            end="2025-02-28",
            base_daily_orders=2,
            min_daily_orders=2,
            n_customers=40,
            n_products=12,
        ),
    )
    canonical = load_multitable_directory(directory)
    assert len(canonical) > 0
    assert {"invoice_no", "stock_code", "unit_cost", "shipping_cost"}.issubset(canonical.columns)
    assert canonical["invoice_no"].notna().all()


def test_olist_adapter_preserves_string_customer_ids(tmp_path: Path):
    directory = tmp_path / "olist"
    directory.mkdir()
    pd.DataFrame(
        [{
            "order_id": "order-1",
            "customer_id": "customer-key",
            "order_status": "delivered",
            "order_purchase_timestamp": "2025-01-02 10:00:00",
        }]
    ).to_csv(directory / "olist_orders_dataset.csv", index=False)
    pd.DataFrame(
        [{
            "order_id": "order-1",
            "order_item_id": 1,
            "product_id": "product-1",
            "seller_id": "seller-1",
            "shipping_limit_date": "2025-01-03",
            "price": 30.0,
            "freight_value": 5.0,
        }]
    ).to_csv(directory / "olist_order_items_dataset.csv", index=False)
    pd.DataFrame(
        [{
            "customer_id": "customer-key",
            "customer_unique_id": "unique-customer-abc",
            "customer_zip_code_prefix": 1000,
            "customer_city": "sao paulo",
            "customer_state": "SP",
        }]
    ).to_csv(directory / "olist_customers_dataset.csv", index=False)
    pd.DataFrame(
        [{
            "product_id": "product-1",
            "product_category_name": "housewares",
        }]
    ).to_csv(directory / "olist_products_dataset.csv", index=False)
    from insightflow.multitable import load_olist_directory

    canonical = load_olist_directory(directory)
    result = clean_transactions(canonical, source_profile="olist_public", transaction_status="Verified")
    assert result.curated["customer_id"].iloc[0] == "unique-customer-abc"
    assert result.metadata["transaction_status"] == "Verified"
    assert result.metadata["economic_status"] == "Estimated"
