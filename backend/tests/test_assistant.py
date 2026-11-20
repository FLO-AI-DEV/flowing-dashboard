"""Flo-Wing Assistant question bank (demo data). Run:  cd backend && python -m pytest tests -q

Each case is (question, words the answer must contain). Add the questions people really ask (see
backend/chat_questions.log, lines marked MISSED) and the words a correct answer contains, then fix the rules
(app/assistant/text.py, pages.py) until the whole bank passes.
"""
import os

os.environ["DATA_SOURCE"] = "demo"
os.environ["GEMINI_API_KEY"] = ""
os.environ["CHAT_LOG"] = "off"

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def ask(q, ctx=None):
    return client.post("/api/chat", json={"message": q, "context": ctx}).json()


CASES = [
    # orders: value
    ("total pending", "Pending is"),
    ("total ordered value batao", "Ordered is"),
    ("order ki value kitni hai", "Ordered is"),
    ("kitna maal aana baki hai", "Pending qty"),
    ("pending pcs", "Pending qty"),
    ("received pcs", "Received qty"),
    ("kitna aaya", "Received"),
    ("overdue kitna hai", "Overdue is"),
    ("kitne PO overdue hai", "Overdue POs"),
    ("order qty", "Order qty"),
    ("on time delivery kitni hai", "On-time delivery"),
    ("time pe delivery kitni hui", "On-time"),
    # orders: months
    ("received in June", "June-26"),
    ("ordered last month", "October-26"),
    ("pending month wise", "month by month"),
    ("compare June vs July ordered", "July-26"),
    # rankings
    ("top 5 vendors by pending", "Top 5 vendors"),
    ("sabse zyada pending kis vendor ke paas hai", "highest Pending"),
    ("kis party ka sabse zyada maal aana baki hai", "Pending Pcs"),
    ("which vendor has most overdue", "highest Overdue"),
    ("on-time rate of vendors", "On-Time %"),
    ("best vendor", "On-Time %"),
    ("worst vendor", "lowest On-Time %"),
    ("category wise pending", "categories by Pending"),
    ("department wise ordered", "departments by Ordered"),
    ("which agency has most dues", "agency with the highest"),
    # names
    ("Kesar Ethnic ka pending kitna hai", "KESAR ETHNIC"),
    ("Jaipur pending", "JAIPUR"),
    ("PREMIUM department received", "PREMIUM"),
    ("dues of Mahavir Creations", "MAHAVIR CREATIONS"),
    # dues
    ("total dues", "Total net payable"),
    ("kitna payment karna hai", "Total net payable"),
    ("payment due this week", "Due in next 7 days"),
    ("is hafte kitna dena hai", "Due in next 7 days"),
    ("dues overdue", "Overdue"),
    # POs
    ("status of po 12", "FWPO-00012/2627"),
    ("FWPO-00098/2627", "FWPO-00098/2627"),
    # order to vendors
    ("total amount in order to vendors", "Total amount"),
    ("rows in order to vendors", "Rows is"),
    # lists, help, pages
    ("how many vendors", "vendors on the dashboard"),
    ("list cities", "cities"),
    ("how do I download", "CSV"),
    ("what does the dues page show", "Supplier dues"),
    ("hi", "Flo-Wing Assistant"),
    ("pending in one word", "**₹"),
]


@pytest.mark.parametrize("question,expected", CASES)
def test_question(question, expected):
    r = ask(question)
    assert r["understood"], f"not understood: {question!r} -> {r['answer'][:120]!r}"
    assert expected.lower() in r["answer"].lower(), f"{question!r} -> {r['answer'][:160]!r}"


FOLLOW_UPS = [
    (["order qty", "paise me bata"], "Ordered is"),
    (["total ordered value batao", "pcs me batao"], "Order qty"),
    (["Kesar Ethnic ka pending kitna hai", "and received?"], "Received for **KESAR ETHNIC"),
    (["total pending", "and for June?"], "June-26"),
]


@pytest.mark.parametrize("chain,expected", FOLLOW_UPS)
def test_follow_up(chain, expected):
    ctx = None
    for q in chain:
        r = ask(q, ctx)
        ctx = r.get("context")
    assert expected.lower() in r["answer"].lower(), f"{chain!r} -> {r['answer'][:160]!r}"


def test_gemini_is_optional():
    assert client.get("/api/health").json()["assistant"] == "rules"


class _FakeResponse:
    status_code = 200

    def __init__(self, hint):
        self._hint = hint

    def json(self):
        import json
        return {"candidates": [{"content": {"parts": [{"text": json.dumps(self._hint)}]}}]}


class _FakeSession:
    """Stands in for Google: checks the prompt never carries figures, returns a fixed reading."""

    def __init__(self, hint):
        self.hint, self.prompts = hint, []

    def post(self, url, json=None, timeout=None, headers=None):
        self.prompts.append(json["contents"][0]["parts"][0]["text"])
        return _FakeResponse(self.hint)


def test_gemini_fallback_maps_question_to_a_label():
    from app.assistant.gemini import GeminiInterpreter
    from app.main import get_assistant
    a = get_assistant()
    fake = _FakeSession({"intent": "value", "metric": "Due in next 7 days", "page": "dues", "names": [], "months": []})
    old = a.interpreter
    a.interpreter = GeminiInterpreter("test-key", session=fake)
    try:
        r = ask("agle saat din mein suppliers ko kitna chukana padega")
    finally:
        a.interpreter = old
    assert r["understood"] and "Due in next 7 days" in r["answer"], r["answer"]
    assert r["engine"] == "gemini"
    assert fake.prompts and "₹" not in fake.prompts[0]          # labels only, no figures sent
