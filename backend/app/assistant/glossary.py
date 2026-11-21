"""Meanings of the words used on the dashboard and in the sheets, answered instantly (no Gemini call).

"PO kya hai", "what does overdue mean", "GR ka matlab", "full form of MSME", "what is the enquiry sheet" are
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
         "A headline number shown in a box at the top of a page, like Pending ₹1.19 Cr. It tells you at a glance how "
         "things stand; the small text under it explains it.", "Top of every page"),
    Term("Dashboard", ("dashboard",),
         "One screen that reads Flo-Wing's Google Sheets every minute and shows the important numbers, charts and lists. "
         "It only reads; it never changes a sheet.", "Whole app"),
    Term("Filter", ("filter", "filters"),
         "Shows only part of the data, e.g. one vendor, one month or one status. Reset clears all filters. Filters are "
         "saved in the page link, so a filtered view can be shared.", "Below each page title"),
    Term("Live / synced", ("live", "synced", "sync", "delayed badge"),
         "The dashboard reads the sheets again every minute. 'Synced 20s ago' is when they were last read; 'Delayed' "
         "means Google didn't answer and the last good copy is shown.", "Top bar"),
    Term("Demo data", ("demo data", "demo"),
         "Made-up practice data shown when no Google key is set up. With the key in backend/service-account.json the "
         "badge disappears and real sheet data is shown.", "Top bar"),
    Term("CSV", ("csv",), "Download a table as a file that opens in Excel. It contains exactly the rows you see.",
         "Under every table"),
    Term("TOTAL row", ("total row",), "The last row of a table, adding up all rows above it.", "Tables"),
    Term("FY (financial year)", ("fy", "financial year", "fy 2026-27"),
         "Financial year, April to March. FY 2026-27 = April 2026 to March 2027.", "Top left, page headers"),
    Term("Lakh (L)", ("lakh", "lac", "lakhs"), "1 lakh = 1,00,000. ₹11.47 L means about ₹11,47,000.", "Money figures"),
    Term("Crore (Cr)", ("crore", "cr", "crores"), "1 crore = 1,00,00,000 (100 lakh). ₹1.19 Cr means about ₹1,19,00,000.",
         "Money figures"),
    Term("pcs / qty", ("pcs", "qty", "quantity", "pieces", "piece", "maal"),
         "Number of garments (pieces), as opposed to money (₹).", "Orders, Vendors"),
    Term("Overview page", ("overview", "overview page"),
         "The 'what needs attention now' page: alert cards for overdue PO lines, pending pieces, overdue dues, vendor "
         "orders and pending supplier enquiries, plus a summary of each sheet.", "Overview"),
    Term("Sheets page", ("sheets page",), "Opens any tab of any of the four sheets live, with search and CSV download.",
         "Sheets"),
    Term("Scorecard", ("scorecard", "score card"),
         "One row per vendor with pending, overdue, received % and on-time %, so vendors can be compared.", "Vendors"),
    # ------------------------------------------------------------------ the four sheets
    Term("Order Status sheet", ("order status", "order status sheet", "po master", "order status 2026-2027"),
         "Google Sheet 'Order Status (2026-2027)', tab 'PO Master'. One row = one item/design on a purchase order: vendor, "
         "PO date, delivery date, ordered / received / pending quantity and value.", "Orders and Vendors pages"),
    Term("DUES PAYMENT SUPPLIERS sheet", ("dues sheet", "dues payment suppliers", "dues payment suppliers sheet"),
         "Google Sheet of unpaid supplier bills. Each dated tab is a dues list on that date; one row = one unpaid bill "
         "(supplier, bill date, net payable, dues-on date). 'Updated Sheet' holds each supplier's agency, credit days "
         "and discount.", "Supplier dues page"),
    Term("Order to vendors sheet", ("order to vendors", "order to vendor", "order to vendors sheet"),
         "Google Sheet of orders sent to vendors. One row = one order; the dashboard finds the vendor, status, amount "
         "and quantity columns by their names.", "Order to vendors page"),
    Term("Supplier's Enquiry Sheet", ("supplier enquiry sheet", "suppliers enquiry sheet", "supplier's enquiry sheet",
                                      "enquiry sheet"),
         "Google Sheet the purchase team keeps: 'Sheet1' is the enquiry log (one row = one supplier issue and its "
         "follow-up), 'Supplier's Enquiry Sheet' tab lists suppliers waiting for a PO city by city, 'Terms Approval' "
         "holds agreed payment terms, 'Inactive25-26' lists suppliers not bought from this year.",
         "Supplier enquiries page"),
    # ------------------------------------------------------------------ orders and vendors
    Term("PO (purchase order)", ("po", "pos", "purchase order", "purchase orders", "po number", "po no"),
         "Flo-Wing's official order to a supplier, e.g. FWPO-00166/2627 ('order 400 pcs of this design by 20 July').",
         "Orders, Vendors, Overview"),
    Term("PO line", ("po line", "po lines", "line", "lines"),
         "One item/design on a PO. One PO can have many lines; each row of the PO Master tab is one line.", "Orders"),
    Term("Vendor / supplier / party", ("vendor", "vendors", "supplier", "suppliers", "party", "parties", "vender"),
         "The business Flo-Wing buys garments from. The three words mean the same thing in these sheets.", "All pages"),
    Term("Ordered", ("ordered", "order value", "order amount", "order amt"),
         "Value (₹) or quantity (pcs) Flo-Wing asked the vendor for on the PO.", "Orders, Vendors", True),
    Term("Received", ("received", "recived", "rcvd", "aaya", "aa gaya"),
         "What has actually arrived from the vendor, in ₹ or pcs.", "Orders, Vendors", True),
    Term("Pending (orders)", ("pending", "pending order", "pending value", "aana baki", "baki"),
         "Still to come in: ordered minus received. On the Orders page it is goods the vendor still has to deliver.",
         "Orders, Vendors", True),
    Term("Overdue (orders)", ("overdue", "overdue pos", "late", "overdue lines"),
         "Still pending AND the delivery date has passed. The most urgent number on the Orders page.",
         "Orders, Vendors, Overview", True),
    Term("Delivery date", ("delivery date", "deadline", "due date of delivery"),
         "The date the vendor promised to deliver by, from the PO Master tab.", "Orders"),
    Term("On Time", ("on time", "ontime"), "Received on or before the delivery date.", "Orders → delivery status"),
    Term("Delayed", ("delayed", "delay"), "Received, but after the delivery date.", "Orders → delivery status"),
    Term("Overdue (Pending)", ("overdue pending", "overdue (pending)"),
         "Not received and the delivery date has passed.", "Orders → delivery status"),
    Term("Open (Within Deadline)", ("open within deadline", "within deadline", "open (within deadline)"),
         "Not received yet, but the delivery date hasn't passed, so it isn't late yet.", "Orders → delivery status"),
    Term("No Date", ("no date",), "The sheet has no delivery date for that line, so it can't be called late or on time.",
         "Orders → delivery status"),
    Term("Nil Order", ("nil order",), "A line where nothing was actually ordered (zero quantity and value).",
         "Orders → delivery status"),
    Term("Delivery status / timing", ("delivery status", "timing", "status of delivery"),
         "Every PO line gets one: On Time, Delayed, Overdue (Pending), Open (Within Deadline), No Date or Nil Order.",
         "Orders filters and charts"),
    Term("Delay (days)", ("delay days", "days late", "avg delay", "average delay"),
         "How many days after the delivery date the goods arrived (for Delayed lines).", "Orders, Vendors"),
    Term("On-time %", ("on-time %", "on time %", "on-time rate", "on time rate", "ontime %"),
         "Out of all lines received, the share that arrived by the delivery date. Higher = more reliable vendor.",
         "Orders, Vendors", True),
    Term("RCVD % / received %", ("rcvd %", "received %", "rcvd%", "received percent"),
         "Received ÷ ordered: how much of what was ordered has arrived.", "Vendors scorecard", True),
    Term("Vendors running late", ("vendors running late",),
         "How many vendors have at least one overdue PO line.", "Vendors", True),
    Term("Category", ("category", "categories"),
         "Product type of the line, as written in the PO Master (e.g. kurta set, dress, co-ord).", "Orders"),
    Term("Department", ("department", "departments"), "The Flo-Wing team the order was placed for.", "Orders"),
    Term("Month (orders)", ("month", "months", "order month"),
         "Taken from the PO date; if that is blank, from the ORDER MONTH column.", "Orders month filter"),
    Term("Design no.", ("design no", "design number", "design"),
         "Flo-Wing's design code for the item; 'Supplier D.No.' is the supplier's own code.", "Orders"),
    Term("PO rate", ("po rate", "rate"), "Price per piece agreed on the PO.", "Orders"),
    # ------------------------------------------------------------------ dues
    Term("Dues / payable", ("dues", "payable", "payables", "dena", "payment due"),
         "Money Flo-Wing owes suppliers for bills not yet paid.", "Supplier dues", True),
    Term("Net payable", ("net payable", "net", "netpayable"),
         "The amount actually to pay on a bill after returns and adjustments.", "Supplier dues", True),
    Term("Bill", ("bill", "bills", "invoice"), "The supplier's invoice for goods sent.", "Supplier dues"),
    Term("Dues On date", ("dues on", "due on", "due date", "payment date"),
         "The date a bill must be paid by.", "Supplier dues"),
    Term("Overdue (dues)", ("overdue dues", "dues overdue", "overdue payment"),
         "Bills whose Dues On date has passed and are still unpaid.", "Supplier dues, Overview", True),
    Term("Due in next 7 days", ("due in 7 days", "due this week", "next 7 days"),
         "Bills falling due in the next seven days: the payments to plan this week.", "Supplier dues", True),
    Term("Oldest overdue", ("oldest overdue",), "Days since the oldest unpaid bill fell due.", "Supplier dues", True),
    Term("Ageing", ("ageing", "aging", "age wise"),
         "Overdue money grouped by how late it is: 0-30, 31-60, 61-90, 90-120 and 120+ days.", "Supplier dues"),
    Term("Credit days / payment days", ("credit days", "payment days", "credit period"),
         "How many days after the bill Flo-Wing is allowed to pay, e.g. 30 or 45.", "Supplier dues, Terms approval"),
    Term("Discount / cash discount", ("discount", "cash discount", "disc", "cd"),
         "% off the bill the supplier gives, often for paying early ('3% if paid within 7 days').",
         "Supplier dues, Terms approval"),
    Term("Agency", ("agency", "agent", "commission agent"),
         "The middleman / commission agent through whom a supplier was arranged.", "Supplier dues"),
    Term("MSME", ("msme",),
         "A government-registered micro, small or medium business. MSME suppliers generally have to be paid within "
         "45 days, so their bills are a priority. In supplier names, '(MSME)' marks them.", "Supplier names"),
    Term("Before tax (BFT)", ("bft", "before tax", "amountbft"), "Amount before GST is added.", "Outstanding reports"),
    # ------------------------------------------------------------------ enquiries
    Term("Enquiry", ("enquiry", "enquiries", "inquiry", "complaint", "complaints"),
         "One issue logged with a supplier, e.g. '2 pcs missing' or 'rate difference in bill', with its follow-up.",
         "Supplier enquiries"),
    Term("Pending enquiries", ("pending enquiries", "pending enquiry", "open enquiries"),
         "Enquiries not marked SOLVED: unsolved, in process, or status left blank.", "Supplier enquiries", True),
    Term("Solved / Unsolved / In process", ("solved", "unsolved", "in process", "no status"),
         "The STATUS column of the enquiry log: Solved = done, Unsolved = stuck, In process = being worked on, "
         "No status = left blank.", "Supplier enquiries"),
    Term("Solved rate", ("solved rate", "solved %"), "Solved enquiries ÷ all enquiries.", "Supplier enquiries", True),
    Term("Handled by / follow up", ("handled by", "handler", "follow up", "followup", "follow-up"),
         "The Flo-Wing person following the enquiry up (the 'Follow Up' column), e.g. Nidhi, Kanchan, Gungun, Shaily.",
         "Supplier enquiries"),
    Term("Concerned person", ("concerned person", "contact person"), "The contact at the supplier's side.",
         "Supplier enquiries"),
    Term("Days pending", ("days pending", "days open"), "Days since the enquiry (or order) date, for items not done yet.",
         "Supplier enquiries"),
    Term("Topic", ("topic", "topics"),
         "What an enquiry is about, read from its text: missing pieces, GR/defect, bill/rate, PO follow-up, "
         "shoot/photos, dispatch, material to send.", "Supplier enquiries"),
    Term("GR (goods return)", ("gr", "goods return", "goods returned"),
         "Pieces sent back to the supplier (or returned by a client), usually because of a defect.", "Enquiry notes"),
    Term("LR (lorry receipt)", ("lr", "lorry receipt"), "The transport slip proving a parcel was dispatched.",
         "Enquiry notes"),
    Term("Debit note", ("debit note",),
         "A note Flo-Wing sends a supplier to reduce what it owes them, for returns or a wrong rate.", "Enquiry notes"),
    Term("Credit note", ("credit note",), "A note from the supplier reducing the amount on their bill.", "Enquiry notes"),
    Term("HSN code", ("hsn", "hsn code"), "The tax (GST) code printed on a bill for the type of goods.", "Enquiry notes"),
    Term("GST", ("gst",), "Goods and Services Tax added on bills.", "Bills"),
    Term("Ledger", ("ledger",), "A supplier's account in the accounting software.", "Enquiry notes"),
    Term("Waiting for PO", ("waiting for po", "po pending", "pending po"),
         "An order agreed with the supplier but the formal PO isn't sent yet (STATUS not 'DONE' in the city lists).",
         "Supplier enquiries → PO by city", True),
    Term("PO issued", ("po issued", "po done"), "The PO has been sent (STATUS 'DONE' in the city lists).",
         "Supplier enquiries → PO by city", True),
    Term("Terms approval", ("terms approval", "approval", "approved", "approval pending"),
         "Payment days and discount agreed with a (new) supplier, then approved by a senior person. Approval pending = "
         "not approved yet; Terms not filled = payment days or discount left blank.",
         "Supplier enquiries → Terms approval"),
    Term("Inactive supplier", ("inactive", "inactive supplier", "inactive suppliers"),
         "A supplier Flo-Wing hasn't bought from in 2025-26; the qty is what was bought from them earlier.",
         "Supplier enquiries → Inactive suppliers", True),
    Term("Purchase issues", ("purchase issue", "purchase issues"),
         "Problems logged against purchases (date, supplier, issue, design no., bill no.).",
         "Supplier enquiries"),
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
