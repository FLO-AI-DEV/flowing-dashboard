from datetime import date

import pytest

from app import nudges as n
from app.dashboards import orders as o
from tests.test_orders_layout import NOV_CREDIT

ROWS = NOV_CREDIT + [
    ["7", "20/11/2026", "", "No reply today", "WHATSAPP", "dev", "", "", "", "", "3"],
    ["8", "20/11/2026", "", "Second today", "WHATSAPP", "dev", "", "", "", "", "1"],
    ["9", "15/11/2026", "", "No reply last week", "WHATSAPP", "dev", "", "", "", "", "2"],
    ["10", "05/11/2026", "", "No reply this month", "WHATSAPP", "dev", "", "", "", "", "4"],
    ["11", "01/09/2026", "", "No reply ancient", "WHATSAPP", "dev", "", "", "", "", "5"],
]


@pytest.fixture()
def view():
    n.reset_for_tests()
    d = o.parse_orders([("NOV CREDIT SALE", ROWS)])
    return o.stage_view(d["orders"], date(2026, 11, 20))


def test_staff_tab_is_read_by_heading():
    people = n.parse_staff([["WHATSAPP NUMBER", "CAUSES", "NAME"], ["+91 77288-17875", "reply", "Mona"], ["", "po", "No number"]])
    assert [(p.name, p.number, p.causes) for p in people] == [("Mona", "917728817875", {"reply"})]
    with pytest.raises(n.NudgeError):
        n.parse_staff([["NAME", "NUMBER"], ["Mona", "1"]])


def test_scopes_pick_separate_lists(view):
    clients = lambda scope, md=0: set(n.pick(view, "reply", scope, md)["client"])
    assert {"No reply today", "Second today"} <= clients("today") and "No reply last week" not in clients("today")
    assert clients("week") == {"No reply last week"}
    assert clients("month") == {"No reply this month"}
    assert clients("older") == {"No reply ancient"}                  # beyond 45 days still reachable
    assert {"No reply this month", "No reply ancient"} <= clients("custom", 10)
    assert "No reply last week" not in clients("custom", 10)


def test_message_lists_clients_and_caps_long_lists(view):
    box = n.TestOutbox()
    p = n.preview(box, view, "reply", "today")
    assert p["to"] == ["Mona"] and p["count"] >= 2 and "waiting for your reply" in p["message"]
    assert "No reply today (3 sets)" in p["message"] and "Please write BILL or PO" in p["message"]
    old = n.preview(box, view, "reply", "older")["message"]
    assert "No reply ancient (5 sets, " in old                       # older lists show how long each has waited


def test_send_writes_a_trigger_row_and_does_not_repeat(view):
    box = n.TestOutbox()
    out = n.send(box, view, "reply", "today")
    assert out["sent"] and len(box.rows) == 1
    created, name, number, message, status, kind, _ = box.rows[0]
    assert (name, number, status, kind) == ("Mona", "'910000000001", "", "DASHBOARD reply today")
    with pytest.raises(n.NudgeError, match="already sent"):
        n.send(box, view, "reply", "today")
    assert n.send(box, view, "reply", "today", force=True)["sent"] and len(box.rows) == 2
    n.send(box, view, "reply", "week")                                  # a different list is a different message
    assert len(box.rows) == 3


def test_nothing_to_send_or_nobody_to_send_to(view):
    box = n.TestOutbox()
    with pytest.raises(n.NudgeError, match="no orders"):
        n.send(box, view, "po", "today")
    with pytest.raises(n.NudgeError, match="Nobody"):
        n.send(box, view, "hold", "today")
    with pytest.raises(n.NudgeError):
        n.pick(view, "reply", "nonsense", 0)


def test_message_everyone_preview_and_send():
    from app import nudges
    from app.dashboards import payments as pm
    from tests.test_payments import HEAD, row
    nudges.reset_for_tests()
    d = pm.parse_payments([HEAD,
        row("10/11/2026 10:00:00", "Alpha", "FWSO-1/2627", 50000, "PIYUSH", "", "KIRAN"),
        row("08/11/2026 10:00:00", "Beta", "FWSO-2/2627", 20000, "PREETI", "", "LOKESH")], today="2026-11-20 15:00")
    box = nudges.TestOutbox()
    p = nudges.preview_all(box, d, "crm", "todo")
    assert {i["name"] for i in p["items"]} == {"Kiran", "Lokesh"} and p["ready"] == 2
    r = nudges.send_all(box, d, "crm", "todo")
    assert sorted(r["sent"]) == ["Kiran", "Lokesh"] and len(box.rows) == 2
    again = nudges.send_all(box, d, "crm", "todo")
    assert again["sent"] == [] and len(again["skipped_recent"]) == 2          # not twice within 30 minutes
    k = nudges.preview_all(box, d, "kavita", "escalated")
    assert k["items"][0]["count"] == 2 and "escalated to you" in k["items"][0]["message"]
