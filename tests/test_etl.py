import pandas as pd

from insightflow.etl import clean_transactions


def sample():
    return pd.DataFrame(
        [
            {
                "InvoiceNo": "1",
                "StockCode": "a",
                "Description": "Item",
                "Quantity": 2,
                "InvoiceDate": "2025-01-01",
                "UnitPrice": 10,
                "CustomerID": 1,
                "Country": "UK",
            },
            {
                "InvoiceNo": "C2",
                "StockCode": "b",
                "Description": "Return",
                "Quantity": -1,
                "InvoiceDate": "2025-01-02",
                "UnitPrice": 5,
                "CustomerID": 2,
                "Country": "UK",
            },
            {
                "InvoiceNo": "1",
                "StockCode": "a",
                "Description": "Item",
                "Quantity": 2,
                "InvoiceDate": "2025-01-01",
                "UnitPrice": 10,
                "CustomerID": 1,
                "Country": "UK",
            },
            {
                "InvoiceNo": "3",
                "StockCode": "c",
                "Description": "Bad",
                "Quantity": 1,
                "InvoiceDate": "bad",
                "UnitPrice": 0,
                "CustomerID": None,
                "Country": "UK",
            },
        ]
    )


def test_clean_transactions_flags_and_deduplicates():
    result = clean_transactions(sample())
    assert len(result.curated) == 3
    assert int(result.curated["is_cancellation"].sum()) == 1
    assert int(result.curated["sale_valid"].sum()) == 1
    metrics = dict(
        zip(result.quality_summary["metric"], result.quality_summary["value"], strict=False)
    )
    assert metrics["duplicate_rows_removed"] == 1
    assert metrics["invalid_price_rows"] == 1
