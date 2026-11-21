"""Payment follow-up rules on rows laid out like the real 'New po sheet' (headings copied; clients invented)."""
import pandas as pd

from app.dashboards import payments as pm

HEAD = ["Column 1", "Column 2", "Column 3", "CONTACT NO", "AMOUNT", "Column 6", "PO SEND", "PAYMENT STATUS",
        "Column 9", "Column 10", "FOLLOW UP -2", "FOLLOW UP -3", "FOLLOW UP -4", "FOLLOW UP -5", "FOLLOW UP -6",
        "Column - 7", "Column 8", "Column 9", "Column 18", "Column 20"]
TODAY = "2026-11-20 15:00"


def row(ts, client, so, amount, sp, status, owner, *notes, owner2=None):
    r = [ts, client, so, "9999999999", str(amount), sp, "YES", status, owner, *notes]
    r += [""] * (19 - len(r))
    return r + [owner2 or owner]


BULK = [row(f"0{1 + i % 8}/11/2026 10:00:00", f"Bulk client {i}", f"FWSO-09{i:03d}/2627", 1000, "PIYUSH", "RECIEVED",
            "KIRAN", "Out of town .  —  13/11/2026 11:35:42 AM") for i in range(12)]


def parse(*rows):
    return pm.parse_payments([HEAD, *rows], today=TODAY)


def test_states_staleness_and_bulk_paste():
    d = parse(
        row("10/11/2026 10:00:00", "Alpha", "FWSO-1/2627", 50000, "PIYUSH", "", "KIRAN",
            "call not pickup  —  12/11/2026 11:00:00 AM", "msg drop  —  14/11/2026 02:00:00 PM",
            "Out of town .  —  13/11/2026 11:35:42 AM"),
        row("18/11/2026 10:00:00", "Beta", "FWSO-2/2627", 20000, "SAMEER", "", "LOKESH",
            "karenge payment  —  19/11/2026 04:00:00 PM"),
        row("05/11/2026 10:00:00", "Gamma", "FWSO-3/2627", 30000, "LUV", "RECIEVED", "SURYANSH",
            "payment done  —  07/11/2026 01:00:00 PM"),
        row("05/11/2026 10:00:00", "Delta", "FWSO-4/2627", 9000, "LUV", "CANCEL", "SURYANSH", "cancel  —  06/11/2026 10:00:00 AM"),
        row("15/11/2026 10:00:00", "Never called", "FWSO-5/2627", 7000, "PREETI", "", "KIRAN"),
        *BULK,
    )
    o = d["orders"].set_index("client")
    assert o.loc["Alpha", ["state", "follow_ups", "days_since_touch", "stale"]].tolist() == ["pending", 2, 6, True]
    assert o.loc["Beta", ["stale", "days_since_touch"]].tolist() == [False, 1]
    assert o.loc["Gamma", ["state", "collect_days"]].tolist() == ["received", 2]
    assert o.loc["Delta", "state"] == "cancelled"
    assert o.loc["Never called", ["stale", "follow_ups", "days_since_touch"]].tolist() == [True, 0, 5]
    assert "pasted onto many rows" in d["issues"][0]["text"]


def test_duplicate_so_latest_wins_and_old_year_dropped():
    d = parse(
        row("29/10/2026 10:00:00", "Dup", "FWSO-7/2627", 8825, "SAMEER", "", "KIRAN"),
        row("30/10/2026 10:21:07", "Dup", "FWSO-7/2627 ", 8825, "SAMEER", "RECIEVED", "KIRAN"),
        row("02/12/2025 10:01:29", "Last year", "SO-5355/25-26", 30203, "SAMEER", "", "KIRAN"),
    )
    o = d["orders"]
    assert o["client"].tolist() == ["Dup"] and o["state"].iloc[0] == "received"


def test_paid_note_but_status_blank_is_a_sheet_fix_not_a_follow_up_miss():
    d = parse(row("05/11/2026 10:00:00", "Paid", "FWSO-8/2627", 9660, "PIYUSH", "", "SURYANSH",
                  "payment done  —  10/11/2026 01:00:00 PM"))
    o = d["orders"].iloc[0]
    assert (o["state"], o["status_not_updated"], o["stale"]) == ("pending", True, False)
    a = pm.needs_action(d)[0]
    assert a["who"] == "Suryansh" and "not marked RECIEVED" in a["what"] and a["tone"] == "warn"


def test_dashboard_and_alerts():
    d = parse(
        row("10/11/2026 10:00:00", "Alpha", "FWSO-1/2627", 150000, "PIYUSH", "", "KIRAN",
            "call not pickup  —  12/11/2026 11:00:00 AM"),
        row("19/11/2026 10:00:00", "Beta", "FWSO-2/2627", 20000, "SAMEER", "", "LOKESH",
            "karenge payment  —  20/11/2026 11:00:00 AM"),
        row("01/11/2026 10:00:00", "Gamma", "FWSO-3/2627", 30000, "LUV", "RECIEVED", "LOKESH",
            "payment done  —  03/11/2026 01:00:00 PM"),
    )
    h = pm.payments_dashboard(d, {}, today=TODAY)
    k = {x["id"]: x for x in h["kpis"]}
    assert k["pending"]["value"] == 170000 and k["stale"]["value"] == 1 and k["collected"]["value"] == 30000
    cols = [c["label"] for c in h["members"]["columns"]]
    mem = {r[0]: dict(zip(cols, r)) for r in h["members"]["rows"]}
    assert mem["Lokesh"]["Followed up today"] == 1 and mem["Kiran"]["Not followed up"] == 1
    assert h["pending"]["rows"][0][0] == "Alpha" and h["pending"]["states"][0] == "late"
    msg = pm.alerts(d)[0]
    assert msg["to"] == "Kiran" and "Alpha (₹1.5 L, 8d)" in msg["text"]


def test_note_parsing():
    t, ts = pm.parse_note("call not pickup / msg drop   —  17/11/2026 04:42:12 PM")
    assert t == "call not pickup / msg drop" and ts == pd.Timestamp("2026-11-17 16:42:12")
    assert pm.parse_note("client cancel ke liye bol rahe hai")[1] is pd.NaT
    assert pm.parse_note("") is None
