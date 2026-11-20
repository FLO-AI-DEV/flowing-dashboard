"""Chat memory, calculator and the Gemini analyst (Google is replaced by a fake; no key or network needed)."""
import copy
import json
import os

os.environ["DATA_SOURCE"] = "demo"
os.environ["GEMINI_API_KEY"] = ""
os.environ["CHAT_LOG"] = "off"

import pytest
from fastapi.testclient import TestClient

from app import main
from app.assistant.analyst import GeminiAnalyst, build_facts, wants_analysis
from app.assistant.calc import CalcError, calculate
from app.assistant.memory import ChatMemory

client = TestClient(main.app)


# ------------------------------------------------------------------------------------------- calculator
@pytest.mark.parametrize("expr,expected", [
    ("2+3*4", 14), ("round(25.58/39.60*100, 1)", 64.6), ("1,23,456 - 456", 123000), ("25.58 Cr - 21.6 Cr", 39800000),
    ("12.5 L / 5", 250000), ("50% * 200", 100), ("max(3, 9, 4)", 9), ("abs(-7)", 7),
])
def test_calculate(expr, expected):
    assert calculate(expr) == pytest.approx(expected)


@pytest.mark.parametrize("expr", ["__import__('os')", "open('x')", "2**999", "1/0", "a+b", ""])
def test_calculate_rejects_unsafe_or_broken(expr):
    with pytest.raises(CalcError):
        calculate(expr)


# ------------------------------------------------------------------------------------------- memory
def test_memory_keeps_recent_turns_per_chat():
    m = ChatMemory(max_turns=2)
    m.add("a", "q1", "a1")
    m.add("a", "q2", "a2")
    m.add("a", "q3", "a3")
    m.add("b", "x", "y")
    assert m.history("a") == [("q2", "a2"), ("q3", "a3")]
    assert m.history("b") == [("x", "y")]
    m.clear("a")
    assert m.history("a") == []
    assert m.history(None) == []


def test_chat_endpoint_remembers_and_resets():
    sid = "testsession1"
    client.post("/api/chat", json={"message": "total pending", "session_id": sid})
    assert len(main.CHAT_MEMORY.history(sid)) == 1
    client.post("/api/chat/reset", json={"session_id": sid})
    assert main.CHAT_MEMORY.history(sid) == []


# ------------------------------------------------------------------------------------------- analyst
def test_wants_analysis():
    assert wants_analysis("pending kitna percent hai ordered ka")
    assert wants_analysis("difference between ordered and received")
    assert wants_analysis("average pending per vendor")
    assert not wants_analysis("total pending")


def test_facts_are_compact_and_follow_names():
    facts, page = build_facts(main.get_assistant(), "Kesar Ethnic ka pending percent", "November-26")
    assert "Orders page (filtered" in facts and "KESAR ETHNIC" in facts
    assert len(facts) < 10000


class _Resp:
    status_code = 200

    def __init__(self, content):
        self._c = content

    def json(self):
        return {"candidates": [{"content": self._c}]}


class FakeGemini:
    """First asks the calculator, then answers with the result it got back."""

    def __init__(self):
        self.bodies = []

    def post(self, url, json=None, timeout=None, headers=None):
        self.bodies.append(copy.deepcopy(json))
        last = json["contents"][-1]["parts"][0]
        if "functionResponse" in last:
            r = last["functionResponse"]["response"]["result"]
            return _Resp({"role": "model", "parts": [{"text": f"Pending is **{r:.1f}%** of ordered."}]})
        return _Resp({"role": "model", "parts": [{"functionCall": {"name": "calculate",
                                                                   "args": {"expression": "round(1304325/3541335*100, 1)"}}}]})


def test_analyst_uses_calculator_and_history(monkeypatch):
    fake = FakeGemini()
    analyst = GeminiAnalyst("test-key", session=fake)
    main.get_analyst.cache_clear()
    monkeypatch.setattr(main, "get_analyst", lambda: analyst)
    sid = "calcsession"
    client.post("/api/chat", json={"message": "total pending", "session_id": sid})
    r = client.post("/api/chat", json={"message": "pending kitna percent hai ordered ka", "session_id": sid}).json()
    assert r["engine"] == "gemini" and "36.8%" in r["answer"]
    first = fake.bodies[0]
    assert first["generationConfig"]["maxOutputTokens"] <= 400            # small, cheap answers
    assert first["contents"][0]["parts"][0]["text"] == "total pending"     # earlier turn of this chat is sent
    assert "FACTS:" in first["contents"][-1]["parts"][0]["text"]
    assert client.get("/api/health").json()["assistant"].startswith("rules + gemini analyst")
    json.dumps(r)


def test_without_key_rules_still_answer():
    main.get_analyst.cache_clear()
    r = client.post("/api/chat", json={"message": "pending kitna percent hai ordered ka"}).json()
    assert r["engine"] == "rules"
