"""Demo source: an order sheet laid out like Flo-Wing's NEW ORDERSHEET-2026-27, with invented clients and figures.

Used when no Google service account is configured (local runs, previews, tests). It keeps the real sheet's quirks so
the heading-based reader is exercised every time:
  * CREDIT tabs: headings in row 1, a count row under them, column A has no heading, a date typed as a heading.
  * CASH / MUMBAI tabs: blank (or filter) row 1, headings in row 2, "SR NO." in A, Mona's column named differently,
    fewer columns.
  * Quantities like "4", "1 pcs", "3+6 pcs"; a TOTAL row; a "full payment rcvd orders" tab that must be ignored.
Tabs are named after the current and previous month so the demo always looks current.
"""
from __future__ import annotations

import random
import threading
from datetime import date, timedelta

from ..core import today_ist

DEMO_SHEET_ID = "1HS61QM69oQXf6HeEeRo9GrM-2UaMzeiZtVxGptCPvSI"   # Flo-Wing Data Mirror
DEMO_ENQUIRIES_ID = "1OqnAbP8B1VFw6ZJXT1_ZTMQLt4hQ3AWzzxjFCZcM3Bc"
DEMO_PAYMENTS_ID = "1YtzUTartI0f1gDWwLFNDKsbwyYLO1cHeEhCL0ZaYQnE"
PAY_HEAD = ["Column 1", "Column 2", "Column 3", "CONTACT NO", "AMOUNT", "Column 6", "PO SEND", "PAYMENT STATUS",
            "Column 9", "Column 10", "FOLLOW UP -2", "FOLLOW UP -3", "FOLLOW UP -4", "FOLLOW UP -5", "FOLLOW UP -6",
            "Column - 7", "Column 8", "Column 9", "Column 18", "Column 20"]
CRM = ["KIRAN", "KIRAN", "SURYANSH", "LOKESH"]
NOTES_OPEN = ["call not pickup / msg drop", "msg drop", "karenge payment", "add more", "po shared", "aaj karenge payment"]

CLIENTS = ["Kalakriti Lucknow", "Yuvati Ahmedabad", "Navrang Industries Surat", "Maatri Prashanti", "Aashvi Couture",
           "Sitara Fashions (Chennai) W.S.", "Hemani Dresses", "Bijlee & Sons (Ranchi) W.S.", "Atipoorv Delhi",
           "Kolkata Creations Surat", "Sahej Fashion (Vadodara) W.S.", "Paridhan (Kolkata) W.S.", "Winmora (Jaipur)",
           "Bahurani Lucknow", "Shree Retails Jodhpur", "The Cotton Store (Orai)", "SM Retail (Delhi)",
           "Sabia Creation Mumbai", "Anusha Maheshwari Delhi", "Pari Fashion Bangalore", "La Vichitra Nagpur",
           "Radha Surat", "Saptam Fashion", "Viva Collection", "Perfect Creation Coimbatore", "Meera Traditional"]
SALES = ["piyush", "piyush", "piyush", "preeti", "preeti", "kamal", "sameer", "saeed", "luv", "BOSS"]
HOLD_REASONS = ["payment pending", "client asked to wait", "design change"]
PO_REASONS = ["fabric not in stock", "waiting for vendor"]
BILL_REASONS = ["GST number missing", "transport not fixed"]

CREDIT_HEAD = ["", "DATE", "TIMESTAMP", "CLIENT NAME", "ORDER TYPE", "SALES PERSON", "LEDGER", "MONA REPLY", "03/08/2026",
               "HOLD REASON", "ORDER (NO. OF SETS)", "PENDING (NO. OF SETS)", "BOX NOT OKAY REASON", "PO STATUS",
               "PO NOT DONE REASON", "PO STATUS DATE TIME", "BILL STATUS", "BILL NOT DONE REASON", "BILL STATUS TIME AND DATE"]
CASH_HEAD = ["SR NO.", "DATE", "DATE", "CLIENT NAME", "ORDER TYPE", "SALES PERSON", "LEDGER", "BILL/PO BY MONA", "",
             "HOLD REASON", "ORDER (NO. OF SETS)", "PENDING(NO. OF SETS)", "BOX NOT OKAY REASON", "PO STATUS",
             "PO NOT DONE REASON", "PO STATUS DATE TIME", "BILL STATUS", "BILL NOT DONE REASON",
             "BILL STATUS TIME AND DATE"]


def dmy(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _qty(rng) -> str:
    n = rng.choice([1, 2, 2, 3, 3, 4, 5, 6, 9])
    r = rng.random()
    return f"{n} pcs" if r < 0.15 else f"{n}+{rng.choice([2, 3, 6])} pcs" if r < 0.2 else str(n)


def _order(rng, d: date, today: date, credit: bool = True) -> dict:
    """One order and how far it has got, based on its age (older orders are mostly billed)."""
    age = (today - d).days
    o = {"date": dmy(d), "client": rng.choice(CLIENTS), "type": "WHATSAPP", "sales": rng.choice(SALES),
         "qty": _qty(rng), "mona": "", "hold": "", "po": "", "po_reason": "", "bill": "", "bill_reason": "",
         "bill_time": "", "pending": "", "mona_time": "", "po_time": ""}
    if rng.random() < 0.03:
        o["qty"] = ""                                   # forgotten quantity -> "rows to complete"
    if credit:                                          # only credit orders wait for Mona's BILL / PO reply
        replied = rng.random() < (0.997 if age > 3 else 0.85 if age >= 1 else 0.4)
        if not replied:
            return o
        o["mona"] = "PO" if rng.random() < 0.25 else "BILL"
        o["mona_time"] = dmy(d + timedelta(days=min(age, rng.choice([0, 1, 1, 1, 2]))))
    if rng.random() < 0.05 and age < 12:
        o["hold"] = rng.choice(HOLD_REASONS)
        return o
    if o["mona"] == "PO" or not credit:
        if age >= 1 and rng.random() < (0.99 if age > 6 else 0.7):
            o["po"] = "DONE"
            o["po_time"] = dmy(d + timedelta(days=min(age, rng.choice([0, 1, 1, 2, 4]))))
        else:
            if age > 3:
                o["po_reason"] = rng.choice(PO_REASONS)
            return o
    billed = rng.random() < (0.99 if age > 6 else 0.8 if age >= 3 else 0.5 if age >= 1 else 0.1)
    if billed:
        o["bill"] = "DONE"
        lag = min(age, rng.choice([0, 1, 1, 1, 2, 2, 3, 5]))
        if rng.random() > 0.04:
            o["bill_time"] = dmy(d + timedelta(days=lag))
    elif age > 3:
        o["bill_reason"] = rng.choice(BILL_REASONS)
    return o


def _credit_tab(orders) -> list[list]:
    rows = [CREDIT_HEAD, [str(len(orders))]]
    for i, o in enumerate(orders, 1):
        rows.append([str(i), o["date"], "", o["client"], o["type"], o["sales"], "", o["mona"],
                     o["mona_time"], o["hold"], o["qty"], o["pending"], "", o["po"], o["po_reason"],
                     o["po_time"], o["bill"], o["bill_reason"], o["bill_time"]])
    rows.append(["", "", "", "TOTAL", "", "", "", "", "", "", str(len(orders)), "", "", "", "", "", "", "", ""])
    return rows


def _cash_tab(orders, filter_row=False) -> list[list]:
    rows = [[""] * len(CASH_HEAD), CASH_HEAD]
    for i, o in enumerate(orders, 1):
        rows.append([str(i), o["date"], "", o["client"], o["type"], o["sales"], "", o["mona"], "", o["hold"], o["qty"],
                     o["pending"], "", o["po"], o["po_reason"], o["po_time"], o["bill"], o["bill_reason"],
                     o["bill_time"]])
    return rows


def _stamp(d: date, rng) -> str:
    return f"{d.strftime('%d/%m/%Y')} {rng.randint(10, 5 + 12) % 12 or 12:02d}:{rng.randint(0, 59):02d}:00 " \
           f"{'AM' if rng.random() < 0.4 else 'PM'}"


def _payments_grid(rng, today: date) -> list[list]:
    """Sale orders for the last ~6 weeks with follow-up notes; older ones mostly paid."""
    rows, n = [PAY_HEAD], 8500
    d = today - timedelta(days=42)
    while d <= today:
        if d.weekday() != 6:
            for _ in range(rng.randint(4, 12)):
                n += 1
                age = (today - d).days
                owner = rng.choice(CRM)
                amount = rng.choice([4805, 6888, 8825, 12650, 19940, 23123, 30959, 44916, 59911, 98525, 155856])
                notes, status = [], ""
                touch = d
                paid_chance = 0.9 if age > 14 else 0.6 if age > 5 else 0.25
                while touch < today and len(notes) < 5:
                    touch = touch + timedelta(days=rng.choice([0, 1, 1, 2, 2, 3, 6]))
                    if touch > today:
                        break
                    notes.append(f"{rng.choice(NOTES_OPEN)}  —  {_stamp(touch, rng)}")
                    if rng.random() < paid_chance / 2:
                        notes.append(f"payment done   —  {_stamp(touch, rng)}")
                        status = "RECIEVED" if rng.random() < 0.9 else ""
                        break
                    if rng.random() < 0.3:          # someone stops following up
                        break
                if not status and rng.random() < 0.02:
                    status = "CANCEL"
                row = [f"{d.strftime('%d/%m/%Y')} 10:{rng.randint(0, 59):02d}:00", rng.choice(CLIENTS),
                       f"FWSO-{n:05d}/2627", "9000000000", str(amount), rng.choice(SALES).upper(),
                       "YES" if rng.random() < 0.8 else "", status, owner] + notes
                row += [""] * (19 - len(row))
                rows.append(row + [owner])
        d += timedelta(days=1)
    return rows


ENQ_ABOUT = ["Parcel track", "PARCEL TRACK", "Refund", "Invoice required", "Article issue", "Rate diff", "Parcel not deliver",
             "Missing article", "Need lr", "Payment query"]
ENQ_STATUS = ["Solved ", "Solved", "solve", "Pending ", "in process", ""]
ENQ_REMARK = ["need lr", "invoice no sent", "client waiting", "shared details", "transport se baat karni hai", ""]


def _enquiry_tabs(rng, today: date) -> dict:
    """The three mirrored enquiry tabs, laid out like the real ones (title row + heading row on the group tabs)."""
    calls = [["DATE & TIME ", "CLIENT NAME ", "Number ", "ENQUIRY ABOUT ", "REMARK ", "SOLVE/ PENDING", "FOLLOW UP ", "Client reply "]]
    d = today - timedelta(days=45)
    while d <= today:
        if d.weekday() != 6:
            for _ in range(rng.randint(3, 8)):
                age = (today - d).days
                status = rng.choice(ENQ_STATUS[:3] if age > 10 and rng.random() < 0.85 else ENQ_STATUS)
                calls.append([f"{d.strftime('%d/%m/%Y')} {rng.randint(10, 18)}:{rng.randint(0, 59):02d}:00", rng.choice(CLIENTS),
                              "98765 43210", rng.choice(ENQ_ABOUT), rng.choice(ENQ_REMARK), status])
        d += timedelta(days=1)
    group_head = ["SNO. ", "DATE", "CLIENT NAME ", "ENQUIRY ABOUT ", "REMARK ", "GIVEN ", "SOLVE/ PENDING", "FOLLOW UP -1"]
    logistics = [["BILL T LOGISTIC ENQUIRY"], group_head]
    billing = [["PARTY BILLING ISSUE "], ["SNO. ", "DATE", "CLIENT NAME ", "", "ENQUIRY ABOUT ", "REMARK ", "SOLVE/ PENDING", "FOLLOW UP "]]
    for i in range(14):
        d = today - timedelta(days=rng.randint(0, 120))
        st = rng.choice(["solve", "solve ", "Pending", "in process"])
        logistics.append([str(i + 1), d.strftime("%d-%m-%Y"), rng.choice(CLIENTS), "PARCEL NOT DELIVER ", "bill no 3504", "", st, ""])
        billing.append([str(i + 1), d.strftime("%d-%m-%Y"), rng.choice(CLIENTS), "", "RATE DIFF", "bill no 7166", st, ""])
    return {"ENQ CALLS": calls, "ENQ LOGISTICS": logistics, "ENQ BILLING": billing}


class DemoSheetSource:
    name = "demo"

    def __init__(self, seed: int = 2026, today: date | None = None):
        self.seed = seed
        self.fixed_today = today
        self._lock = threading.Lock()
        self._built_for = None
        self._tabs: dict[str, list] = {}

    def _build(self):
        today = self.fixed_today or today_ist().date()
        with self._lock:
            if self._built_for == today:
                return self._tabs
            rng = random.Random(self.seed)
            first = today.replace(day=1)
            prev = (first - timedelta(days=1)).replace(day=1)
            tabs: dict[str, list] = {}
            for start, end in ((first, today), (prev, first - timedelta(days=1))):
                mon = start.strftime("%b").upper()
                per_channel = {"Credit": [], "Cash": [], "Mumbai": []}
                d = start
                while d <= end:
                    if d.weekday() != 6:            # no orders on Sundays
                        for ch, n in (("Credit", rng.randint(3, 7)), ("Cash", rng.randint(1, 4)),
                                      ("Mumbai", rng.randint(0, 2))):
                            per_channel[ch] += [_order(rng, d, today, ch == "Credit") for _ in range(n)]
                    d += timedelta(days=1)
                tabs[f"{mon} CREDIT SALE"] = _credit_tab(per_channel["Credit"])
                tabs[f"{mon} CASH SALE"] = _cash_tab(per_channel["Cash"])
                tabs[f"{mon.title()} MUMBAI SALE"] = _cash_tab(per_channel["Mumbai"], filter_row=True)
            tabs[f"full payment rcvd orders {prev.strftime('%b').upper()} / {first.strftime('%b').upper()}."] = \
                [["CLIENT NAME", "AMOUNT"], ["Someone", "1000"]]
            self._enquiries = _enquiry_tabs(rng, today)
            self._payments = {"Form responses 1": _payments_grid(rng, today), "DASHBOARD": [["TEAM MEMBER"]]}
            self._tabs, self._built_for = tabs, today
            return tabs

    # -- source interface --------------------------------------------------------------------------------------
    def list_tabs(self, sheet_id):
        if sheet_id == DEMO_ENQUIRIES_ID:
            self._build()
            return [(t, i) for i, t in enumerate(self._enquiries)]
        if sheet_id == DEMO_PAYMENTS_ID:
            self._build()
            return [(t, i) for i, t in enumerate(self._payments)]
        if sheet_id != DEMO_SHEET_ID:
            from .google import SheetAccessError
            raise SheetAccessError("Unknown sheet id (demo source).")
        return [(t, i) for i, t in enumerate(self._build())]

    def get_values(self, sheet_id, tab, formatted=False):
        tabs = self._build()
        if sheet_id == DEMO_ENQUIRIES_ID:
            return [list(r) for r in self._enquiries[tab]]
        if sheet_id == DEMO_PAYMENTS_ID:
            return [list(r) for r in self._payments[tab]]
        return [list(r) for r in tabs[tab]]

    def get_formulas(self, sheet_id, tab, col_letter):
        return []
