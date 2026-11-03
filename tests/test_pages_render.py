"""Open every page headlessly on a real warehouse and fail on any exception."""

from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from insightflow import cli, config, ui
from insightflow.backup import list_backups
from insightflow.etl import clean_transactions
from insightflow.experiments import experiment_catalog
from insightflow.i18n import ZH
from insightflow.metrics import FilterSpec
from insightflow.warehouse import build_warehouse, connect, warehouse_schema_version

PAGES = [
    "overview",
    "markets",
    "sales",
    "profit",
    "customers",
    "products",
    "inventory",
    "diagnostics",
    "planning",
    "pricing",
    "decision_lab",
    "experiments",
    "actions",
    "assistant",
    "data_hub",
    "quality",
    "report",
]


@pytest.mark.parametrize("name", PAGES)
def test_page_renders_without_exceptions(page_warehouse: Path, name: str) -> None:
    script = f"from insightflow.pages import {name}\n{name}.render()\n"
    app = AppTest.from_string(script, default_timeout=120).run()
    assert not app.exception, [str(item.value) for item in app.exception]
    assert not app.error, [item.value for item in app.error]


def test_full_app_shell_starts(page_warehouse: Path) -> None:
    entry = Path(config.ROOT_DIR) / "streamlit_app.py"
    app = AppTest.from_file(str(entry), default_timeout=120).run()
    assert not app.exception, [str(item.value) for item in app.exception]


MESSY_EXPORT = (
    "订单号,商品编码,商品名称,数量,单价,下单时间,国家,订单状态\n"
    "D-1,S-1,保温杯,2,￥39.90,2025年12月1日,中国,已完成\n"
    "D-2,S-2,咖啡杯,1,￥25.00,2025年12月2日,日本,已取消\n"
)


def _upload_script(content: bytes, name: str) -> str:
    return (
        "import types\n"
        "import streamlit as st\n"
        f"fake = types.SimpleNamespace(name={name!r}, getvalue=lambda: {content!r})\n"
        "st.file_uploader = lambda *args, **kwargs: fake\n"
        "from insightflow.pages import data_hub\n"
        "data_hub.render()\n"
    )


def test_messy_upload_passes_precheck_and_imports(page_warehouse: Path) -> None:
    script = _upload_script(MESSY_EXPORT.encode("gbk"), "export.csv")
    app = AppTest.from_string(script, default_timeout=120).run()
    assert not app.exception, [str(item.value) for item in app.exception]
    assert not app.error, [item.value for item in app.error]
    assert app.toggle(key="import_replace").value is True
    app = app.toggle(key="import_replace").set_value(False).run()
    importer = next(button for button in app.button if button.label == "确认导入")
    assert not importer.disabled
    app = importer.click().run()
    assert not app.exception, [str(item.value) for item in app.exception]


def test_problem_rows_wait_for_a_decision_and_a_backup_comes_first(page_warehouse: Path) -> None:
    rows = ["订单号,商品编码,商品名称,数量,单价,下单时间,国家"]
    rows += [f"D-{index},S-1,保温杯,1,10,2025-12-0{index % 9 + 1},中国" for index in range(12)]
    rows.append("D-99,S-2,破损,1,0,2025-12-01,中国")
    script = _upload_script("\n".join(rows).encode(), "mixed.csv")
    app = AppTest.from_string(script, default_timeout=120).run()
    assert not app.exception, [str(item.value) for item in app.exception]
    importer = next(button for button in app.button if button.label == "确认导入")
    assert importer.disabled
    app = app.toggle(key="import_replace").set_value(False).run()
    app = app.checkbox(key="import_isolate").check().run()
    importer = next(button for button in app.button if button.label == "确认导入")
    assert not importer.disabled
    before = {path.name for path in list_backups(page_warehouse)}
    app = importer.click().run()
    assert not app.exception, [str(item.value) for item in app.exception]
    assert {path.name for path in list_backups(page_warehouse)} - before


def test_a_file_that_is_mostly_broken_cannot_be_imported(page_warehouse: Path) -> None:
    rows = ["订单号,商品编码,商品名称,数量,单价,下单时间,国家"]
    rows += [f"D-{index},S-1,保温杯,1,0,2025-12-01,中国" for index in range(10)]
    script = _upload_script("\n".join(rows).encode(), "broken.csv")
    app = AppTest.from_string(script, default_timeout=120).run()
    assert not app.exception
    importer = next(button for button in app.button if button.label == "确认导入")
    assert importer.disabled


def test_unreadable_mapping_names_what_is_missing(page_warehouse: Path) -> None:
    script = _upload_script("a,b\n1,2\n".encode(), "bad.csv")
    app = AppTest.from_string(script, default_timeout=120).run()
    assert not app.exception
    assert any("还缺少" in item.value for item in app.error)


@pytest.mark.parametrize("name", ["overview", "markets", "decision_lab", "experiments"])
def test_english_interface_renders(page_warehouse: Path, name: str) -> None:
    script = (
        "import streamlit as st\n"
        "st.session_state['insightflow_language'] = 'en'\n"
        f"from insightflow.pages import {name}\n"
        f"{name}.render()\n"
    )
    app = AppTest.from_string(script, default_timeout=120).run()
    assert not app.exception, [str(item.value) for item in app.exception]


@pytest.mark.parametrize("name", ["overview", "markets", "sales", "customers", "products"])
def test_empty_scope_explains_itself(
    page_warehouse: Path, name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = importlib.import_module(f"insightflow.pages.{name}")
    empty = FilterSpec("2031-01-01", "2031-01-31")
    monkeypatch.setattr(page, "sidebar_filters", lambda _: empty)
    script = f"from insightflow.pages import {name}\n{name}.render()\n"
    app = AppTest.from_string(script, default_timeout=120).run()
    assert not app.exception, [str(item.value) for item in app.exception]


def test_selecting_a_market_opens_its_detail(page_warehouse: Path) -> None:
    script = (
        "import streamlit as st\n"
        "st.session_state['market_selected'] = 'China'\n"
        "from insightflow.pages import markets\n"
        "markets.render()\n"
    )
    app = AppTest.from_string(script, default_timeout=120).run()
    assert not app.exception, [str(item.value) for item in app.exception]
    assert any(button.label == "查看全部区域" for button in app.button)


@pytest.mark.parametrize("question", ["为什么利润下降？", "哪些商品适合搭配销售？"])
def test_assistant_answers_a_picked_question(page_warehouse: Path, question: str) -> None:
    script = (
        "import streamlit as st\n"
        f"st.session_state['assistant_pick'] = {question!r}\n"
        "from insightflow.pages import assistant\n"
        "assistant.render()\n"
    )
    app = AppTest.from_string(script, default_timeout=120).run()
    assert not app.exception, [str(item.value) for item in app.exception]
    assert len(app.chat_message) == 2


def test_fault_drill_runs_without_the_demo_file(page_warehouse: Path) -> None:
    script = "from insightflow.pages import quality\nquality.render()\n"
    app = AppTest.from_string(script, default_timeout=120).run()
    drill = next(button for button in app.button if button.label == "运行演练")
    app = drill.click().run()
    assert not app.exception, [str(item.value) for item in app.exception]


def test_saving_actions_from_the_page(page_warehouse: Path) -> None:
    script = "from insightflow.pages import actions\nactions.render()\n"
    app = AppTest.from_string(script, default_timeout=120).run()
    assert not app.exception, [str(item.value) for item in app.exception]
    save = next(button for button in app.button if button.label == ZH["actions.save"])
    app = save.click().run()
    assert not app.exception, [str(item.value) for item in app.exception]


def test_importing_a_real_experiment_from_the_page(page_warehouse: Path) -> None:
    rows = ["experiment_id,customer_id,assignment,converted,net_revenue,contribution_profit,returned"]
    rows += [
        f"EXP_REAL,{index},{'Treatment' if index % 2 else 'Control'},1,100,{20 + index % 7},0"
        for index in range(200)
    ]
    content = "\n".join(rows).encode()
    script = (
        "import types\n"
        "import streamlit as st\n"
        f"fake = types.SimpleNamespace(name='real.csv', getvalue=lambda: {content!r})\n"
        "st.file_uploader = lambda *args, **kwargs: fake\n"
        "st.session_state['experiment_name'] = 'Real checkout test'\n"
        "from insightflow.pages import experiments\n"
        "experiments.render()\n"
    )
    app = AppTest.from_string(script, default_timeout=120).run()
    importer = next(button for button in app.button if button.label == "导入实验")
    assert not importer.disabled
    app = importer.click().run()
    assert not app.exception, [str(item.value) for item in app.exception]
    assert "EXP_REAL" in set(experiment_catalog(page_warehouse)["experiment_id"])


def test_stale_real_warehouse_asks_for_a_reimport(tmp_path: Path) -> None:
    db = tmp_path / "old.db"
    frame = pd.DataFrame(
        [
            {
                "invoice_no": "1",
                "stock_code": "S",
                "description": "Item",
                "quantity": 1,
                "invoice_date": "2025-01-01",
                "unit_price": 10.0,
                "country": "China",
            }
        ]
    )
    build_warehouse(clean_transactions(frame, transaction_status="Verified"), db)
    with connect(db) as conn:
        conn.execute("UPDATE data_profiles SET schema_version='4.1'")
    assert warehouse_schema_version(db) == "4.1"
    with pytest.raises(FileNotFoundError, match="旧版本"):
        ui.ensure_demo_warehouse(db)


def test_command_line_validates_and_reports(
    demo_warehouse: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(cli, "REPORTS_DIR", tmp_path)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--db", str(demo_warehouse), "validate"])
    assert exit_info.value.code == 0
    cli.main(["--db", str(demo_warehouse), "report"])
    assert (tmp_path / "insightflow_business_report.html").exists()
    assert (tmp_path / "insightflow_weekly_report.docx").exists()
    cli.main(["--db", str(demo_warehouse), "benchmark", "--runs", "2"])
    assert "median_ms" in capsys.readouterr().out
