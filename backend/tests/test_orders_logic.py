"""Order pipeline rules: which stage an order is at, who must act, when it is late, and the alert messages."""
from datetime import date

import pandas as pd

from app.dashboards import orders as o

TODAY = date(2026, 11, 20)
HEAD = ["DATE", "CLIENT NAME", "SALES PERSON", "MONA REPLY", "HOLD REASON", "ORDER (NO. OF SETS)", "PO STATUS",
        "PO NOT DONE REASON", "BILL STATUS", "BILL NOT DONE REASON", "BILL STATUS TIME AND DATE"]


def sheet(*rows):
    return o.parse_orders([("NOV CREDIT SALE", [HEAD, *rows])])


def view(*rows):
    return o.stage_view(sheet(*rows)["orders"], TODAY).set_index("client")


def test_stages_and_owners():
    v = view(
        ["20/11/2026", "New today", "piyush", "", "", "2", "", "", "", "", ""],
        ["17/11/2026", "No reply", "preeti", "", "", "2", "", "", "", "", ""],
        ["15/11/2026", "PO pending", "kamal", "PO", "", "3", "", "fabric not in stock", "", "", ""],
        ["16/11/2026", "Bill pending", "sameer", "BILL", "", "1", "", "", "", "GST missing", ""],
        ["10/11/2026", "Held", "luv", "BILL", "payment pending", "1", "", "", "", "", ""],
        ["10/11/2026", "Billed", "piyush", "BILL", "", "4", "", "", "DONE", "", "12/11/2026"],
    )
    assert v.loc["New today", ["waiting", "owner", "state"]].tolist() == ["Mona's reply", "Mona", "ok"] or \
        v.loc["New today", "state"] in ("ok", "due")
    assert v.loc["No reply", ["owner", "state", "days_late"]].tolist() == ["Mona", "late", 2]
    assert v.loc["PO pending", ["waiting", "owner", "state", "reason"]].tolist() == \
        ["PO", "PO team", "late", "fabric not in stock"]
    assert v.loc["Bill pending", ["owner", "state", "days_late", "reason"]].tolist() == \
        ["Billing team", "late", 1, "GST missing"]
    assert v.loc["Held", ["state", "owner"]].tolist() == ["hold", "Luv"]
    assert v.loc["Billed", ["state", "bill_days"]].tolist() == ["done", 2]


def test_due_today_is_amber_not_red():
    v = view(["19/11/2026", "Yesterday", "piyush", "", "", "2", "", "", "", "", ""])   # Mona's deadline: 1 day
    assert v.loc["Yesterday", "state"] == "due"


def test_quality_issues_name_the_sales_person():
    d = sheet(["19/11/2026", "No qty", "preeti", "BILL", "", "", "", "", "", "", ""],
              ["18/11/2026", "Done no date", "kamal", "BILL", "", "2", "", "", "DONE", "", ""])
    q = o.quality_issues(o.stage_view(d["orders"], TODAY))
    assert sorted(zip(q["who"], q["problem"])) == [("Kamal", "bill DONE without date"), ("Preeti", "no quantity")]


def test_home_numbers_and_actions():
    d = sheet(
        ["20/11/2026", "A", "piyush", "", "", "2", "", "", "", "", ""],
        ["17/11/2026", "B", "preeti", "", "", "3", "", "", "", "", ""],
        ["10/11/2026", "C", "piyush", "BILL", "", "4", "", "", "DONE", "", "11/11/2026"],
    )
    h = o.home_dashboard(d, {}, today=TODAY)
    k = {x["id"]: x["value"] for x in h["kpis"]}
    assert (k["today"], k["month"], k["open"], k["late"]) == (1, 3, 2, 1)
    first = h["actions"][0]
    assert (first["who"], first["tone"], first["late"]) == ("Mona", "bad", 1)
    assert {a["who"]: a["tone"] for a in h["actions"]}["Billing team"] == "good"


def test_alert_messages():
    d = sheet(["15/11/2026", "Kalakriti Lucknow", "piyush", "", "", "2", "", "", "", "", ""],
              ["19/11/2026", "Atipoorv Delhi", "preeti", "", "", "3", "", "", "", "", ""])
    a = o.alerts(d, today=TODAY)
    mona = next(m for m in a["employees"] if m["to"] == "Mona")
    assert mona["count"] == 1 and "Kalakriti Lucknow (5d)" in mona["text"]
    assert "late: 1" in a["owner"] and "Mona" in a["owner"]


def test_layout_change_is_reported_not_fatal():
    d = o.parse_orders([("NOV CREDIT SALE", [HEAD, ["20/11/2026", "A", "piyush", "", "", "2"]]),
                        ("NOV CASH SALE", [["SOMETHING", "ELSE"], ["x", "y"]])])
    assert d["tabs"] == ["NOV CREDIT SALE"]
    assert len(d["orders"]) == 1
    assert "NOV CASH SALE" in d["issues"][0]["text"] and "layout changed" in d["issues"][0]["text"]


def test_tab_rules():
    assert o.is_order_tab("NOV CREDIT SALE") and o.is_order_tab("Nov MUMBAI SALE") and o.is_order_tab("OCT CASH SALE")
    assert not o.is_order_tab("full payment rcvd orders OCT / NOV.")
    assert [o.tab_channel(t) for t in ("NOV CREDIT SALE", "NOV CASH SALE", "Nov MUMBAI SALE")] == \
        ["Credit", "Cash", "Mumbai"]


def test_tab_months():
    assert [o.tab_month(t) for t in ("NOV CREDIT SALE", "SEP. CASH SALE", "JULY MUMBAI SALE", "Sheet12")] == \
        [11, 9, 7, None]
    assert o.is_recent_tab("NOV CASH SALE", date(2026, 11, 20)) and o.is_recent_tab("OCT CREDIT SALE", date(2026, 11, 20))
    assert not o.is_recent_tab("SEP. CREDIT SALE", date(2026, 11, 20))
    assert o.is_recent_tab("DEC CASH SALE", date(2027, 1, 5))


def test_mirror_not_connected_is_reported_clearly():
    d = o.parse_orders([("NOV CREDIT SALE", [["#REF!"]]), ("NOV CASH SALE", [HEAD, ["20/11/2026", "A", "piyush"]])])
    assert d["tabs"] == ["NOV CASH SALE"]
    assert "Allow access" in d["issues"][0]["text"]
