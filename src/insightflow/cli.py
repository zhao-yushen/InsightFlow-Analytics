from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

from .config import (
    DEFAULT_DB_PATH,
    DEFAULT_RAW_PATH,
    REPORTS_DIR,
    ROOT_DIR,
    SERVER_ADDRESS,
    SERVER_PORT,
    ensure_directories,
)
from .demo_data import write_demo_csv
from .diagnostics import generate_diagnostics, profit_driver_decomposition
from .etl import clean_transactions, load_source
from .forecasting import forecast_metric
from .metrics import (
    FilterSpec,
    date_bounds,
    inventory_status,
    kpi_summary,
    monthly_trend,
    previous_period,
    quality_dimensions,
    target_status,
)
from .provenance import STATUS_LABELS, dataset_profile
from .reporting import build_html_report, build_word_report
from .warehouse import build_warehouse, query_df, table_exists
from .watcher import watch


def _full_filters(db_path: Path) -> FilterSpec:
    start, end = date_bounds(db_path)
    return FilterSpec(start, end)


def _recent_filters(db_path: Path, days: int = 90) -> FilterSpec:
    start, end = date_bounds(db_path)
    del start
    end_ts = pd.Timestamp(end)
    start_ts = end_ts - pd.Timedelta(days=max(1, days) - 1)
    return FilterSpec(start_ts.date().isoformat(), end_ts.date().isoformat())


def bootstrap(db_path: Path = DEFAULT_DB_PATH) -> None:
    ensure_directories()
    source = write_demo_csv(DEFAULT_RAW_PATH)
    result = clean_transactions(
        load_source(source),
        source_profile="demo_generated",
        transaction_status="Simulated",
    )
    stats = build_warehouse(result, db_path, source_name="cli_bootstrap")
    print(json.dumps({"database": str(db_path), **stats}, ensure_ascii=False, indent=2))


def validate(db_path: Path = DEFAULT_DB_PATH, *, strict: bool = False) -> int:
    if not table_exists(db_path, "fact_transactions"):
        print(f"数据仓库不存在：{db_path}", file=sys.stderr)
        return 2
    issues = query_df(db_path, "SELECT * FROM data_contract_issues")
    failing = issues.loc[issues["severity"] != "PASS"] if not issues.empty else issues
    print(issues.to_string(index=False))
    if not failing.empty:
        print(f"\n发现 {len(failing)} 个契约问题。", file=sys.stderr)
        has_blocker = bool((failing["severity"] == "P0").any())
        return 1 if strict or has_blocker else 0
    print("\n数据契约检查通过。")
    return 0


def report(db_path: Path = DEFAULT_DB_PATH) -> None:
    if not table_exists(db_path, "fact_transactions"):
        raise FileNotFoundError(f"数据仓库不存在：{db_path}")
    filters = _recent_filters(db_path)
    kpi = kpi_summary(db_path, filters)
    issues, drivers = generate_diagnostics(db_path, filters)
    trend = monthly_trend(db_path, filters)
    month = str(pd.Timestamp(filters.end_date).to_period("M"))
    targets = target_status(db_path, month)
    forecast = forecast_metric(db_path, "contribution_profit", horizon=3).forecast
    inventory = inventory_status(db_path, "Reorder").head(15)
    quality = quality_dimensions(db_path)
    profile = dataset_profile(db_path)
    profile_text = (
        f"交易：{STATUS_LABELS.get(str(profile.get('transaction_status', 'Mixed')), '混合')}；"
        f"成本：{STATUS_LABELS.get(str(profile.get('economic_status', 'Mixed')), '混合')}；"
        f"库存：{STATUS_LABELS.get(str(profile.get('inventory_status', 'Mixed')), '混合')}"
    )
    profit_bridge = profit_driver_decomposition(kpi, kpi_summary(db_path, previous_period(filters)))
    period = f"{filters.start_date} 至 {filters.end_date}"
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
    print(f"HTML：{html}\nWord：{docx}")


def benchmark(db_path: Path = DEFAULT_DB_PATH, runs: int = 10) -> None:
    filters = _full_filters(db_path)
    timings = []
    for _ in range(max(1, runs)):
        started = time.perf_counter()
        kpi_summary(db_path, filters)
        timings.append(time.perf_counter() - started)
    output = {
        "runs": len(timings),
        "min_ms": min(timings) * 1000,
        "median_ms": float(pd.Series(timings).median()) * 1000,
        "max_ms": max(timings) * 1000,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def run_app(extra_args: list[str]) -> None:
    if extra_args[:1] == ["--"]:
        extra_args = extra_args[1:]
    app_path = ROOT_DIR / "streamlit_app.py"
    if not app_path.exists():
        raise FileNotFoundError(f"Streamlit entry point not found: {app_path}")
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        f"--server.address={SERVER_ADDRESS}",
        f"--server.port={SERVER_PORT}",
        *extra_args,
    ]
    raise SystemExit(subprocess.call(command))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="insightflow", description="InsightFlow management CLI")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite warehouse path")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap", help="Generate demo data and initialize the warehouse")
    validate_parser = sub.add_parser("validate", help="Run saved data-contract checks")
    validate_parser.add_argument("--strict", action="store_true", help="Fail on P1 warnings as well as P0 blockers")
    sub.add_parser("report", help="Generate HTML and Word management reports")
    benchmark_parser = sub.add_parser("benchmark", help="Benchmark KPI query latency")
    benchmark_parser.add_argument("--runs", type=int, default=10)
    watch_parser = sub.add_parser("watch", help="Watch data/incoming and append new files")
    watch_parser.add_argument("--interval", type=int, default=30, help="Polling interval in seconds")
    watch_parser.add_argument("--once", action="store_true", help="Process current files once and exit")
    run_parser = sub.add_parser("run", help="Launch the Streamlit application")
    run_parser.add_argument("streamlit_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "bootstrap":
        bootstrap(args.db)
    elif args.command == "validate":
        raise SystemExit(validate(args.db, strict=args.strict))
    elif args.command == "report":
        report(args.db)
    elif args.command == "benchmark":
        benchmark(args.db, args.runs)
    elif args.command == "watch":
        watch(args.db, interval=args.interval, once=args.once)
    elif args.command == "run":
        run_app(args.streamlit_args)


if __name__ == "__main__":
    main()
