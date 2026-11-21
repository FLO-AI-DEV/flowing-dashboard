"""Real heading rows copied from NEW ORDERSHEET-2026-27 (20 Nov 2026), each with its own quirk. Every one must read to
the same fields. Client names below are from the real sheet's first rows."""
from datetime import date

from app.dashboards import orders as o

STD = ["SR NO.", "DATE", "DATE", "CLIENT NAME", "ORDER TYPE", "SALES PERSON", "LEDGER", "BILL/PO BY MONA", "",
       "HOLD REASON", "ORDER (NO. OF SETS)", "PENDING(NO. OF SETS)", "BOX NOT OKAY REASON", "PO STATUS",
       "PO NOT DONE REASON", "PO STATUS DATE TIME", "BILL STATUS", "BILL NOT DONE REASON", "BILL STATUS TIME AND DATE"]

# NOV CREDIT SALE: headings in row 1, A blank, C "TIMESTAMP", Mona's date column headed by a date, count row "609"
NOV_CREDIT = [
    ["   ", "DATE", "TIMESTAMP", "CLIENT NAME", "ORDER TYPE", "SALES PERSON", "LEDGER", "MONA REPLY", "03/08/2026",
     "HOLD REASON", "ORDER (NO. OF SETS)", "PENDING(NO. OF SETS)", "BOX NOT OKAY REASON", "PO STATUS",
     "PO NOT DONE REASON", "PO STATUS DATE TIME", "BILL STATUS", "BILL NOT DONE REASON", "BILL STATUS TIME AND DATE"],
    ["609"],
    ["1", "01/11/2026", "", "Kalakriti Lucknow", "WHATSAPP", "piyush", "", "BILL", "02/11/2026", "", "4", "", "", "", "",
     "", "DONE", "", "02/11/2026"],
    ["3", "01/11/2026", "", "Paratpar industries surat(Dispatch after diwali) 002", "WHATSAPP", "piyush", "", "BILL",
     "03/11/2026", "", "3", "", "", "", "", "", "DONE", "", "10/11/2026"],
]

# NOV CASH SALE: blank row 1, headings in row 2, two DATE columns, no Mona step (PO straight away)
NOV_CASH = [
    ["     "],
    STD,
    ["1", "01/11/2026", "", "Shree retails jodhpur", "WHATSAPP", "piyush", "", "", "", "", "1", "", "", "DONE", "",
     "02/11/2026"],
]

# APR CREDIT SALE: extra blank column B (everything shifted), Mona's two columns have NO headings
APR_CREDIT = [
    ["  "],
    ["SR NO.", "", "DATE", "DATE", "CLIENT NAME", "ORDER TYPE", "SALES PERSON", "LEDGER", " ", "", "HOLD REASON",
     "ORDER (NO. OF SETS)", "PENDING(NO. OF SETS)", "BOX NOT OKAY REASON", "PO STATUS", "PO NOT DONE REASON",
     "PO STATUS DATE TIME", "BILL STATUS", "BILL NOT DONE REASON", "BILL STATUS TIME AND DATE"],
    ["1", "", "01/04/2026", "01/04/2026", "Shehzad Mahel punjab", "WHATSAPP", "piyush",
     "SHEHZAD MAHAL (AMRITSAR) W.S.085", "BILL", "02/04/2026", "", "18pcs", "", "", "", "", "", "DONE"],
    ["2", "", "01/04/2026", "01/04/2026", "Label madhuri", "WHATSAPP", "Boss", "LABEL MADHURI THAKKAR (PUNE) W.S.103",
     "BILL", "02/04/2026", "", "5", "", "", "", "", "", "DONE"],
]

# APR CASH SALE: a client's name typed over the CLIENT NAME heading
APR_CASH = [
    ["BEFORE DISPATCH ORDER PROCESS SHEET"],
    STD[:3] + ["chahat gorkhpur"] + STD[4:],
    ["1", "01/04/2026", "01/04/2026", "Heritage banglore", "WHATSAPP", "dev", "", "", "", "", "14", "", "", "DONE", "",
     "04/04/2026"],
    ["3", "01/04/2026", "01/04/2026", "Verrast lucknow", "WHATSAPP", "dev", "", "", "", "", "2", "", "", "DONE", "", "",
     "DONE"],
]


def read(grid, tab):
    df, lay = o.read_order_tab(grid, tab)
    return df, lay


def test_nov_credit():
    df, lay = read(NOV_CREDIT, "NOV CREDIT SALE")
    assert lay.header_row == 0 and lay.inferred == ["mona_time"]
    assert df["client"].tolist() == ["Kalakriti Lucknow", "Paratpar industries surat(Dispatch after diwali) 002"]
    assert df[["mona", "mona_time", "sets_n", "bill_status", "bill_time"]].iloc[1].tolist() == \
        ["BILL", "03/11/2026", 3, "DONE", "10/11/2026"]


def test_nov_cash_two_date_columns():
    df, lay = read(NOV_CASH, "NOV CASH SALE")
    assert lay.header_row == 1 and lay.columns["date"] == 1
    r = df.iloc[0]
    assert (r["client"], r["po_status"], r["po_time"], r["mona"]) == ("Shree retails jodhpur", "DONE", "02/11/2026", "")


def test_apr_credit_blank_mona_headings_and_shift():
    df, lay = read(APR_CREDIT, "APR CREDIT SALE")
    assert set(lay.inferred) == {"mona", "mona_time"}
    assert lay.columns["mona"] == 8 and lay.columns["date"] == 2
    assert df[["client", "mona", "mona_time", "sets_n"]].iloc[0].tolist() == \
        ["Shehzad Mahel punjab", "BILL", "02/04/2026", 18]


def test_apr_cash_heading_typed_over():
    df, lay = read(APR_CASH, "APR CASH SALE")
    assert "client" in lay.inferred
    assert df["client"].tolist() == ["Heritage banglore", "Verrast lucknow"]


def test_channel_flows():
    """Cash orders go straight to PO (no Mona); credit orders wait for Mona first."""
    d = o.parse_orders([("NOV CREDIT SALE", NOV_CREDIT + [
        ["4", "19/11/2026", "", "Waiting Mona", "WHATSAPP", "preeti", "", "", "", "", "2"]]),
        ("NOV CASH SALE", NOV_CASH + [
            ["2", "18/11/2026", "", "Waiting PO", "WHATSAPP", "piyush", "", "", "", "", "1"],
            ["3", "18/11/2026", "", "PO done", "WHATSAPP", "piyush", "", "", "", "", "1", "", "", "DONE", "", "19/11/2026"]])])
    v = o.stage_view(d["orders"], date(2026, 11, 20)).set_index("client")
    assert v.loc["Waiting Mona", "stage"] == "reply"
    assert v.loc["Waiting PO", ["stage", "owner"]].tolist() == ["po", "PO team"]
    assert v.loc["PO done", "stage"] == "done"                   # cash orders are done when PO is DONE
    assert v.loc["Shree retails jodhpur", "stage"] == "done"     # cash tab: PO DONE
    assert v.loc["Kalakriti Lucknow", ["stage", "reply_days", "bill_days"]].tolist() == ["done", 1, 1]


def test_parse_qty():
    assert [o.parse_qty(v) for v in ["4", "1 pcs", "3+6 pcs", "", None, "18pcs"]] == [4, 1, 9, 0, 0, 18]


# JULY CREDIT SALE: a stray heading in row 1, the DATE heading blank (next to an empty TIMESTAMP column), Mona's
# heading blank and her date column headed by a date
JULY_CREDIT = [
    [""] * 18 + ["BILL STATUS TIME AND DATE"],
    ["SR NO.", " ", "TIMESTAMP", "CLIENT NAME", "ORDER TYPE", "SALES PERSON", "LEDGER", "  ", "06/07/2026",
     "HOLD REASON", "ORDER (NO. OF SETS)", "PENDING(NO. OF SETS)", "BOX NOT OKAY REASON", "PO STATUS",
     "PO NOT DONE REASON", "PO STATUS DATE TIME", "BILL STATUS", "BILL NOT DONE REASON", "BILL STATUS TIME AND DATE"],
    ["1", "01/07/2026", "", "Aristocrat Gallery Ludhiyana", "WHATSAPP", "piyush", "", "BILL", "02/07/2026", "", "4", "",
     "", "", "", "", "DONE"],
]


def test_july_credit_blank_date_heading():
    df, lay = read(JULY_CREDIT, "JULY CREDIT SALE")
    assert lay.header_row == 1 and lay.columns["date"] == 1
    assert {"date", "mona", "mona_time"} <= set(lay.inferred)
    assert df[["date", "client", "mona", "mona_time"]].iloc[0].tolist() == \
        ["01/07/2026", "Aristocrat Gallery Ludhiyana", "BILL", "02/07/2026"]


def test_old_unbilled_orders_are_not_late_work():
    old = ["9", "01/08/2026", "", "Old order", "WHATSAPP", "piyush", "", "BILL", "02/08/2026", "", "2"]
    d = o.parse_orders([("NOV CREDIT SALE", NOV_CREDIT + [old])])
    v = o.stage_view(d["orders"], date(2026, 11, 20)).set_index("client")
    assert v.loc["Old order", ["stage", "state", "waiting"]].tolist() == ["old", "old", "Not marked billed"]
    h = o.home_dashboard(d, {}, today=date(2026, 11, 20))
    assert {k["id"]: k["value"] for k in h["kpis"]}["late"] == 0
    assert any(a["stage"] == "Not marked billed" for a in h["actions"])


def test_daily_close_points_at_what_is_wrong():
    """Today's orders are counted against today; older not-done orders are backlog, grouped by what the sheet is missing."""
    rows = [
        ["5", "20/11/2026", "", "Done today", "WHATSAPP", "piyush", "", "BILL", "", "", "2", "", "", "", "", "", "DONE"],
        ["6", "20/11/2026", "", "Pending today", "WHATSAPP", "piyush", "", "BILL", "", "", "2"],
        ["7", "18/11/2026", "", "Silent old", "WHATSAPP", "asif", "", "", "", "", "3"],
        ["8", "17/11/2026", "", "PO stuck", "WHATSAPP", "asif", "", "PO", "", "", "1", "", "", "", "no fabric"],
    ]
    d = o.parse_orders([("NOV CREDIT SALE", NOV_CREDIT + rows)])
    h = o.home_dashboard(d, {}, today=date(2026, 11, 20))
    c = h["close"]
    assert (c["received"], c["done"], c["pending"], c["after_cutoff"]) == (2, 1, 1, False)
    by = {w["key"]: w for w in c["wrong"]}
    assert by["reply"]["backlog"] == 1 and by["reply"]["oldest_days"] == 2
    assert by["po"]["backlog"] == 1 and by["bill"]["today"] == 1
    assert o.home_dashboard(d, {}, today=date(2026, 11, 20), now_hour=18)["close"]["after_cutoff"] is True


def test_cause_rows_have_only_the_relevant_columns():
    rows = [
        ["6", "20/11/2026", "", "Pending today", "WHATSAPP", "piyush", "", "BILL", "", "", "2"],
        ["7", "18/11/2026", "", "Silent old", "WHATSAPP", "asif", "", "", "", "", "3"],
        ["8", "17/11/2026", "", "PO stuck", "WHATSAPP", "asif", "", "PO", "", "", "1", "", "", "", "no fabric"],
    ]
    d = o.parse_orders([("NOV CREDIT SALE", NOV_CREDIT + rows)])
    r = o.cause_dashboard(d, "reply", today=date(2026, 11, 20))
    assert r["count"] == 1 and [c["label"] if isinstance(c, dict) else c for c in r["table"]["columns"]][0:1]
    cols = [c.get("label", c.get("key")) if isinstance(c, dict) else c for c in r["table"]["columns"]]
    assert "Client" in cols and "PO status" not in cols and "Bill status" not in cols
    p = o.cause_dashboard(d, "po", today=date(2026, 11, 20))
    assert p["count"] == 1 and "Reason" in [c.get("label", c.get("key")) if isinstance(c, dict) else c for c in p["table"]["columns"]]


def test_credit_order_paid_via_po_is_done_at_po_done_and_cause_filters_by_period():
    """Credit order where Mona said PO (the client pays): PO DONE means the order is done. Mona said BILL: still needs the bill."""
    rows = NOV_CREDIT + [
        ["7", "20/11/2026", "", "Pays via po", "WHATSAPP", "dev", "", "PO", "20/11/2026", "", "2", "", "", "DONE", "", "20/11/2026"],
        ["8", "20/11/2026", "", "Needs bill", "WHATSAPP", "dev", "", "BILL", "20/11/2026", "", "2", "", "", "DONE", "", "20/11/2026"],
        ["9", "20/11/2026", "", "No reply today", "WHATSAPP", "dev", "", "", "", "", "1"],
        ["10", "10/11/2026", "", "No reply old", "WHATSAPP", "dev", "", "", "", "", "1"]]
    d = o.parse_orders([("NOV CREDIT SALE", rows)])
    v = o.stage_view(d["orders"], date(2026, 11, 20)).set_index("client")
    assert v.loc["Pays via po", "stage"] == "done"
    assert v.loc["Needs bill", "stage"] == "bill"
    every = o.cause_dashboard(d, "reply", date(2026, 11, 20))
    today = o.cause_dashboard(d, "reply", date(2026, 11, 20), period="today")
    assert every["count"] == today["total"] > today["count"] == 1
    assert today["table"]["rows"][0][0] == "No reply today"

    mid = o.cause_dashboard(d, "reply", date(2026, 11, 20), period="month")
    assert mid["count"] == 1 and mid["table"]["rows"][0][0] == "No reply old"

    newest = o.cause_dashboard(d, "reply", date(2026, 11, 20), order="newest")["table"]["rows"]
    oldest = o.cause_dashboard(d, "reply", date(2026, 11, 20), order="oldest")["table"]["rows"]
    assert newest[0][0] == "No reply today" and oldest[0][0] == "No reply old"


def test_nov_credit_tab_with_blank_sr_and_date_headings_is_read():
    """NOV CREDIT SALE has blank headings over SR NO and the dates; the date column is the one before TIMESTAMP."""
    head = [" ", " ", "TIMESTAMP", "CLIENT NAME", "ORDER TYPE", "SALES PERSON", "LEDGER", "MONA REPLY", "03/08/2026"]
    grid = [head, ["609"], ["911", "21/11/2026", "", "Devana adipur", "WHATSAPP", "sameer", "", "BILL"],
            ["912", "21/11/2026", "", "Winmora", "WHATSAPP", "kamal"]]
    r = o.parse_orders([("NOV CREDIT SALE", grid)])
    assert r["issues"] == []
    assert list(r["orders"]["client"]) == ["Devana adipur", "Winmora"]
    assert list(r["orders"]["replied"]) == [True, False]
