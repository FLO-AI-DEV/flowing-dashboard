"""Fabric filter, order-date / delivery-date choice and the date columns on Orders and Vendors."""
import os

os.environ["DATA_SOURCE"] = "demo"
os.environ["CHAT_LOG"] = "off"
os.environ["WARM_UP"] = "off"
os.environ["GEMINI_API_KEY"] = ""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import main
from app.dashboards import orders as o

client = TestClient(main.app)


def get(path, **params):
    r = client.get(f"/api/{path}", params=params)
    assert r.status_code == 200, r.text[:300]
    return r.json()


def kpi(d, kid):
    return next(k["value"] for k in d["kpis"] if k["id"] == kid)


def test_sheet_spellings_are_tidied_and_grouped():
    s = pd.Series(["Cotton", "silly cotton", "VISCOSE-SILK", "PURE VSICOSE CRAPE", "WOOLEN", "STRAIGHT", "", "-"])
    tags = list(o.fabric_tags(o.tidy_fabric(s)))
    assert tags == ["|Cotton|", "|Cotton|", "|Silk|Viscose|", "|Viscose|Crepe|", "|Wool|", "|Other fabric|",
                    "|(Fabric not filled in)|", "|(Fabric not filled in)|"]


def test_fabric_filter_and_table_agree():
    allp = get("orders")
    assert {"Cotton", "Wool"} <= set(allp["options"]["fabric"])
    cotton = get("orders", fabric="Cotton")
    assert 0 < kpi(cotton, "ordered") < kpi(allp, "ordered")
    rows = cotton["tables"]["lines"]["rows"]
    assert rows and all("COTTON" in str(r[2]) for r in rows)          # Fabric column of every listed line
    both = get("orders", fabric=["Cotton", "Wool"])
    assert kpi(both, "ordered") > kpi(cotton, "ordered")


def test_every_po_line_has_both_dates():
    t = get("orders")["tables"]["lines"]
    labels = [c["label"] for c in t["columns"]]
    assert {"Order Date", "Delivery Date", "Received Date"} <= set(labels)
    i, j = labels.index("Order Date"), labels.index("Delivery Date")
    assert all(r[i] and r[j] for r in t["rows"][:50])


def test_period_follows_the_chosen_date():
    by_order = get("orders", period="Last 30 days")
    by_delivery = get("orders", period="Last 30 days", date_by="Delivery date")
    assert by_order["options"]["date_by"] == ["Order date", "Delivery date"]
    assert kpi(by_order, "ordered") != kpi(by_delivery, "ordered")
    rows = by_delivery["tables"]["lines"]["rows"]
    labels = [c["label"] for c in by_delivery["tables"]["lines"]["columns"]]
    j = labels.index("Delivery Date")
    start = pd.Timestamp.today().normalize() - pd.Timedelta(days=60)
    assert rows and all(pd.to_datetime(r[j], dayfirst=True) >= start for r in rows)


def test_delivery_month_filter():
    d = get("orders")
    m = d["options"]["delivery_month"][0]
    one = get("orders", delivery_month=m)
    assert 0 < kpi(one, "ordered") < kpi(d, "ordered")


def test_vendor_scorecard_shows_order_and_delivery_dates():
    t = get("vendors", fabric="Cotton")["tables"]["scorecard"]
    labels = [c["label"] for c in t["columns"]]
    assert {"First Order", "Last Order", "Next Delivery Due", "Last Delivery Date"} <= set(labels)


@pytest.mark.parametrize("question,expect", [
    ("cotton pending", "Cotton"), ("silk ka pending kitna hai", "Silk"), ("fabric wise pending", "fabrics by Pending"),
    ("which fabric has most pending", "Cotton"),
])
def test_chatbot_knows_fabrics(question, expect):
    r = client.post("/api/chat", json={"message": question}).json()
    assert r["understood"] and expect in r["answer"], r["answer"]


@pytest.mark.parametrize("date_by,label", [("", "Order Month"), ("Delivery date", "Delivery Month")])
def test_status_by_order_or_delivery_month(date_by, label):
    d = get("orders", date_by=date_by)
    t = d["tables"]["status_by_date"]
    cols = [c["label"] for c in t["columns"]]
    assert cols[0] == label and {"On Time", "Delayed", "Overdue Lines", "Open (Within Deadline)"} <= set(cols)
    total = t["rows"][-1]
    assert total[0] == "TOTAL" and total[cols.index("Lines")] == sum(r[cols.index("Lines")] for r in t["rows"][:-1])
    status = sum(total[cols.index(c)] for c in ("On Time", "Delayed", "Overdue Lines", "Open (Within Deadline)", "No Date"))
    assert status <= total[cols.index("Lines")]                      # the rest are "Nil Order" lines
