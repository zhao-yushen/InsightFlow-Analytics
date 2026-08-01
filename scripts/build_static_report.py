from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pandas as pd

from insightflow.config import DEFAULT_DB_PATH, REPORTS_DIR
from insightflow.diagnostics import generate_diagnostics, profit_driver_decomposition
from insightflow.forecasting import forecast_metric
from insightflow.metrics import (
    FilterSpec,
    date_bounds,
    inventory_status,
    kpi_summary,
    monthly_trend,
    previous_period,
    quality_dimensions,
    target_status,
)
from insightflow.provenance import STATUS_LABELS, dataset_profile
from insightflow.reporting import build_html_report, build_word_report
from insightflow.warehouse import table_exists


def main() -> None:
    if not table_exists(DEFAULT_DB_PATH, "fact_transactions"):
        from bootstrap import main as bootstrap

        bootstrap()
    _, max_date = date_bounds(DEFAULT_DB_PATH)
    end = pd.Timestamp(max_date)
    start = end - pd.Timedelta(days=89)
    filters = FilterSpec(start.date().isoformat(), end.date().isoformat())
    kpi = kpi_summary(DEFAULT_DB_PATH, filters)
    issues, drivers = generate_diagnostics(DEFAULT_DB_PATH, filters)
    trend = monthly_trend(DEFAULT_DB_PATH, FilterSpec())
    period = f"{filters.start_date} 至 {filters.end_date}"
    month = str(end.to_period("M"))
    targets = target_status(DEFAULT_DB_PATH, month)
    forecast = forecast_metric(DEFAULT_DB_PATH, "contribution_profit", horizon=3).forecast
    inventory = inventory_status(DEFAULT_DB_PATH, "Reorder").head(15)
    quality = quality_dimensions(DEFAULT_DB_PATH)
    profile = dataset_profile(DEFAULT_DB_PATH)
    profile_text = (
        f"交易：{STATUS_LABELS.get(str(profile.get('transaction_status', 'Mixed')), '混合')}；"
        f"成本：{STATUS_LABELS.get(str(profile.get('economic_status', 'Mixed')), '混合')}；"
        f"库存：{STATUS_LABELS.get(str(profile.get('inventory_status', 'Mixed')), '混合')}"
    )
    profit_bridge = profit_driver_decomposition(kpi, kpi_summary(DEFAULT_DB_PATH, previous_period(filters)))

    html = build_html_report(
        REPORTS_DIR / "insightflow_business_report.html",
        period,
        kpi,
        issues,
        drivers,
        trend,
        profit_table=profit_bridge,
        targets=targets,
        forecast=forecast,
        inventory=inventory,
        quality=quality,
        data_profile=profile_text,
    )
    docx = build_word_report(
        REPORTS_DIR / "insightflow_weekly_report.docx",
        period,
        kpi,
        issues,
        drivers,
        targets=targets,
        forecast=forecast,
        inventory=inventory,
        quality=quality,
        data_profile=profile_text,
    )
    print(f"HTML report: {html}")
    print(f"Word report: {docx}")


if __name__ == "__main__":
    main()
