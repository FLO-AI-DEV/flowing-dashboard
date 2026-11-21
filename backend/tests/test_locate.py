"""The heading-based reader must give the same table however the sheet is shuffled."""
import pytest

from app.locate import Col, SheetLayoutError, locate, read_table

COLS = [
    Col("party", "PARTY NAME", "CLIENT NAME", "CUSTOMER"),
    Col("qty", "QTY", "PCS", "QUANTITY"),
    Col("date", "ORDER DATE", "DATE"),
    Col("remarks", "REMARKS", required=False),
]

CLEAN = [
    ["S.NO", "PARTY NAME", "ORDER DATE", "QTY", "QTY RECEIVED", "REMARKS"],
    ["1", "Alpha Traders", "01/04/2026", "100", "40", "urgent"],
    ["2", "Beta Fashions", "03/04/2026", "50", "50", ""],
]
EXPECTED = [["Alpha Traders", "100", "01/04/2026", "urgent"], ["Beta Fashions", "50", "03/04/2026", ""]]


def rows(df):
    return df[["party", "qty", "date", "remarks"]].values.tolist()


def test_clean_sheet():
    df, lay = read_table(CLEAN, COLS, tab="ORDERS")
    assert rows(df) == EXPECTED
    assert lay.header_row == 0
    assert lay.columns["qty"] == 3          # exact "QTY", not "QTY RECEIVED"


def test_title_rows_and_inserted_columns():
    grid = [
        ["FLO-WING ORDER REGISTER 2026-27"],
        [],
        ["Updated by Deepak", "", "", "note: check daily"],
        ["", "NEW COL", "S.NO", "Order Dt.", "Party Name", "x", "Qty", "Qty Received", "Remarks"],
        ["", "z", "1", "01/04/2026", "Alpha Traders", "", "100", "40", "urgent"],
        ["", "", "2", "03/04/2026", "Beta Fashions", "", "50", "50", ""],
    ]
    cols = [Col("party", "PARTY NAME"), Col("qty", "QTY"), Col("date", "ORDER DATE", "ORDER DT"),
            Col("remarks", "REMARKS", required=False)]
    df, lay = read_table(grid, cols)
    assert rows(df) == EXPECTED
    assert lay.header_row == 3


def test_two_row_merged_heading():
    grid = [
        ["", "", "PRODUCTION", "", "DISPATCH", ""],
        ["PARTY NAME", "ORDER DATE", "PCS", "DATE", "PCS", "DATE"],
        ["Alpha Traders", "01/04/2026", "100", "05/04/2026", "60", "09/04/2026"],
    ]
    cols = [Col("party", "PARTY NAME"), Col("prod_pcs", "PRODUCTION PCS"), Col("disp_pcs", "DISPATCH PCS"),
            Col("disp_date", "DISPATCH DATE")]
    df, lay = read_table(grid, cols)
    assert lay.columns == {"party": 0, "prod_pcs": 2, "disp_pcs": 4, "disp_date": 5}
    assert df.iloc[0].tolist() == ["Alpha Traders", "100", "60", "09/04/2026"]


def test_drops_blank_total_and_repeated_heading_rows():
    grid = CLEAN + [
        ["", "", "", "", "", ""],
        ["", "TOTAL", "", "150", "90", ""],
        ["S.NO", "PARTY NAME", "ORDER DATE", "QTY", "QTY RECEIVED", "REMARKS"],    # second pasted block
        ["3", "Gamma Silks", "05/04/2026", "20", "0", ""],
        ["", "Grand Total", "", "170", "", ""],
    ]
    df, _ = read_table(grid, COLS)
    assert df["party"].tolist() == ["Alpha Traders", "Beta Fashions", "Gamma Silks"]


def test_alias_spelling():
    grid = [["Customer", "Quantity", "Date"], ["Alpha", "5", "01/04/2026"]]
    df, lay = read_table(grid, COLS)
    assert df.iloc[0][["party", "qty", "date"]].tolist() == ["Alpha", "5", "01/04/2026"]
    assert lay.missing == ["remarks"]
    assert df.iloc[0]["remarks"] == ""


def test_missing_required_column_is_loud():
    grid = [["PARTY NAME", "ORDER DATE", "REMARKS"], ["Alpha", "01/04/2026", ""]]
    with pytest.raises(SheetLayoutError) as e:
        locate(grid, COLS, tab="ORDERS")
    assert e.value.missing == ["qty"]
    assert "ORDERS" in str(e.value) and "PARTY NAME" in str(e.value)
