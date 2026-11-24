"""The chatbot's data tools, glossary, figure check, answer cache and Gemini tool use (Gemini is faked; no network)."""
import copy
import os

os.environ["DATA_SOURCE"] = "demo"
os.environ["GEMINI_API_KEY"] = ""
os.environ["CHAT_LOG"] = "off"
os.environ["WARM_UP"] = "off"

import pytest
from fastapi.testclient import TestClient

from app import main
from app.assistant import glossary
from app.assistant.analyst import GeminiAnalyst, ungrounded
from app.assistant.datatools import ToolError

client = TestClient(main.app)
tools = main.get_datatools()


def kpi(page: str, kid: str, **params):
    data = client.get(f"/api/{page}", params=params).json()
    found = []

    def walk(x):
        if isinstance(x, dict):
            if x.get("id") == kid and "value" in x and "label" in x:
                found.append(x["value"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(data)
    assert found, f"no KPI {kid} on {page}"
    return found[0]


# ------------------------------------------------------------------------------- tools agree with the pages
def test_tables_cover_every_sheet():
    t = tools.tables()
    assert {"po_lines", "supplier_bills", "vendor_orders", "enquiries", "po_by_city", "terms_approval",
            "inactive_suppliers"} <= set(t)


def test_query_totals_match_page_kpis():
    r = tools.query("po_lines", metrics=["sum pending_amt", "sum order_amt", "sum overdue_amt"])["result"]
    assert r["sum_pending_amt"] == pytest.approx(kpi("orders", "pending"), abs=1)
    assert r["sum_order_amt"] == pytest.approx(kpi("orders", "ordered"), abs=1)
    assert r["sum_overdue_amt"] == pytest.approx(kpi("orders", "overdue"), abs=1)
    bills = tools.query("supplier_bills", metrics=["sum net_payable"])["result"]["sum_net_payable"]
    assert bills == pytest.approx(kpi("dues", "total"), abs=1)
    open_ = tools.query("enquiries", ["status != Solved"], metrics=["count"])["result"]["count"]
    assert open_ == kpi("enquiries", "open")
    wait = tools.query("po_by_city", ["po_status = Waiting for PO"], metrics=["count"])["result"]["count"]
    assert wait == kpi("enquiries", "po_pending")


def test_query_filters_groups_and_rows():
    one = tools.query("po_lines", ["vendor contains kesar"], metrics=["sum pending_amt"])
    assert one["rows_matched"] > 0 and one["result"]["sum_pending_amt"] == pytest.approx(
        kpi("orders", "pending", vendor="KESAR ETHNIC (JAIPUR)"), abs=1)
    top = tools.query("po_lines", ["delivery_status = Overdue (Pending)"], group_by="vendor",
                      metrics=["sum overdue_amt", "count"], limit=3)
    vals = [r["sum_overdue_amt"] for r in top["result"]]
    assert len(vals) == 3 and vals == sorted(vals, reverse=True)
    assert top["overall"]["sum_overdue_amt"] == pytest.approx(kpi("orders", "overdue"), abs=1)
    rows = tools.query("enquiries", ["status != Solved"], columns=["supplier", "days_pending"], sort_by="days_pending",
                       limit=2)["result"]
    assert len(rows) == 2 and rows[0]["days_pending"] >= rows[1]["days_pending"]


def test_month_and_date_filters_agree():
    a = tools.query("po_lines", ["month = July-26"], metrics=["sum order_amt"])["result"]["sum_order_amt"]
    b = tools.query("po_lines", ["po_date = July 2026"], metrics=["sum order_amt"])["result"]["sum_order_amt"]
    c = tools.query("po_lines", ["po_date >= 2026-07-01", "po_date < 2026-08-01"], metrics=["sum order_amt"])
    assert a == b == c["result"]["sum_order_amt"]


def test_forgiving_and_helpful_filters():
    r = tools.query("enquiries", ["handled_by = gungn"])
    assert r["rows_matched"] == 0 and "gungun" in r["notes"][0]          # tells the model the right spelling
    r = tools.query("po_lines", ["vendor = kesar"], metrics=["count"])
    assert r["result"]["count"] > 0 and "contains" in r["notes"][0]
    r = tools.query("po_line", ["supplier contains kesar"], metrics=["count"])   # near-miss table & column names
    assert r["table"] == "po_lines" and r["result"]["count"] > 0


@pytest.mark.parametrize("call", [
    lambda: tools.query("nothing_like_this"),
    lambda: tools.query("po_lines", ["vendor ~~ kesar"]),
    lambda: tools.query("po_lines", ["pending_amt > lots"]),
    lambda: tools.query("po_lines", metrics=["sum vendor"]),
    lambda: tools.search("   "),
])
def test_bad_tool_input_is_explained_not_crashing(call):
    with pytest.raises(ToolError):
        call()


def test_search_finds_rows_and_other_tabs():
    r = tools.search("FWPO-00003/2627")
    assert r["matches"] >= 1 and r["results"][0]["table"] == "po_lines"
    r = tools.search("nova prints")                              # only on a scratch tab (Sheet18)
    assert r["results"][0]["tab"] == "Sheet18"
    assert tools.search("zzqx nothing")["matches"] == 0


def test_catalog_lists_tables_and_values():
    c = tools.catalog()
    assert "po_lines" in c and "delivery_status [" in c and "Sheet18" in c and len(c) < 7000


# ------------------------------------------------------------------------------- glossary
@pytest.mark.parametrize("q,term", [
    ("PO kya hai", "PO (purchase order)"), ("what does overdue mean", "Overdue (orders)"),
    ("GR ka matlab", "GR (goods return)"), ("full form of MSME", "MSME"), ("what is KPI", "KPI"),
    ("LR kya hota hai", "LR (lorry receipt)"), ("meaning of ageing", "Ageing"), ("what is debit note", "Debit note"),
    ("net payable kise kehte hai", "Net payable"), ("what is the enquiry sheet", "Supplier's Enquiry Sheet"),
    ("what does rcvd % mean", "RCVD %"), ("crore kya hota hai", "Crore"), ("handled by meaning", "Handled by"),
])
def test_glossary_answers_meanings(q, term):
    r = client.post("/api/chat", json={"message": q}).json()
    assert r["engine"] == "glossary" and term in r["answer"]


@pytest.mark.parametrize("q", ["what is pending", "pending kitna hai", "what is the total overdue", "dues of mahavir",
                               "which vendor has most pending", "what are inactive suppliers", "kitna overdue hai"])
def test_figure_questions_are_not_glossary(q):
    assert glossary.answer(q) is None


# ------------------------------------------------------------------------------- figure check
def test_ungrounded_figures():
    src = ['{"sum_pending_amt": 1468375, "count": 44}', "Solved rate: 38.3%"]
    assert ungrounded("Kesar has **₹14.68 L** pending in 44 lines (38.3%).", src) == []
    assert ungrounded("PO FWPO-00166/2627 due 21/07/2026, top 3", src) == []
    assert ungrounded("Kesar has ₹15.20 L pending", src) == ["₹15.20 L"]


# ------------------------------------------------------------------------------- Gemini with tools (faked)
class _Resp:
    status_code = 200

    def __init__(self, content):
        self._c = content

    def json(self):
        return {"candidates": [{"content": self._c}]}


class Scripted:
    """Plays a fixed list of model turns; each turn may look at what the analyst sent."""

    def __init__(self, *turns):
        self.turns, self.bodies = list(turns), []

    def post(self, url, json=None, timeout=None, headers=None):
        self.bodies.append(copy.deepcopy(json))
        turn = self.turns.pop(0)
        content = turn(json) if callable(turn) else turn
        return _Resp({"role": "model", "parts": content})


def call(name, **args):
    return [{"functionCall": {"name": name, "args": args}}]


def last_response(body):
    return body["contents"][-1]["parts"][0]["functionResponse"]["response"]


@pytest.fixture
def use_analyst(monkeypatch):
    def install(fake, **kw):
        analyst = GeminiAnalyst("test-key", session=fake, tools=tools, **kw)
        monkeypatch.setattr(main, "get_analyst", lambda: analyst)
        main.ANSWER_CACHE.clear()
        return analyst
    yield install
    main.ANSWER_CACHE.clear()


def kesar_pending() -> str:
    """Kesar Ethnic's pending value as the dashboard shows it today (the demo orders move with the date)."""
    return f"₹{kpi('orders', 'pending', vendor='KESAR ETHNIC (JAIPUR)') / 1e5:.2f} L"


def test_gemini_looks_up_exact_rows(use_analyst):
    fake = Scripted(call("query_table", table="po_lines", filters=["vendor contains kesar"], metrics=["sum pending_amt"]),
                    lambda b: [{"text": f"Kesar Ethnic: **₹{last_response(b)['result']['sum_pending_amt'] / 1e5:.2f} L** "
                                        "still to come in."}])
    use_analyst(fake)
    r = client.post("/api/chat", json={"message": "kesar ethnic details"}).json()
    assert r["engine"] == "gemini" and kesar_pending() in r["answer"] and "couldn't be checked" not in r["answer"]
    sent = fake.bodies[0]
    assert "TABLES" in sent["systemInstruction"]["parts"][0]["text"]
    assert {f["name"] for f in sent["tools"][0]["functionDeclarations"]} == {"calculate", "query_table", "search_rows"}


def test_made_up_figure_is_sent_back_and_corrected(use_analyst):
    fake = Scripted([{"text": "Kesar has **₹99.99 L** pending."}],
                    call("query_table", table="po_lines", filters=["vendor contains kesar"], metrics=["sum pending_amt"]),
                    [{"text": f"Kesar has **{kesar_pending()}** pending."}])
    use_analyst(fake)
    r = client.post("/api/chat", json={"message": "kesar ethnic details"}).json()
    assert kesar_pending() in r["answer"]
    assert "CHECK:" in fake.bodies[1]["contents"][-1]["parts"][0]["text"]


def test_figure_that_stays_unverified_is_flagged(use_analyst):
    fake = Scripted([{"text": "Kesar has **₹99.99 L** pending."}], [{"text": "Kesar has **₹99.99 L** pending."}])
    use_analyst(fake)
    r = client.post("/api/chat", json={"message": "kesar ethnic details"}).json()
    assert "couldn't be checked" in r["answer"]


def test_search_on_other_tabs(use_analyst):
    fake = Scripted(call("search_rows", text="nova prints", scope="all"),
                    lambda b: [{"text": "NOVA PRINTS is on tab " + last_response(b)["results"][0]["tab"] + ": rates revised."}])
    use_analyst(fake)
    r = client.post("/api/chat", json={"message": "nova prints ka kya update hai"}).json()
    assert "Sheet18" in r["answer"]


def test_tool_errors_reach_the_model(use_analyst):
    fake = Scripted(call("query_table", table="po_lines", filters=["vendor ~~ x"]),
                    lambda b: [{"text": "Sorry: " + last_response(b)["error"][:40]}])
    use_analyst(fake)
    r = client.post("/api/chat", json={"message": "kesar ethnic details"}).json()
    assert r["answer"].startswith("Sorry: Can't read filter")


def test_slow_or_failing_gemini_falls_back_to_rules(use_analyst):
    class Down:
        def post(self, *a, **k):
            raise TimeoutError
    use_analyst(Down())
    r = client.post("/api/chat", json={"message": "pending kitna percent hai ordered ka"}).json()
    assert r["engine"] == "rules" and r["answer"]
    use_analyst(Scripted(), deadline=0)            # no time left: never calls Google, rules answer
    r = client.post("/api/chat", json={"message": "kesar ethnic details"}).json()
    assert r["engine"] == "rules" and "KESAR" in r["answer"]


# ------------------------------------------------------------------------------- speed: answer cache
def test_same_question_is_served_from_cache(use_analyst):
    fake = Scripted(call("query_table", table="po_lines", filters=["vendor contains kesar"], metrics=["count"]),
                    lambda b: [{"text": f"{last_response(b)['result']['count']} PO lines for Kesar."}])
    use_analyst(fake)
    a = client.post("/api/chat", json={"message": "kesar ethnic details"}).json()
    b = client.post("/api/chat", json={"message": "Kesar Ethnic details?"}).json()
    assert a["answer"] == b["answer"] and len(fake.bodies) == 2     # the second answer cost no Gemini call


# ------------------------------------------------------------------------------- broad question bank (rules)
BANK = """total ordered|total received|total pending|pending kitna hai|kitna maal aana baki hai|overdue amount
how many PO lines are overdue|on time percentage|on-time rate of kesar ethnic|pending of shree ram textiles
shree ram textiles ka overdue|which vendor has most pending|top 5 vendors by overdue|sabse zyada pending kis vendor ke paas hai
pending in july|july me kitna order hua|ordered in june 2026|pending pcs for kurta category|category wise pending
department wise pending|classic department pending|surat vendors pending|city wise overdue|status of po 12
FWPO-00003/2627|vendors running late|worst vendor on time|best vendor on time|total dues|dues overdue
payment due this week|oldest overdue bill|dues of mahavir creations|mahavir ka payment kitna baki hai|agency wise dues
MM agency dues|supplier wise dues|vendor orders total|order to vendors by status|how many enquiries|pending enquiries
unsolved enquiries|enquiries in process|solved rate|kitni enquiry pending hai gungun ke paas
which handler has most pending enquiries|enquiries of mahavir creations|enquiries in july
how many suppliers waiting for PO in surat|po issued in mumbai|terms approval pending|approved suppliers
terms not filled|inactive suppliers|what needs attention|help|average delay|ganga exports overdue lines
kolkata vendors overdue|dress category ordered|co-ord set pending|PO kya hai|GR ka matlab"""


@pytest.mark.parametrize("q", [x.strip() for line in BANK.splitlines() for x in line.split("|") if x.strip()])
def test_question_bank_without_gemini(q):
    main.ANSWER_CACHE.clear()
    r = client.post("/api/chat", json={"message": q}).json()
    assert r["understood"], f"{q!r} -> {r['answer'][:120]!r}"
    assert r["answer"] and "Something went wrong" not in r["answer"]


def test_spot_checks():
    ask = lambda q: client.post("/api/chat", json={"message": q}).json()["answer"]  # noqa: E731
    assert "MAHAVIR CREATIONS" in ask("mahavir ka payment kitna baki hai")
    assert "Kanchan" in ask("which handler has most pending enquiries")
    assert "Order to vendors" in ask("vendor orders total")
    assert "What needs attention" in ask("what needs attention")
