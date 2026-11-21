"""WhatsApp nudges: a person clicks "Send" on a cause, the dashboard adds one message row to the Trigger tab of the
nudges sheet, and Iris sends that row from the company number.

The order sheets are never written to. Only the nudges sheet (NUDGE_SHEET_ID) is, and only with rows added at the
bottom of its Trigger tab. Who gets what comes from the Staff tab of that sheet:

    NAME | ROLE | WHATSAPP NUMBER | CAUSES      (CAUSES = any of: reply, po, bill, hold, enquiry, comma separated)

Without NUDGE_SHEET_ID the buttons are hidden (real data) or work against a built-in test outbox (demo data).
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

import pandas as pd

from .core import now_ist
from .dashboards import enquiries as enqs
from .dashboards import orders as ords

TRIGGER_TAB = "Trigger"
STAFF_TAB = "Staff"
COOLDOWN_SECONDS = 30 * 60          # the same list to the same person is not sent twice within this time unless forced
MAX_LINES = 10

SCOPES = {"today": "today", "week": "yesterday to 7 days ago", "month": "8 to 30 days ago", "older": "over 30 days ago"}

ASK = {   # what the person is being asked to do, per cause
    "reply": "waiting for your reply (BILL or PO)",
    "po": "waiting for a PO",
    "bill": "waiting for a bill",
    "hold": "on hold",
    "enquiry": "still open",
}
CLOSING = {
    "reply": "Please write BILL or PO for each in the order sheet.",
    "po": "Please mark PO STATUS DONE in the order sheet when each is made.",
    "bill": "Please mark BILL STATUS DONE in the order sheet when each is made.",
    "hold": "Please sort out the hold reason and tell the team.",
    "enquiry": "Please follow up and mark each one SOLVED in the enquiry sheet when it is done.",
}


class NudgeError(Exception):
    """Something the person can fix (no recipient, no sheet configured...)."""


@dataclass
class Person:
    name: str
    number: str
    causes: set


# ------------------------------------------------------------------------------------------ where messages go
class TestOutbox:
    """Demo data: a built-in staff list and an in-memory outbox, so the button can be tried with nothing connected."""
    test_mode = True

    def __init__(self):
        self.rows: list[list] = []

    def staff(self) -> list[Person]:
        return [Person("Mona", "910000000001", {"reply"}), Person("Akshat", "910000000002", {"po", "bill"}),
                Person("Kavita", "910000000003", {"enquiry"})]

    def append(self, row: list) -> None:
        self.rows.append(row)


class SheetOutbox:
    """The nudges Google Sheet. Uses the same service account with write access to that one sheet only."""
    test_mode = False

    def __init__(self, sheet_id: str, service_account_info: dict):
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_info(
            service_account_info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        self.session = AuthorizedSession(creds)
        self.sheet_id = sheet_id
        self.client_email = service_account_info.get("client_email", "")
        self._staff: tuple[float, list[Person]] | None = None

    def _url(self, rng: str, suffix: str = "") -> str:
        from urllib.parse import quote
        return f"https://sheets.googleapis.com/v4/spreadsheets/{self.sheet_id}/values/{quote(rng, safe='')}{suffix}"

    def _fail(self, resp) -> NudgeError:
        try:
            msg = resp.json().get("error", {}).get("message", resp.text[:200])
        except Exception:
            msg = resp.text[:200]
        hint = f" Share the nudges sheet with {self.client_email} as Editor." if resp.status_code in (403, 404) else ""
        return NudgeError(f"The nudges sheet answered {resp.status_code}: {msg}.{hint}")

    def staff(self) -> list[Person]:
        if self._staff and time.time() - self._staff[0] < 120:
            return self._staff[1]
        resp = self.session.get(self._url(f"{STAFF_TAB}!A1:F200"), params={"valueRenderOption": "FORMATTED_VALUE"}, timeout=30)
        if resp.status_code != 200:
            raise self._fail(resp)
        people = parse_staff(resp.json().get("values", []))
        self._staff = (time.time(), people)
        return people

    def append(self, row: list) -> None:
        resp = self.session.post(
            self._url(f"{TRIGGER_TAB}!A1", ":append"),
            params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
            json={"values": [row]}, timeout=30)
        if resp.status_code != 200:
            raise self._fail(resp)


def parse_staff(values: list[list]) -> list[Person]:
    """Staff tab rows -> people. Columns are found by heading, so their order can change."""
    if not values:
        return []
    head = [str(h).strip().upper() for h in values[0]]

    def col(*names):
        for n in names:
            for i, h in enumerate(head):
                if h.startswith(n):
                    return i
        return None

    ci, cn, cc = col("NAME"), col("WHATSAPP", "NUMBER", "PHONE"), col("CAUSE")
    if ci is None or cn is None or cc is None:
        raise NudgeError("The Staff tab needs the headings NAME, WHATSAPP NUMBER and CAUSES.")
    out = []
    for r in values[1:]:
        get = lambda i: str(r[i]).strip() if i < len(r) else ""
        digits = "".join(ch for ch in get(cn) if ch.isdigit())
        causes = {c.strip().lower() for c in get(cc).replace(";", ",").split(",") if c.strip()}
        if get(ci) and digits and causes:
            out.append(Person(get(ci), digits, causes))
    return out


_outbox = None
_lock = threading.Lock()
_sent: dict[tuple, float] = {}


def get_outbox(settings):
    global _outbox
    with _lock:
        if _outbox is None:
            sheet = os.getenv("NUDGE_SHEET_ID", "").strip()
            if sheet and settings.service_account_info:
                _outbox = SheetOutbox(sheet, settings.service_account_info)
            elif settings.data_source == "demo":
                _outbox = TestOutbox()
        return _outbox


def reset_for_tests():
    global _outbox
    _outbox = None
    _sent.clear()


# ---------------------------------------------------------------------------------------------- the message
def pick(v, cause: str, scope: str, min_days: int, group: str = "all") -> pd.DataFrame:
    """The stuck orders of one cause in the chosen part of the past. scope is today / week / month / older, or
    custom (waiting min_days days or more). Oldest first, as the dashboard shows them."""
    if cause == "enquiry":      # v is the parsed enquiry data; group = what the enquiry is about ("all" = every open one)
        try:
            rows = enqs.open_rows(v, group or "all")[1]
        except KeyError:
            raise NudgeError("Unknown enquiry group.")
    else:
        rows = v[v["cause"] == cause]
    if scope == "custom":
        rows = rows[rows["days_open"] >= max(1, min_days)]
    elif scope in ords.RANGES:
        rows = rows[ords.in_range(rows["days_open"], scope)]
    else:
        raise NudgeError("Choose which orders to send: today, yesterday to 7 days, 8 to 30 days, older, or a number of days.")
    return rows.sort_values(["date"], ascending=True, kind="stable")


def scope_words(scope: str, min_days: int) -> str:
    return f"waiting {max(1, min_days)} days or more" if scope == "custom" else f"placed {SCOPES[scope]}" if scope != "today" else "placed today"


def compose(person: Person, rows: pd.DataFrame, cause: str, scope: str, min_days: int) -> str:
    n = len(rows)
    enquiry = cause == "enquiry"
    plural = ("enquiry is" if n == 1 else "enquiries are") if enquiry else ("order is" if n == 1 else "orders are")
    lines = []
    for _, r in rows.head(MAX_LINES).iterrows():
        days = "" if scope == "today" else f", {int(r['days_open'])}d"
        if enquiry:
            lines.append(f"- {r['client_tidy']} ({r['about_tidy']}{days})")
        else:
            lines.append(f"- {r['client']} ({int(r['sets_n'])} sets{days})")
    more = f"\n...and {n - MAX_LINES} more" if n > MAX_LINES else ""
    url = os.getenv("NUDGE_DASHBOARD_URL", "").strip()
    link = f"\nFull list: {url}" if url else ""
    when = scope_words(scope, min_days).replace("placed", "asked") if enquiry else scope_words(scope, min_days)
    return (f"{person.name}, {n} {plural} {ASK[cause]} ({when}):\n"
            + "\n".join(lines) + more + f"\n{CLOSING[cause]}{link}")


def recipients(outbox, cause: str) -> list[Person]:
    people = [p for p in outbox.staff() if cause in p.causes]
    if not people:
        raise NudgeError(f"Nobody in the Staff tab has '{cause}' in the CAUSES column. Add the person who handles it.")
    return people


def who(outbox) -> dict:
    """Which people each cause goes to, for the button label."""
    out = {c: [] for c in ASK}
    for p in outbox.staff():
        for c in p.causes:
            if c in out:
                out[c].append(p.name)
    return out


def preview(outbox, orders_view, cause: str, scope: str, min_days: int = 0, group: str = "all") -> dict:
    if cause not in ASK:
        raise NudgeError("Unknown cause.")
    rows = pick(orders_view, cause, scope, min_days, group)
    people = recipients(outbox, cause)
    key = (cause, group if cause == "enquiry" else "", scope, min_days if scope == "custom" else 0)
    last = _sent.get(key)
    return {
        "count": len(rows),
        "to": [p.name for p in people],
        "message": compose(people[0], rows, cause, scope, min_days) if len(rows) else "",
        "already_sent_minutes": int((time.time() - last) // 60) if last and time.time() - last < COOLDOWN_SECONDS else None,
        "test_mode": outbox.test_mode,
    }


def send(outbox, orders_view, cause: str, scope: str, min_days: int = 0, force: bool = False, group: str = "all") -> dict:
    p = preview(outbox, orders_view, cause, scope, min_days, group)
    if not p["count"]:
        raise NudgeError(f"There are no {'enquiries' if cause == 'enquiry' else 'orders'} in this selection, so nothing was sent.")
    if p["already_sent_minutes"] is not None and not force:
        raise NudgeError(f"This list was already sent {p['already_sent_minutes']} minutes ago. Send it again only if you mean to.")
    rows = pick(orders_view, cause, scope, min_days, group)
    stamp = now_ist().strftime("%d %b %H:%M:%S")
    for person in recipients(outbox, cause):
        # a leading apostrophe keeps the phone number as text in the sheet
        outbox.append([stamp, person.name, "'" + person.number, compose(person, rows, cause, scope, min_days), "",
                       f"DASHBOARD {cause} {scope}" + (f" {min_days}d" if scope == "custom" else "") + (f" {group}" if cause == "enquiry" else ""), ""])
    _sent[(cause, group if cause == "enquiry" else "", scope, min_days if scope == "custom" else 0)] = time.time()
    return {**p, "sent": True, "sent_at": stamp}
