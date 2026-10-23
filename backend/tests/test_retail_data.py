import sys
from pathlib import Path
from decimal import Decimal
from datetime import datetime
import pytest
import csv

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))


def test_csv_preserves_embedded_quotes_commas_and_newlines(tmp_path):
    import duckdb
    from retail_pipeline import RAW_DDL, load_normalized
    target = tmp_path / 'lines.csv'
    description = 'RECORD FRAME 7" SINGLE, SIZE\nSECOND LINE'
    with target.open('w', newline='', encoding='utf-8') as output:
        csv.writer(output).writerow([1,'test',2,'001','001A',description,1,'2011-01-01 00:00:00','2.5',None,'France'])
    db = duckdb.connect()
    db.execute(RAW_DDL)
    load_normalized(db, target)
    assert db.execute('SELECT description,customer_id FROM raw_lines').fetchone() == (description, None)


def test_source_identifiers_preserve_strings_and_missing_customers():
    from retail_pipeline import normalize_row
    row = normalize_row(["C001", "001A", "Item", -2, datetime(2011, 1, 2), 1.25, None, "United Kingdom"], 1, "sheet", 2)
    assert row[3:5] == ["C001", "001A"]
    assert row[9] is None
    assert row[8] == "1.25"


@pytest.mark.parametrize("invoice,quantity,price,expected", [
    ("100", 2, "1.25", ("2.500000", 2, "100", "123", "0.000000")),
    ("C100", -2, "1.25", ("0.000000", 0, None, None, "2.500000")),
    ("100", -2, "1.25", ("0.000000", 0, None, None, "0.000000")),
    ("100", 2, "0", ("0.000000", 0, None, None, "0.000000")),
])
def test_warehouse_classification_does_not_treat_adjustments_as_sales(tmp_path, invoice, quantity, price, expected):
    import duckdb
    from retail_pipeline import RAW_DDL, build_warehouse
    db = duckdb.connect()
    db.execute(RAW_DDL)
    db.execute("INSERT INTO raw_lines VALUES (1,'test',2,?,?, 'Product',?, '2011-01-02 10:00:00',?, '123','France')", [invoice, "x", quantity, price])
    build_warehouse(db)
    row = db.execute("SELECT sale_amount,sale_units,sale_invoice,sale_customer,cancel_amount FROM fact_retail_line").fetchone()
    assert tuple(str(v) if isinstance(v, Decimal) else v for v in row) == expected


def test_identical_source_rows_are_preserved_and_counted():
    import duckdb
    from retail_pipeline import RAW_DDL, build_warehouse, profile
    db = duckdb.connect()
    db.execute(RAW_DDL)
    for row_id in (1, 2):
        db.execute("INSERT INTO raw_lines VALUES (?,'test',?, '100','x','Product',1,'2011-01-02',2.50,NULL,'France')", [row_id, row_id + 1])
    build_warehouse(db)
    assert db.execute("SELECT COUNT(*) FROM fact_retail_line").fetchone()[0] == 2
    result = profile(db)
    assert result["duplicate_extra_rows"] == 1
    assert result["missing_customers"] == 2
