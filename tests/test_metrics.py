from pathlib import Path

from insightflow.demo_data import DemoConfig, generate_demo_transactions
from insightflow.etl import clean_transactions
from insightflow.metrics import FilterSpec, kpi_summary, monthly_trend, rfm_segments
from insightflow.warehouse import build_warehouse


def test_metrics_end_to_end(tmp_path: Path):
    db = tmp_path / "test.db"
    df = generate_demo_transactions(DemoConfig(start="2025-01-01", end="2025-03-31", base_daily_orders=12, n_customers=120, n_products=35, min_daily_orders=3))
    build_warehouse(clean_transactions(df), db)
    filters = FilterSpec("2025-01-01", "2025-03-31")
    kpi = kpi_summary(db, filters)
    assert kpi["revenue"] > 0
    assert kpi["orders"] > 0
    assert 0 <= kpi["repeat_rate"] <= 1
    assert 0 <= kpi["cancellation_rate"] <= 1
    assert len(monthly_trend(db, filters)) == 3
    assert not rfm_segments(db, filters).empty
