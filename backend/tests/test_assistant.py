"""Flo-Wing Assistant on the demo CRM sheets: the rules, the glossary, the quick answers and the data tools."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    mp = pytest.MonkeyPatch()
    mp.setenv("DATA_SOURCE", "demo")
    mp.setenv("CHAT_LOG", "off")
    mp.setenv("GEMINI_API_KEY", "")
    mp.delenv("DASHBOARD_PASSCODE", raising=False)
    from app import main
    from app.config import get_settings
    get_settings.cache_clear()
    main.get_store.cache_clear()
    main.get_assistant.cache_clear()
    main.get_datatools.cache_clear()
    main.get_analyst.cache_clear()
    yield TestClient(main.app)
    mp.undo()
    get_settings.cache_clear()


def ask(client, q):
    r = client.post("/api/chat", json={"message": q})
    assert r.status_code == 200
    return r.json()


def kpi(client, path, label):
    return next(k["value"] for k in client.get(path).json()["kpis"] if k["label"] == label)


def test_health_reports_assistant_mode(client):
    assert client.get("/api/health").json()["assistant"] == "rules"


@pytest.mark.parametrize("q,path,label", [
    ("kitne orders late hai?", "/api/home", "Late"),
    ("Orders this month", "/api/home", "Orders this month"),
    ("orders today", "/api/home", "Orders today"),
    ("open orders", "/api/home", "Open orders"),
    ("total open enquiries", "/api/enquiries", "Total open"),
    ("enquiries not picked up yet", "/api/enquiries", "Not picked up yet"),
    ("pieces returned", "/api/returns", "Pieces returned"),
    ("open POs", "/api/po", "Open POs"),
])
def test_headline_figures_match_the_pages(client, q, path, label):
    out = ask(client, q)
    assert out["understood"] and out["engine"] == "rules"
    value = kpi(client, path, label)
    assert f"**{int(value)}**" in out["answer"]


def test_money_figure(client):
    out = ask(client, "pending payments")
    assert out["understood"] and "₹" in out["answer"] and out["page"] == "/payments"


def test_names_from_tables_are_understood(client):
    assert "**Mona**" in ask(client, "Mona ke paas kitne waiting hai")["answer"]
    assert "Piyush" in ask(client, "late orders of Piyush")["answer"]
    assert ask(client, "Kiran ke paas kitne pending hai")["page"] == "/payments"


def test_month_question_does_not_quote_today(client):
    assert "today" not in ask(client, "orders in October")["answer"].lower()


def test_ranking(client):
    out = ask(client, "top 5 clients by orders")
    assert out["understood"] and out["answer"].count("\n") >= 5


def test_glossary(client):
    assert ask(client, "GR kya hai")["engine"] == "glossary"
    assert "defect" in ask(client, "QC fail ka matlab")["answer"]


def test_quick_answers(client):
    assert ask(client, "what needs attention?")["answer"].startswith("**Today**")
    assert "Escalation" in ask(client, "L3 escalation kitne hai")["answer"]
    assert "On hold" in ask(client, "on hold orders")["answer"]


def test_chat_reset(client):
    assert client.post("/api/chat/reset", json={"session_id": "abc"}).json() == {"ok": True}


def test_data_tools_cover_every_sheet(client):
    from app.main import get_datatools
    t = get_datatools()
    assert set(t.tables()) == {"orders", "payments", "enquiries", "returns"}
    late = t.query("orders", filters=["status = late"], metrics=["count"])["result"]["count"]
    assert late == kpi(client, "/api/home", "Late")
    total = t.query("payments", filters=["status = pending"], metrics=["sum amount"])["result"]["sum_amount"]
    assert round(total) == round(kpi(client, "/api/payments", "Pending payments"))
    assert t.search("atipoorv")["matches"] > 0
