"""Every endpoint answers on demo data, and the JSON has the shape the frontend expects."""
import os

os.environ["DATA_SOURCE"] = "demo"
os.environ["GEMINI_API_KEY"] = ""
os.environ["CHAT_LOG"] = "off"

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    h = client.get("/api/health").json()
    assert h["ok"] and h["source"] == "demo" and h["assistant"] == "rules"


@pytest.mark.parametrize("path,keys", [
    ("/api/overview", {"meta", "alerts", "sections", "options"}),
    ("/api/orders", {"meta", "kpis", "tables", "charts", "options", "summary"}),
    ("/api/orders?month=June-26&vendor=KESAR%20ETHNIC%20(JAIPUR)", {"kpis", "tables"}),
    ("/api/vendors", {"kpis", "tables", "charts", "summary"}),
    ("/api/dues", {"kpis", "tables", "charts", "tab", "tabs"}),
    ("/api/order-to-vendors", {"kpis", "tables", "charts", "tab", "tabs"}),
    ("/api/sheets", {"sheets"}),
    ("/api/sheet?source=order_status&q=jaipur", {"table", "total", "header_row"}),
    ("/api/status", {"sources"}),
])
def test_endpoints(path, keys):
    r = client.get(path)
    assert r.status_code == 200, r.text
    assert keys <= set(r.json())


def test_kpis_add_up():
    d = client.get("/api/orders").json()
    k = {x["id"]: x["value"] for x in d["kpis"]}
    assert k["pending"] == pytest.approx(k["ordered"] - k["received"], rel=0.01)
    totals = d["tables"]["vendors"]["rows"][-1]
    assert totals[0] == "TOTAL"


def test_bad_input_is_rejected():
    assert client.get("/api/sheet?source=nope").status_code == 404
    assert client.get("/api/dues?tab=No%20Such%20Tab").status_code == 503
    assert client.post("/api/chat", json={"message": ""}).status_code == 422
    assert client.post("/api/chat", json={"message": "hi", "session_id": "bad id!"}).status_code == 422
