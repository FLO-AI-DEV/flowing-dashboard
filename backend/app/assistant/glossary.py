"""Meanings of the words used on the dashboard and in the sheets, answered instantly (no Gemini call).

"PO kya hai", "what does late mean", "GR ka matlab", "QC fail kya hai", "what is the order sheet" are
answered from TERMS below. A question that asks for a figure ("pending kitna hai", "total overdue") is NOT a meaning
question and goes to the numbers instead.

Each term: (name, aliases, meaning, where it appears, is_metric). For metric words (pending, overdue, ...) a plain
"what is pending" is a request for the number, so only explicit meaning words ("meaning", "matlab", "define",
"kya hota hai", "what does .. mean") return the definition.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Term:
    name: str
    aliases: tuple[str, ...]
    meaning: str
    where: str = ""
    metric: bool = False


TERMS: list[Term] = [
    # ------------------------------------------------------------------ dashboard words
    Term("KPI (Key Performance Indicator)", ("kpi", "kpis", "key performance indicator"),
         "A headline number shown in a box at the top of a page, like Open orders 30. The small text under it "
         "explains it.", "Top of every page"),
    Term("Dashboard", ("dashboard",),
         "One screen that reads Flo-Wing's Google Sheets every minute and shows the important numbers and lists. "
         "It only reads the order, payment, enquiry and returns sheets; it never changes them.", "Whole app"),
    Term("Filter", ("filter", "filters"),
         "Shows only part of the data, e.g. one month, channel or sales person. Clear the filter to see everything.",
         "Below each page title"),
    Term("Live / synced", ("live", "synced", "sync"),
         "The dashboard reads the sheets again every minute. 'Synced 20s ago' is when they were last read.", "Top bar"),
    Term("Demo data", ("demo data", "demo"),
         "Made-up practice data shown when no Google key is set up. With the key set, real sheet data is shown.",
         "Top bar"),
    Term("CSV", ("csv",), "Download a table as a file that opens in Excel. It contains exactly the rows you see.",
         "Under tables"),
    Term("FY (financial year)", ("fy", "financial year"),
         "Financial year, April to March. FY 2026-27 = April 2026 to March 2027.", "Page headers"),
    Term("Lakh (L)", ("lakh", "lac", "lakhs"), "1 lakh = 1,00,000. ₹11.47 L means about ₹11,47,000.", "Money figures"),
    Term("Crore (Cr)", ("crore", "cr", "crores"), "1 crore = 1,00,00,000 (100 lakh).", "Money figures"),
    Term("Password", ("password", "passcode", "login"),
         "The dashboard asks for the team password when it opens, and again every 24 hours.", "Start of the app"),
    # ------------------------------------------------------------------ orders
    Term("Order Sheet", ("order sheet", "ordersheet"),
         "The NEW ORDERSHEET 2026-27 Google Sheet: one tab per month and channel (NOV CREDIT SALE, NOV CASH SALE, "
         "MUMBAI SALE). Every client order is one row.", "Today, Orders, Team, Clients"),
    Term("Channel", ("channel", "channels", "credit sale", "cash sale", "mumbai sale"),
         "How the order was sold: Credit, Cash or Mumbai. Credit orders need Mona's reply first; Cash and Mumbai "
         "orders go straight to PO and billing.", "Orders filters"),
    Term("Sets", ("sets", "set"), "The quantity on an order, counted in sets.", "Orders, Team, Clients", True),
    Term("Open order", ("open order", "open orders"),
         "An order that is not billed yet and not finished.", "Today, Orders", True),
    Term("Late", ("late", "late order", "late orders", "delay", "delayed"),
         "An order that has waited at its current step longer than that step allows (Mona's reply 1 day, PO 3 days, "
         "billing 3 days, counted from the order date).", "Today, Orders, Team", True),
    Term("Mona's reply", ("mona", "mona reply", "mona's reply", "bill/po by mona"),
         "First step of a credit order: Mona writes BILL (bill straight away) or PO (a PO is needed first) on the "
         "order. She has 1 day.", "Orders, Team"),
    Term("PO (on an order)", ("po",),
         "The PO step of an order, done by the PO team within 3 days, before the order can be billed. On the PO "
         "follow-up page a PO is the payment request sent to the client for a sale order.", "Orders, PO follow-up"),
    Term("Billing", ("billing", "bill", "billed", "bill done"),
         "Last step: the billing team bills the order (Bill DONE in the sheet), within 3 days.", "Orders, Team"),
    Term("On hold", ("on hold", "hold", "hold reason"),
         "An order with a HOLD REASON in the sheet. It is parked with its sales person until the reason is cleared.",
         "Orders", True),
    Term("Who must act", ("who must act", "owner", "step owner"),
         "The person or team the order is waiting for right now: Mona, the PO team, the billing team, or the sales "
         "person for orders on hold.", "Orders, Team"),
    Term("Days open", ("days open",), "Days since the order date.", "Orders", True),
    Term("Sales person", ("sales person", "salesperson", "salesman"),
         "The person who took the order (SALES PERSON column).", "Orders, Team, Clients, PO follow-up"),
    Term("Quiet client", ("quiet", "quiet 30+ days", "quiet clients"),
         "A client who has not ordered for 30 days or more.", "Clients", True),
    # ------------------------------------------------------------------ payments / PO follow-up
    Term("CRM", ("crm", "crm member", "caller", "callers"),
         "The calling team (Kiran, Suryansh, Lokesh) who follow up payments with clients. Each pending sale order is "
         "assigned to one CRM member.", "Payments, PO follow-up"),
    Term("SO (sale order)", ("so", "sale order", "fwso"),
         "A sale order number like FWSO-08543/2627. One row of the payment follow-up sheet.", "Payments"),
    Term("Pending payment", ("pending payment", "pending payments", "pending"),
         "A sale order whose PAYMENT STATUS is still blank: not received and not cancelled.", "Payments", True),
    Term("Not followed up", ("not followed up", "stale", "follow up", "follow-up", "followup"),
         "A pending payment with no follow-up note for 2 days or more (measured from the time stamps of the notes).",
         "Payments", True),
    Term("Collected", ("collected", "collection", "received payment"),
         "Payment received (PAYMENT STATUS = RECIEVED).", "Payments", True),
    Term("Escalation (L1 / L2 / L3)", ("escalation", "l1", "l2", "l3", "escalated"),
         "How long a PO has waited: L1 5-7 days (caller reminds the client), L2 8-10 days (sales person and Kavita "
         "told), L3 11+ days (cancel or collect, decision with Kavita).", "PO follow-up"),
    Term("Past the limit", ("past limit", "past the limit", "limit"),
         "A PO that has waited more than 10 days; it is at risk of cancellation.", "PO follow-up", True),
    Term("PO not sent", ("not sent", "po not sent", "po send"),
         "A sale order whose PO was not sent to the client yet (PO SEND column).", "PO follow-up", True),
    # ------------------------------------------------------------------ enquiries
    Term("Enquiry", ("enquiry", "enquiries", "inquiry", "query"),
         "A customer-care case from the ENQUIRY SHEET (calls, parcel / transport, billing issues). It is solved only "
         "when the sheet says solved; everything else is open.", "Enquiries"),
    Term("Not picked up yet", ("not picked up", "not picked up yet"),
         "An open enquiry nobody has started on yet.", "Enquiries", True),
    # ------------------------------------------------------------------ returns
    Term("GR (goods return)", ("gr", "goods return", "sales return", "sales returns", "return", "returns"),
         "Goods a client sent back. Each returned barcode is one row of the Quality Check Sheet.", "Sales returns"),
    Term("CR", ("cr", "cr no", "fwsr", "credit note"),
         "The return number (like FWSR-00005/2627) the team gives a sales return.", "Sales returns"),
    Term("QC pass", ("qc pass", "qcpass", "pass"),
         "Quality check found the goods fine: the calling team calls the client and the goods go back at the "
         "client's cost.", "Sales returns", True),
    Term("QC fail", ("qc fail", "qcfail", "fail"),
         "Quality check found a real defect: the return is accepted.", "Sales returns", True),
    Term("90-day policy", ("policy", "90 day", "90-day", "return policy"),
         "A return is accepted only within 90 days of the bill date, and only for a genuine defect.", "Sales returns"),
]

MEANING = re.compile(
    r"\b(meaning|mean|means|meant|matlab|matalab|mtlb|arth|define|definition|defination|full ?form|stands? for|"
    r"kya hota|kya hoti|kya hote|kise kehte|kisko kehte|explain (the )?(term|word)|samjhao|samjha do|samjhaiye|"
    r"what does|what do)\b", re.I)
WHAT_IS = re.compile(r"\b(what is|what's|whats|what are|kya hai|kya hain|kya h|what is a|what is an)\b", re.I)
FIGURE = re.compile(
    r"\b(how much|how many|kitna|kitne|kitni|total|value|amount|sum|count|list|show|top|highest|lowest|most|least|"
    r"which|kaun|kis|kiska|kiski|batao|bata|figure|number of|status of|abhi|today|aaj|this month|of [a-z])\b|\d", re.I)

_ALIASES = sorted(((a, t) for t in TERMS for a in t.aliases), key=lambda x: -len(x[0]))


def _norm(q: str) -> str:
    q = q.lower().replace("’", "'")
    q = re.sub(r"[?!.,;:]+", " ", q)
    return re.sub(r"\s+", " ", q).strip()


def find_term(question: str) -> Term | None:
    q = _norm(question)
    for alias, term in _ALIASES:
        if re.search(rf"(?<![\w]){re.escape(alias)}(?![\w])", q):
            return term
    return None


def is_meaning_question(question: str) -> bool:
    q = _norm(question)
    return bool(MEANING.search(q) or WHAT_IS.search(q))


def answer(question: str) -> dict | None:
    """A definition answer, or None when this isn't a 'what does X mean' question."""
    q = _norm(question)
    if not q or len(q) > 120:
        return None
    explicit = bool(MEANING.search(q))
    if not explicit and not WHAT_IS.search(q):
        return None
    term = find_term(q)
    if term is None:
        return None
    # "what is the total pending" / "pending kitna hai" ask for a figure, not a meaning
    if not explicit and (term.metric or FIGURE.search(q)):
        return None
    if explicit and term.metric and re.search(r"\b(kitna|kitne|kitni|how much|how many)\b", q):
        return None
    text = f"**{term.name}**: {term.meaning}"
    if term.where:
        text += f"\n\n_Where:_ {term.where}"
    return {"answer": text, "page": None, "page_label": None, "context": {}, "understood": True,
            "intent": "glossary", "engine": "glossary"}


def glossary_text(max_chars: int = 2600) -> str:
    """Short glossary for the Gemini prompt."""
    out, size = [], 0
    for t in TERMS:
        line = f"- {t.name}: {t.meaning.split('. ')[0].rstrip('.')}."
        if size + len(line) > max_chars:
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out)
