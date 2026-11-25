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


# ------------------------------------------------------------------------------ PO follow-up (clock, views, window)
def row2(ts, client, so, amount, sp, status, owner, *notes, po_send="YES"):
    r = row(ts, client, so, amount, sp, status, owner, *notes)
    r[6] = po_send
    return r


def test_clock_starts_at_po_share_note_and_buckets():
    d = parse(
        # order 15 Nov, PO shared 17 Nov -> day 3 on 20 Nov (on track), not day 5
        row2("15/11/2026 10:00:00", "Late share", "FWSO-11/2627", 10000, "PIYUSH", "", "KIRAN",
             "po shared  —  17/11/2026 11:00:00 AM"),
        row2("13/11/2026 10:00:00", "Due soon", "FWSO-12/2627", 20000, "PIYUSH", "", "KIRAN"),
        row2("11/11/2026 10:00:00", "Overdue", "FWSO-13/2627", 30000, "SAMEER", "", "LOKESH"),
        row2("05/11/2026 10:00:00", "Past limit", "FWSO-14/2627", 40000, "SAMEER", "", "LOKESH"),
        row2("20/11/2026 10:00:00", "Not sent", "FWSO-15/2627", 5000, "LUV", "", "KIRAN", po_send=""),
    )
    o = d["orders"].set_index("client")
    assert o["days_out"].to_dict() == {"Late share": 3, "Due soon": 7, "Overdue": 9, "Past limit": 15, "Not sent": 0}
    assert o["bucket"].to_dict() == {"Late share": "on_track", "Due soon": "due_soon", "Overdue": "overdue",
                                     "Past limit": "past_limit", "Not sent": "on_track"}


def test_person_view_today_list_and_overview():
    d = parse(
        row2("05/11/2026 10:00:00", "Past limit", "FWSO-14/2627", 40000, "SAMEER", "", "KIRAN"),
        row2("13/11/2026 10:00:00", "Done today", "FWSO-12/2627", 20000, "SAMEER", "", "KIRAN",
             "msg drop  —  20/11/2026 09:00:00 AM"),
        row2("13/11/2026 10:00:00", "Paid", "FWSO-16/2627", 8000, "PIYUSH", "RECIEVED", "KIRAN",
             "payment done  —  20/11/2026 09:30:00 AM"),
    )
    d["window"] = {"key": "60d", "label": "Last 60 days"}
    p = pm.person_dashboard(d, "crm", "kiran", today=pd.Timestamp(TODAY))
    assert p["todo"] == 1 and p["count"] == 2
    assert p["table"]["rows"][0][0] == "Past limit" and "past the 10-day limit" in p["table"]["rows"][0][[c["key"] for c in p["table"]["columns"]].index("What to do")]
    assert p["table"]["done"] == [False, True]
    o = pm.po_overview(d, today=pd.Timestamp(TODAY))
    kp = {k["id"]: k["value"] for k in o["kpis"]}
    assert kp["open"] == 2 and kp["past"] == 1 and kp["paid_today"] == 1
    sp = {r[0]: r for r in o["sales"]["rows"]}
    assert sp["Sameer"][2] == 2 and sp["Piyush"][2] == 0


def test_nudge_rows_scopes():
    d = parse(row2("05/11/2026 10:00:00", "Past limit", "FWSO-14/2627", 40000, "SAMEER", "", "KIRAN"),
              row2("14/11/2026 10:00:00", "Soon", "FWSO-12/2627", 20000, "SAMEER", "", "KIRAN"))
    assert pm.nudge_rows(d, "sp:Sameer", "overdue")["client"].tolist() == ["Past limit"]
    assert pm.nudge_rows(d, "crm:kiran", "due")["client"].tolist() == ["Soon"]
    assert len(pm.nudge_rows(d, "crm:Kiran", "all")) == 2


def test_duplicate_so_is_reported_and_counted_once():
    d = parse(
        row2("10/11/2026 10:00:00", "Alpha", "FWSO-77/2627", 10000, "PIYUSH", "", "KIRAN"),
        row2("11/11/2026 10:00:00", "Alpha", "FWSO-77/2627", 10000, "PIYUSH", "", "KIRAN"),
        row2("12/11/2026 10:00:00", "Beta", "FWSO-78/2627", 5000, "PIYUSH", "", "KIRAN"),
    )
    assert len(d["orders"]) == 2
    assert any("1 SO number(s) appear on more than one row" in n["text"] and "FWSO-77/2627" in n["text"] for n in d["issues"])


def test_calls_promised_date_and_part_payment_columns_are_optional_and_used():
    import pandas as pd
    from app.dashboards import payments as pays
    t = pd.Timestamp("2026-11-24")
    hdr = ["COLUMN 1", "COLUMN 2", "COLUMN 3", "AMOUNT", "COLUMN 6", "PO SEND", "PAYMENT STATUS", "COLUMN 9",
           "n1", "n2", "COLUMN 20", "PROMISED DATE", "PART PAYMENT RECEIVED"]
    def row(so, promised="", part=""):
        return ["10/11/2026", "Client " + so, so, 100000, "Piyush", "YES", "", "Kiran",
                "po shared  —  10/11/2026 10:00:00 AM", "called, will pay  —  12/11/2026 12:00:00 PM", "", promised, part]
    grid = [hdr, row("FWSO-1"), row("FWSO-2", promised="30/11/2026"), row("FWSO-3", promised="20/11/2026"), row("FWSO-4", part="40000")]
    d = pays.parse_payments(grid, today=t)["orders"].set_index("so")
    assert d.loc["FWSO-1", "calls"] == 1
    assert d.loc["FWSO-1", "todo"] and not d.loc["FWSO-2", "todo"]       # promise still ahead: wait
    assert d.loc["FWSO-3", "promise_broken"] and d.loc["FWSO-3", "todo"]
    assert d.loc["FWSO-4", "held"] and d.loc["FWSO-4", "part_paid_n"] == 40000


def test_person_report_numbers_agree_with_overview():
    d = parse(
        row2("05/11/2026 10:00:00", "Past limit", "FWSO-14/2627", 40000, "SAMEER", "", "KIRAN"),
        row2("11/11/2026 10:00:00", "Overdue", "FWSO-13/2627", 30000, "SAMEER", "", "LOKESH"),
        row2("13/11/2026 10:00:00", "Paid", "FWSO-16/2627", 30000, "SAMEER", "RECIEVED", "KIRAN",
             "payment done  —  20/11/2026 09:30:00 AM"),
    )
    r = pm.person_report(d, "sp", "sameer", today=pd.Timestamp(TODAY))
    assert r["open"] == {"count": 2, "amount": 70000.0}
    assert r["late"]["count"] == 2 and r["paid_pct"] == 30
    assert [a["label"] for a in r["ages"]] == ["0–4 days", "5–7 days", "8–10 days", "11+ days"]
    assert sum(a["count"] for a in r["ages"]) == r["open"]["count"]
    assert r["worst"][0]["client"] == "Past limit" and {x["name"] for x in r["split"]} == {"Kiran", "Lokesh"}
