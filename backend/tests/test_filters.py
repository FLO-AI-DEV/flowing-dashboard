"""Shared filters (period, search, window, supplier type, amount), View-as roles and the Today page."""
import os

os.environ["DATA_SOURCE"] = "demo"
os.environ["CHAT_LOG"] = "off"
os.environ["WARM_UP"] = "off"

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import main
from app.dashboards import extra as ex

client = TestClient(main.app)
TODAY = pd.Timestamp("2026-11-21")


def get(path, **params):
    r = client.get(f"/api/{path}", params=params)
    assert r.status_code == 200, r.text[:300]
    return r.json()


def kpis(d):
    return {k["id"]: k["value"] for k in d.get("kpis", [])}


@pytest.mark.parametrize("period,start,end", [
    ("Today", "2026-11-21", "2026-11-21"), ("Yesterday", "2026-11-20", "2026-11-20"),
    ("Last 7 days", "2026-11-15", "2026-11-21"), ("This week", "2026-11-16", "2026-11-21"),
    ("This month", "2026-11-01", "2026-11-21"), ("Last month", "2026-10-01", "2026-10-31"),
    ("This quarter", "2026-10-01", "2026-11-21"), ("This FY", "2026-04-01", "2026-11-21"),
])
def test_period_presets(period, start, end):
    assert ex.period_range({"period": period}, TODAY) == (pd.Timestamp(start), pd.Timestamp(end))


def test_custom_period_and_all_dates():
    assert ex.period_range({"period": "Custom", "date_from": "2026-07-31", "date_to": "2026-07-01"}, TODAY) == \
        (pd.Timestamp("2026-07-01"), pd.Timestamp("2026-07-31"))
    assert ex.period_range({}, TODAY) is None


def test_orders_period_matches_month_filter():
    a = kpis(get("orders", period="Custom", date_from="2026-07-01", date_to="2026-07-31"))
    b = kpis(get("orders", month="July-26"))
    assert a["ordered"] == b["ordered"] and a["pending"] == b["pending"]
    assert get("orders", period="This month")["period_label"].endswith("2026")


def test_filters_narrow_and_add_up():
    total = kpis(get("orders"))["pending"]
    parts = [kpis(get("orders", amount=a)).get("pending", 0) for a in get("orders")["options"]["amount"]]
    assert sum(parts) == pytest.approx(total, abs=1)                     # amount bands split the total exactly
    msme = kpis(get("orders", supplier_type="MSME")).get("pending", 0)
    non = kpis(get("orders", supplier_type="Non-MSME")).get("pending", 0)
    assert msme + non == pytest.approx(total, abs=1)
    over = kpis(get("orders"))["overdue"]
    bands = [kpis(get("orders", window=w)).get("overdue", 0) for w in ex.OVERDUE]
    assert sum(bands) == pytest.approx(over, abs=1)                      # overdue windows split the overdue total


def test_search_filters_the_whole_page():
    d = get("orders", q="kesar")
    assert kpis(d)["pending"] == pytest.approx(kpis(get("orders", vendor="KESAR ETHNIC (JAIPUR)"))["pending"], abs=1)
    assert get("orders", q="zzqx nothing").get("empty")


def test_dues_windows_and_search():
    d = get("dues")
    assert kpis(get("dues", window="Due in next 7 days"))["total"] == pytest.approx(kpis(d)["due7"], abs=1)
    overdue = sum(kpis(get("dues", window=w)).get("total", 0) for w in ex.OVERDUE)
    assert overdue == pytest.approx(kpis(d)["overdue"], abs=1)
    assert kpis(get("dues", q="mm agency"))["total"] < kpis(d)["total"]


def test_otv_and_enquiry_filters():
    otv = get("order-to-vendors")
    assert "period" in otv["options"] and otv["detected"]["date"]
    assert kpis(get("order-to-vendors", q="pending"))["rows"] <= kpis(otv)["rows"]
    e = get("enquiries", window="Pending 90+ days")["sections"]["enquiries"]
    k = {x["id"]: x["value"] for x in e["kpis"]}
    assert k["enquiries"] == k["open"]                                   # only pending ones are in that window


def test_view_as_roles():
    acc = get("overview", role="Accounts")
    assert set(acc["sections"]) <= {"dues"} and all(a["area"] in ("dues", "none") for a in acc["alerts"])
    pur = get("overview", role="Purchase team")
    assert "dues" not in pur["sections"] and "enquiries" in pur["sections"]
    assert get("overview")["role"] == "Management"


def test_today_page():
    d = get("today")
    ids = [s["id"] for s in d["sections"]]
    assert {"orders", "dues", "enquiries"} <= set(ids)
    orders = next(s for s in d["sections"] if s["id"] == "orders")
    due_week = next(k["value"] for k in orders["kpis"] if k["id"] == "due_week")
    assert len(orders["tables"][0]["table"]["rows"]) == due_week
    assert [s["id"] for s in get("today", role="Accounts")["sections"]] == ["dues"]


def test_chat_today_summary_and_direct_calls_still_work():
    r = client.post("/api/chat", json={"message": "aaj kya hua"}).json()
    assert r["page"] == "/today" and "Orders and deliveries" in r["answer"]
    r = client.post("/api/chat", json={"message": "total pending"}).json()
    assert r["understood"] and "₹" in r["answer"]
