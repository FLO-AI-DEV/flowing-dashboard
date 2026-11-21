"""Every endpoint answers on the demo order sheet (laid out like the real one)."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(monkeypatch_module):
    from app import main
    main.get_store.cache_clear()
    return TestClient(main.app)


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    mp.setenv("DATA_SOURCE", "demo")
    mp.delenv("DASHBOARD_PASSCODE", raising=False)
    from app.config import get_settings
    get_settings.cache_clear()
    yield mp
    mp.undo()
    get_settings.cache_clear()


def test_health(client):
    assert client.get("/api/health").json()["source"] == "demo"


def test_status_reads_only_order_tabs(client):
    s = client.get("/api/status").json()["sources"]["orders"]
    assert s["ok"] and len(s["tabs"]) == 6
    assert not any("full payment" in t.lower() for t in s["tabs"])


def test_home(client):
    h = client.get("/api/home").json()
    assert [k["id"] for k in h["kpis"]] == ["today", "month", "open", "late"]
    assert h["kpis"][1]["value"] > 0
    assert [p["key"] for p in h["pipeline"]] == ["reply", "po", "bill", "hold", "old", "done"]
    assert {a["who"] for a in h["actions"]} >= {"Mona", "PO team", "Billing team"}
    assert h["notices"] == []


def test_orders_team_clients_alerts(client):
    o = client.get("/api/orders").json()
    assert o["table"]["columns"][0]["label"] == "Client"
    assert all(s != "done" for s in o["table"]["states"])
    late = client.get("/api/orders", params={"late_only": "true"}).json()
    assert all(s == "late" for s in late["table"]["states"])
    t = client.get("/api/team").json()
    assert t["sales"]["rows"] and [r[0] for r in t["owners"]["rows"]] == ["Mona", "PO team", "Billing team"]
    c = client.get("/api/clients").json()
    assert c["table"]["rows"]
    a = client.get("/api/alerts").json()
    assert a["owner"].startswith("Good morning")


def test_filters(client):
    h = client.get("/api/home", params={"channel": "Mumbai"}).json()
    allh = client.get("/api/home").json()
    assert h["kpis"][1]["value"] < allh["kpis"][1]["value"]


def test_payments_endpoint_and_today_merge(client):
    p = client.get("/api/payments").json()
    assert [k["id"] for k in p["kpis"]] == ["pending", "stale", "collected", "cancelled"]
    assert {r[0] for r in p["members"]["rows"]} == {"Kiran", "Suryansh", "Lokesh"}
    h = client.get("/api/home").json()
    assert any(a["stage"] == "Payments" for a in h["actions"])
    assert len(client.get("/api/status").json()["sources"]) == 2


def test_nudge_endpoints_on_demo_data(client):
    from app import nudges
    nudges.reset_for_tests()
    who = client.get("/api/nudge/who").json()
    assert who["enabled"] and who["test_mode"] and who["who"]["reply"] == ["Mona"]
    pv = client.post("/api/nudge/preview", json={"cause": "reply", "scope": "week"})
    assert pv.status_code in (200, 400)          # demo orders may have none in this period: a clear message, never a crash
    bad = client.post("/api/nudge/preview", json={"cause": "reply", "scope": "nonsense"})
    assert bad.status_code == 400
