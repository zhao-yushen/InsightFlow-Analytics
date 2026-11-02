from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from insightflow.etl import clean_transactions, load_source
from insightflow.ingest import (
    apply_mapping,
    auto_canonicalize,
    canonical_field,
    decode_bytes,
    missing_required,
    parse_datetime,
    parse_number,
    parse_rate,
    read_table,
    suggest_mapping,
)


def test_gbk_export_with_chinese_headers_reads_cleanly():
    text = "订单号,商品编码,商品名称,数量,单价,下单时间,国家\nA1,S1,保温杯,2,￥39.90,2025年3月1日,中国\n"
    frame = read_table(text.encode("gbk"), "export.csv")
    canonical, notes = auto_canonicalize(frame)
    assert canonical["unit_price"].iloc[0] == pytest.approx(39.9)
    assert canonical["invoice_date"].iloc[0] == pd.Timestamp("2025-03-01")
    assert notes == []
    result = clean_transactions(canonical, transaction_status="Verified")
    assert result.metadata["valid_sales_rows"] == 1
    assert result.curated["country"].iloc[0] == "China"


def test_decoder_prefers_strict_encodings():
    assert decode_bytes("价格".encode("utf-8-sig"))[1] == "utf-8-sig"
    assert decode_bytes("价格".encode("gbk"))[1] == "gb18030"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("¥1,299.00", 1299.0),
        ("1.299,50", 1299.5),
        ("1,299", 1299.0),
        ("12,5", 12.5),
        ("(12.00)", -12.0),
        ("RM 45", 45.0),
        ("€ 3.20", 3.2),
        ("2件", 2.0),
        ("", np.nan),
    ],
)
def test_number_parsing_handles_regional_formats(raw, expected):
    parsed = parse_number(pd.Series([raw], dtype="object")).iloc[0]
    assert (np.isnan(parsed) and np.isnan(expected)) or parsed == pytest.approx(expected)


def test_discounts_in_whole_percents_are_rescaled():
    assert parse_rate(pd.Series([5, 10, 0])).tolist() == pytest.approx([0.05, 0.10, 0.0])
    assert parse_rate(pd.Series(["5%", "10%"])).tolist() == pytest.approx([0.05, 0.10])
    assert parse_rate(pd.Series([0.05, 0.9])).tolist() == pytest.approx([0.05, 0.9])


@pytest.mark.parametrize(
    "raw",
    ["2025-03-01", "2025/03/01", "2025年3月1日", "2025-03-01T10:30:00Z", "Mar 1, 2025"],
)
def test_date_parsing_covers_common_exports(raw):
    parsed = parse_datetime(pd.Series([raw])).iloc[0]
    assert parsed.normalize() == pd.Timestamp("2025-03-01")


def test_excel_serial_dates_become_calendar_dates():
    assert parse_datetime(pd.Series([45717])).iloc[0] == pd.Timestamp("2025-03-01")


def test_semicolon_files_with_european_decimals(tmp_path):
    path = tmp_path / "sales.csv"
    path.write_text(
        "Order ID;SKU;Quantity;Price;Date;Country\nA1;S1;2;12,50;2025-03-01;Germany\n",
        encoding="utf-8",
    )
    canonical, _ = auto_canonicalize(load_source(path))
    assert canonical["unit_price"].iloc[0] == pytest.approx(12.5)


def test_json_and_jsonl_sources(tmp_path):
    rows = [{"order_id": "A1", "sku": "S1", "qty": 1, "price": 10, "date": "2025-03-01", "country": "UK"}]
    nested = tmp_path / "orders.json"
    nested.write_text(json.dumps({"data": rows}), encoding="utf-8")
    lines = tmp_path / "orders.jsonl"
    lines.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    assert len(read_table(nested)) == 1
    assert len(read_table(lines)) == 1


def test_mapping_suggestions_report_how_sure_they_are():
    frame = pd.DataFrame(
        {
            "订单编号": ["A1"],
            "SKU": ["S1"],
            "Qty": [2],
            "Sale Price": [9.5],
            "Created At": ["2025-03-01"],
            "Ship Country": ["Japan"],
            "Unknown Column": ["x"],
        }
    )
    mapping = suggest_mapping(frame)
    assert mapping["invoice_no"].column == "订单编号"
    assert mapping["invoice_no"].confidence == 1.0
    assert mapping["invoice_date"].column == "Created At"
    assert "Unknown Column" not in {item.column for item in mapping.values()}


def test_similar_headers_match_with_lower_confidence():
    frame = pd.DataFrame({"Invoice Nunber": ["A1"]})
    mapping = suggest_mapping(frame)
    assert mapping["invoice_no"].confidence < 1.0
    assert mapping["invoice_no"].reason == "similar name"


def test_dates_are_found_by_their_values():
    frame = pd.DataFrame({"when": ["2025-03-01", "2025-03-02"], "col": ["a", "b"]})
    assert suggest_mapping(frame)["invoice_date"].column == "when"


def test_missing_fields_are_derived_and_every_derivation_is_noted():
    frame = pd.DataFrame(
        {
            "Date": ["2025-03-01"],
            "Product Name": ["Mug"],
            "Quantity": [4],
            "Total": ["¥100.00"],
        }
    )
    mapping = {item.field: item.column for item in suggest_mapping(frame).values()}
    canonical, notes = apply_mapping(frame, mapping, default_country="China")
    assert canonical["unit_price"].iloc[0] == pytest.approx(25.0)
    assert canonical["stock_code"].iloc[0] == "MUG"
    assert canonical["invoice_no"].iloc[0].startswith("AUTO-")
    assert canonical["country"].iloc[0] == "China"
    assert len(notes) == 4
    assert clean_transactions(canonical, transaction_status="Verified").metadata["valid_sales_rows"] == 1


def test_required_gaps_name_what_cannot_be_derived():
    assert set(missing_required({"quantity": "q"})) == {"invoice_date", "unit_price", "stock_code"}
    assert missing_required({"invoice_date": "d", "line_amount": "a", "description": "n"}) == []


def test_cancelled_status_becomes_a_sale_with_its_reversal():
    frame = pd.DataFrame(
        {
            "Order ID": ["A1", "A2"],
            "SKU": ["S1", "S2"],
            "Quantity": [2, 1],
            "Price": [10.0, 20.0],
            "Date": ["2025-03-01", "2025-03-02"],
            "Country": ["China", "China"],
            "Order Status": ["delivered", "已取消"],
        }
    )
    canonical, notes = auto_canonicalize(frame)
    assert len(canonical) == 3
    assert any("取消" in note for note in notes)
    curated = clean_transactions(canonical, transaction_status="Verified").curated
    assert curated.groupby("invoice_no")["net_revenue"].sum().sum() == pytest.approx(
        curated.loc[curated["invoice_no"] == "A1", "net_revenue"].sum()
    )


def test_watched_files_reject_unmappable_columns():
    with pytest.raises(ValueError, match="无法识别必要字段"):
        auto_canonicalize(pd.DataFrame({"foo": [1], "bar": [2]}))


def test_header_variants_share_one_canonical_field():
    for variant in ("UnitPrice", "unit_price", "Unit Price", "单价", "UNIT-PRICE"):
        assert canonical_field(variant) == "unit_price"
