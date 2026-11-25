"""Only the rows of the chosen time window are read from the PO log (demo source stands in for Google)."""
import os

os.environ["DATA_SOURCE"] = "demo"
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

c = TestClient(app)


def test_window_reads_fewer_rows_for_shorter_windows():
    a = c.get("/api/po", params={"window": "30d"}).json()["window"]
    b = c.get("/api/po", params={"window": "fy"}).json()["window"]
    assert a["rows"] < b["rows"] <= b["log_rows"]
    assert a["label"] == "Last 30 days"


def test_person_and_nudge_for_a_caller():
    o = c.get("/api/po").json()
    name = o["people"]["crm"][0]["name"]
    p = c.get("/api/po/person", params={"role": "crm", "name": name}).json()
    assert p["name"] == name and p["table"]["rows"]
    pv = c.post("/api/nudge/preview", json={"cause": "payment", "scope": "all", "group": f"crm:{name}"}).json()
    assert pv["to"] == [name] and name in pv["message"]
    assert c.get("/api/po/person", params={"role": "crm", "name": "nobody"}).status_code == 404


def test_older_open_pos_are_kept_for_short_windows():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    short = c.get("/api/po", params={"window": "30d"}).json()
    full = c.get("/api/po", params={"window": "fy"}).json()
    assert short["window"]["older_open"] > 0
    assert short["kpis"][0]["value"] == full["kpis"][0]["value"]          # same open POs, whatever the window
    older = c.get("/api/po", params={"window": "30d", "range": "older"}).json()
    assert older["kpis"][0]["value"] == next(p["count"] for p in full["periods"] if p["key"] == "older")
