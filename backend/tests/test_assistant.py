"""Flo-Wing Assistant question bank (demo data). Run:  cd backend && python -m pytest tests -q

Each case is (question, words the answer must contain). Add the questions people really ask (see
backend/chat_questions.log, lines marked MISSED) and the words a correct answer contains, then fix the rules
(app/assistant/text.py, pages.py) until the whole bank passes.
"""
import os
from datetime import date, datetime

os.environ["DATA_SOURCE"] = "demo"
os.environ["GEMINI_API_KEY"] = ""
os.environ["CHAT_LOG"] = "off"

import pytest
from fastapi.testclient import TestClient

from app import main
from app.assistant import engine
from app.config import SHEET_REGISTRY, Settings
from app.sources.demo import DemoSheetSource, serial
from app.store import DataStore

client = TestClient(main.app)


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


def test_list_suppliers_with_less_overdue_returns_the_lowest_amounts_first():
    dashboard = {"tables": {"vendors": {
        "columns": [{"key": "Vendor", "label": "Vendor"}, {"key": "Overdue", "label": "Overdue", "format": "inr"}],
        "rows": [["SIXTH SUPPLIER", 900], ["THIRD SUPPLIER", 125], ["FIRST SUPPLIER", 0],
                 ["FIFTH SUPPLIER", 700], ["SECOND SUPPLIER", 25], ["FOURTH SUPPLIER", 400]],
    }}}
    assistant = engine.Assistant(lambda page, filters: dashboard if page == "orders" else {})

    for question in ("list to supplier who has less overdue", "list suppliers with lower overdue"):
        reply = assistant.answer(question)
        assert reply["understood"] and reply["intent"] == "rank" and reply["page"] == "/orders"
        assert reply["answer"].splitlines()[1:] == [
            "1. **FIRST SUPPLIER**: ₹0", "2. **SECOND SUPPLIER**: ₹25", "3. **THIRD SUPPLIER**: ₹125",
            "4. **FOURTH SUPPLIER**: ₹400", "5. **FIFTH SUPPLIER**: ₹700",
        ]

    assert "FIRST SUPPLIER" in assistant.answer("which supplier has less overdue")["answer"]
    assert "SIXTH SUPPLIER" in assistant.answer("which supplier has most overdue")["answer"]


@pytest.fixture
def factory_visit_suppliers(monkeypatch):
    source = DemoSheetSource()
    header = ["Date", "City", "Supplier Name", "Selection via", "Selected"]
    names = ["RARE", "ROOPRANG", "REGARDS", "SILAAI APPARELS", "DESIGNER COLLECTION", "MEERA ETHENIC"]
    visited_date = date(2026, 11, 12)
    source.sheets[SHEET_REGISTRY["order_to_vendors"]["id"]] = {
        "26-27": [header, ["12/11/2026", "Jaipur", "From catalogue", "Catalogue", "Yes"]],
        "25-26": [["Order to vendors"], header]
        + [["01/11/2026", "Jaipur", "Earlier supplier", "Factory Visited", "Yes"]] * 2000
        + [[serial(visited_date), "Jaipur", names[0], "Factory Visited", "Reworking"]]
        + [["12/11/2026", "Jaipur", name, "Factory Visited", "Yes"] for name in names[1:]]
        + [["13/11/2026", "Jaipur", "CIGNAL", "Factory Visited", "Yes"],
           ["23/11/2026", "Jaipur", "Today's supplier", "Factory Visited", "Yes"]],
        "Archive": [header, ["12/11/2026", "Jaipur", "rare", "Factory Visited", "Yes"]],
        "Summary": [["Summary"], ["Category", "Total"]],
    }
    store = DataStore(source, Settings())
    monkeypatch.setattr(main, "get_store", lambda: store)
    monkeypatch.setattr(engine, "today_ist", lambda: datetime(2026, 11, 23))

    def unexpected_analyst():
        pytest.fail("Factory visit lookups should be answered from the sheet rows")

    monkeypatch.setattr(main, "get_analyst", unexpected_analyst)
    return names


@pytest.mark.parametrize("question", [
    "list all of then who visited factory on date 12nov",
    "Which suppliers were marked Factory Visited on 12/11/2026?",
    "Explain who visited the factory on 2026-11-12",
    "List factory visits on Nov 12, 2026",
])
def test_factory_visit_lookup(question, factory_visit_suppliers):
    reply = ask(question)
    assert reply["understood"] and reply["intent"] == "factory_visits"
    assert reply["page"] == "/order-to-vendors"
    assert reply["context"]["date"] == "2026-11-12"
    assert "6 suppliers" in reply["answer"] and "12 November 2026" in reply["answer"]
    assert [line[2:] for line in reply["answer"].splitlines() if line.startswith("• ")] == factory_visit_suppliers


def test_factory_visit_lookup_handles_no_match_and_invalid_date(factory_visit_suppliers):
    missing = ask("Who visited factory on 14 Nov?")
    assert missing["understood"] and "no suppliers" in missing["answer"]
    invalid = ask("Who visited factory on 31 Nov?")
    assert invalid["intent"] == "factory_visits" and "Which date" in invalid["answer"]


def test_factory_visit_follows_up_on_a_new_date(factory_visit_suppliers):
    sid = "factory-visit-date-followup"
    first = client.post("/api/chat", json={"message": "Who visited factory on 12nov?", "session_id": sid}).json()
    assert first["understood"] and first["context"]["date"] == "2026-11-12"

    for question, day, name, context in (
        ("and today", "2026-11-23", "Today's supplier", first["context"]),
        ("and for 13nov?", "2026-11-13", "CIGNAL", None),
        ("aur aaj ke liye?", "2026-11-23", "Today's supplier", None),
    ):
        reply = client.post("/api/chat", json={"message": question, "session_id": sid, "context": context}).json()
        assert reply["understood"] and reply["intent"] == "factory_visits"
        assert reply["context"]["date"] == day
        assert [line[2:] for line in reply["answer"].splitlines() if line.startswith("• ")] == [name]


def test_factory_visit_resolves_today_on_a_standalone_question(factory_visit_suppliers):
    reply = ask("Who visited factory today?")
    assert reply["understood"] and reply["context"]["date"] == "2026-11-23"
    assert "Today's supplier" in reply["answer"]
    assert ask("weather today", reply["context"])["intent"] == "out_of_scope"


def test_factory_visit_yesterday_after_an_empty_result(factory_visit_suppliers, monkeypatch):
    monkeypatch.setattr(engine, "today_ist", lambda: datetime(2026, 11, 24))
    first = ask("Who visited factory on 12nov?")
    today = ask("today", first["context"])
    assert today["understood"] and "no suppliers" in today["answer"]
    yesterday = ask("yesterday", today["context"])
    assert yesterday["understood"] and yesterday["context"]["date"] == "2026-11-23"
    assert "Today's supplier" in yesterday["answer"]


def test_bare_date_asks_for_the_missing_subject_before_reading_data():
    def unexpected_fetch(*args):
        pytest.fail("A date without a subject should ask what to look up")

    reply = engine.Assistant(unexpected_fetch).answer("yesterday")
    assert reply["intent"] == "clarify" and "What should I look up for that date?" in reply["answer"]


def test_natural_question_can_use_a_measure_from_dashboard_labels():
    dashboard = {"kpis": [{"label": "Inspection fee", "format": "inr", "value": 1500}]}
    assistant = engine.Assistant(lambda page, filters: dashboard if page == "orders" else {})
    reply = assistant.answer("How much is the inspection fee?")
    assert reply["understood"] and "₹1,500" in reply["answer"]


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
