"""Flo-Wing payment follow-up (CRM "New po sheet", tab "Form responses 1", filled by Kiran, Suryansh and Lokesh).

One row per sale order (FWSO-08543/2627): client, amount, sales person, PO SEND, PAYMENT STATUS (RECIEVED / CANCEL /
blank = still pending), the CRM member it is assigned to, and up to ten follow-up notes, each stamped by the form as
"call not pickup / msg drop   —  17/11/2026 04:42:12 PM".

What the dashboard needs from it:
  * pending payments (₹ and count) per CRM member and per sales person;
  * when each pending order was last followed up -> "not followed up for N days" is the real "not updating" signal,
    measured from the time stamps, not guessed;
  * money collected and how long collection took.

Quirks handled (seen in the real sheet, Nov 2026):
  * headings are mostly "Column 1", "Column 2"… (form defaults) and "Column 9" appears twice -> found by heading with
    a position fallback; the follow-up notes are every column between the assigned member and the second assignee;
  * the same SO number is sometimes submitted twice -> the latest row wins;
  * one note was pasted on 114 rows with the same time stamp ("Out of town . — 13/11/2026 11:35:42 AM") -> a note whose
    exact text and time stamp appear on BULK_MIN or more rows is ignored as a bulk paste, not counted as a follow-up;
  * follow-up columns are not in time order -> the newest time stamp wins;
  * the sheet goes back to the 2025-26 year -> only orders from FY_START onwards are used.
"""
from __future__ import annotations

import re
from collections import Counter

import pandas as pd

from ..core import month_label, month_sort_key, norm_key, parse_dates, today_ist
from ..locate import Col, locate
from ..tables import kpi, notice, table

TAB = "PO LOG"
FY_START = pd.Timestamp("2026-04-01")
FOLLOWUP_DAYS = 2        # a pending order not followed up for this many days is "not followed up"
BULK_MIN = 10            # the same note + time stamp on this many rows = a bulk paste, ignored

PAY_COLS = [
    Col("created", "COLUMN 1", "TIMESTAMP", "DATE", expect="date"),
    Col("client", "COLUMN 2", "PARTY NAME", "CLIENT NAME", after="created", expect="text"),
    Col("so", "COLUMN 3", "SO NO", "SALE ORDER", "PO NO", after="client"),
    Col("contact", "CONTACT NO", "CONTACT", required=False),
    Col("amount", "AMOUNT", "PO AMOUNT", required=False),
    Col("sales_person", "COLUMN 6", "SALES PERSON", required=False, after="amount"),
    Col("po_send", "PO SEND", required=False),
    Col("status", "PAYMENT STATUS", "STATUS", required=False),
    Col("owner", "COLUMN 9", "ASSIGNED TO", "CRM", required=False, after="status"),
    Col("owner2", "COLUMN 20", required=False),
    # optional columns the team adds to the right of the sheet; the page works without them
    Col("promised", "PROMISED DATE", "PROMISE DATE", "PAYMENT PROMISED", "PROMISED PAYMENT DATE", required=False),
    Col("part_paid", "PART PAYMENT RECEIVED", "PART PAYMENT", "PARTIAL PAYMENT", "ADVANCE RECEIVED", required=False),
]

DUE_DAYS = 7             # cash orders: payment is due this many days after the PO is sent to the client
LIMIT_DAYS = 10          # the longest a PO may wait; after this it is "past the limit" (likely to be cancelled)
PO_SHARE = re.compile(r"\bPO\s*(SHARE|SHARED|SEND|SENT)\b", re.I)    # a note like "po shared" = the PO went to the client
CHANGE_NOTE = re.compile(r"\b(ADD\s*MORE|REMOVE|ARTI[CK]LE?S?|ARTICAL|GR\s*RAISE)\b", re.I)   # order change, not a payment chase
BUCKETS = [("past_limit", f"{LIMIT_DAYS + 1}+ days: at risk of cancellation"), ("overdue", f"{DUE_DAYS + 1}–{LIMIT_DAYS} days: overdue"),
           ("due_soon", f"5–{DUE_DAYS} days: due soon"), ("on_track", "0–4 days: on track")]
BUCKET_KEYS = [k for k, _ in BUCKETS]
# Same age bands as the Orders page (days since the PO went to the client; today = day 0).
PERIODS = {"today": (0, 0), "week": (1, 7), "month": (8, 30), "older": (31, None)}
PERIOD_LABELS = [("today", "Today"), ("week", "Yesterday – 7 days"), ("month", "8 – 30 days"), ("older", "Older than 30 days")]
_RANK = {"past_limit": 0, "overdue": 1, "due_soon": 2, "not_sent": 3, "on_track": 4, "": 9}

_STAMP = re.compile(r"[—–-]{1,2}\s*(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?\s*[APap][Mm])")
RECEIVED_WORDS = ("RECIEVED", "RECEIVED", "DONE", "PAID")
PAID_NOTE = re.compile(r"\b(PAYMENT\s+DONE|DONE|PAID|RECEIVED|RECIEVED)\b", re.I)


def status_column(header) -> str:
    """Column letter of PAYMENT STATUS in the header row ('' if it cannot be found)."""
    for i, h in enumerate(header):
        if norm_key(str(h)) in ("PAYMENTSTATUS", "STATUS"):
            n, letters = i + 1, ""
            while n:
                n, r = divmod(n - 1, 26)
                letters = chr(65 + r) + letters
            return letters
    return ""


def is_closed_status(v) -> bool:
    s = str(v or "").upper()
    return "CANCEL" in s or any(w in s for w in RECEIVED_WORDS)


def row_runs(rows: list[int], gap: int = 15) -> list[tuple[int, int]]:
    """Row numbers -> (first, last) runs; rows less than `gap` apart share one read (fewer Google calls)."""
    runs: list[list[int]] = []
    for r in sorted(rows):
        if runs and r - runs[-1][1] <= gap:
            runs[-1][1] = r
        else:
            runs.append([r, r])
    return [(a, b) for a, b in runs]


def parse_note(cell: str):
    """'call not pickup / msg drop   —  17/11/2026 04:42:12 PM' -> ('call not pickup / msg drop', Timestamp)."""
    s = str(cell or "").strip()
    if not s:
        return None
    m = _STAMP.search(s)
    if not m:
        return (s, pd.NaT)
    text = s[:m.start()].strip(" —–-")
    ts = pd.to_datetime(m.group(1).upper(), format="%d/%m/%Y %I:%M:%S %p", errors="coerce")
    if pd.isna(ts):
        ts = pd.to_datetime(m.group(1).upper(), format="%d/%m/%Y %I:%M %p", errors="coerce")
    return (text, ts)


def _amount(v) -> float:
    s = re.sub(r"[^\d.]", "", str(v or ""))
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def parse_payments(grid, tab: str = TAB, today=None) -> dict:
    """Grid of 'Form responses 1' -> {"orders": DataFrame (one row per SO), "issues": [...]}"""
    today = pd.Timestamp(today) if today is not None else today_ist()
    lay = locate(grid, PAY_COLS, tab=tab)
    c = lay.columns
    first_note = c.get("owner", c.get("status", c["so"]) + 1) + 1
    last_note = c.get("owner2", first_note + 10)          # notes sit between the two assignee columns
    rows = []
    for raw in grid[lay.header_row + 1:]:
        get = lambda f: (str(raw[c[f]]).strip() if f in c and c[f] < len(raw) and raw[c[f]] is not None else "")
        if not get("client") and not get("so"):
            continue
        notes = [parse_note(raw[i]) for i in range(first_note, min(last_note, len(raw)))]
        rows.append({k: get(k) for k in [p.field for p in PAY_COLS]} | {"notes": [n for n in notes if n]})
    issues = []
    if not rows:
        return {"orders": pd.DataFrame(), "issues": issues, "bulk": []}

    # bulk pastes: same text + same time stamp on many rows
    seen = Counter((norm_key(t), ts) for r in rows for t, ts in r["notes"] if pd.notna(ts))
    bulk = {k for k, n in seen.items() if n >= BULK_MIN}
    d = pd.DataFrame(rows)
    d["created"] = parse_dates(d["created"].str.split(" ").str[0])
    d = d[d["created"].isna() | (d["created"] >= FY_START)]
    d["so_key"] = d["so"].str.upper().str.replace(r"\s+", "", regex=True)
    dups = d.loc[d["so_key"].ne("") & d.duplicated("so_key", keep="last"), ["so", "sales_person"]] if len(d) else d.iloc[0:0]
    d = d.drop_duplicates("so_key", keep="last") if len(d) else d

    def touches(notes):
        return [(t, ts) for t, ts in notes if pd.notna(ts) and (norm_key(t), ts) not in bulk]

    d["real_notes"] = d["notes"].map(touches)
    d["follow_ups"] = d["real_notes"].map(len)
    d["calls"] = d["real_notes"].map(lambda ns: sum(1 for t, _ in ns if not PO_SHARE.search(t)))   # chase calls, not "po shared"
    d["last_touch"] = d["real_notes"].map(lambda ns: max((ts for _, ts in ns), default=pd.NaT))
    d["last_note"] = d["real_notes"].map(lambda ns: max(ns, key=lambda n: n[1])[0] if ns else "")
    d["paid_at"] = d["real_notes"].map(
        lambda ns: min((ts for t, ts in ns if PAID_NOTE.search(t)), default=pd.NaT))
    st = d["status"].str.upper()
    d["state"] = "pending"
    d.loc[st.str.contains("CANCEL"), "state"] = "cancelled"
    d.loc[st.map(lambda s: any(w in s for w in RECEIVED_WORDS)), "state"] = "received"
    d["amount_n"] = d["amount"].map(_amount)
    d["promised"] = parse_dates(d["promised"]) if "promised" in d else pd.NaT
    d["part_paid_n"] = d["part_paid"].map(_amount) if "part_paid" in d else 0.0
    d["held"] = (d["state"] == "pending") & (d["part_paid_n"] > 0)     # partial payment received: hold, do not cancel
    owner = d["owner"].str.strip().str.title()
    d["owner"] = owner.where(owner != "", d["owner2"].str.strip().str.title()).replace("", "(unassigned)")
    d["sales_person"] = d["sales_person"].str.strip().str.title().replace("", "(none)")
    d["days_pending"] = (today.normalize() - d["created"].dt.normalize()).dt.days.fillna(0).astype(int)
    since = d["last_touch"].where(d["last_touch"].notna(), d["created"])
    d["days_since_touch"] = (today.normalize() - since.dt.normalize()).dt.days.fillna(0).clip(lower=0).astype(int)
    # notes say "payment done" but PAYMENT STATUS was never set: not a follow-up problem, a sheet-update problem
    d["status_not_updated"] = (d["state"] == "pending") & d["paid_at"].notna()
    d["stale"] = (d["state"] == "pending") & ~d["status_not_updated"] & (d["days_since_touch"] >= FOLLOWUP_DAYS)
    d["collect_days"] = (d["paid_at"].dt.normalize() - d["created"].dt.normalize()).dt.days.where(
        d["state"] == "received")
    d["month"] = month_label(d["created"])
    # --- PO clock: starts when the PO is sent to the client (the "po share" note), else when the order was made
    d["po_shared_at"] = d["real_notes"].map(
        lambda ns: min((ts for t, ts in ns if PO_SHARE.search(t)), default=pd.NaT))
    d["po_sent"] = d["po_send"].str.upper().str.contains("YES") | d["po_shared_at"].notna()
    d["clock_start"] = d["po_shared_at"].where(d["po_shared_at"].notna(), d["created"])
    d["days_out"] = (today.normalize() - d["clock_start"].dt.normalize()).dt.days.fillna(0).clip(lower=0).astype(int)
    pend = d["state"] == "pending"
    d["period"] = d["days_out"].map(lambda n: "today" if n == 0 else "week" if n <= 7 else "month" if n <= 30 else "older")

    def bucket(r):
        if r["state"] != "pending":
            return ""
        # every PO on this sheet has been sent to the client, so the age alone decides the box
        n = r["days_out"]
        return "on_track" if n <= 4 else "due_soon" if n <= DUE_DAYS else "overdue" if n <= LIMIT_DAYS else "past_limit"
    d["bucket"] = d.apply(bucket, axis=1) if len(d) else pd.Series(dtype=str)
    d["done_today"] = pend & (d["last_touch"].dt.normalize() == today.normalize())
    # paid today = a "payment done" note stamped today, or paid together with an order made today
    d["paid_today"] = (d["state"] == "received") & (
        (d["paid_at"].dt.normalize() == today.normalize())
        | (d["paid_at"].isna() & (d["created"].dt.normalize() == today.normalize())))
    first_call_due = (d["follow_ups"] == 0) & (d["days_out"] >= 1)
    d["promise_kept_wait"] = pend & d["promised"].notna() & (d["promised"].dt.normalize() >= today.normalize())   # client gave a date still ahead
    d["promise_broken"] = pend & d["promised"].notna() & (d["promised"].dt.normalize() < today.normalize())
    d["todo"] = pend & ~d["status_not_updated"] & ~d["done_today"] & ~d["promise_kept_wait"] & (
        d["bucket"].isin(["past_limit", "overdue", "due_soon", "not_sent"]) | d["stale"] | first_call_due | d["promise_broken"])
    d["change_note"] = d["last_note"].map(lambda t: bool(CHANGE_NOTE.search(t or "")))
    if len(dups):
        who = Counter(dups["sales_person"].str.strip().str.title())
        top = ", ".join(f"{n} ({c})" for n, c in who.most_common(4))
        sample = ", ".join(dups["so"].head(5))
        issues.append(notice(f"{len(dups)} SO number(s) appear on more than one row; the latest row of each is used, "
                             f"so they are counted once. By sales person: {top}. e.g. {sample}.", "info"))
    if bulk:
        biggest = max(bulk, key=lambda k: seen[k])
        issues.append(notice(f"{len(bulk)} note(s) were pasted onto many rows at once (largest: {seen[biggest]} rows "
                             f"at {biggest[1]:%d %b %H:%M}). They are not counted as follow-ups.", "info"))
    return {"orders": d.reset_index(drop=True), "issues": issues, "bulk": sorted(bulk, key=lambda k: -seen[k])}


# ----------------------------------------------------------------------------------------------- pages
def _lakh(x: float) -> str:
    return f"₹{x / 1e5:.1f} L" if x >= 1e5 else f"₹{x:,.0f}"


def options(data) -> dict:
    d = data["orders"]
    if d.empty:
        return {"month": [], "owner": [], "sales_person": []}
    months = sorted([m for m in d["month"].unique() if m != "(NO DATE)"], key=month_sort_key)
    return {"month": months, "owner": sorted(d["owner"].unique().tolist()),
            "sales_person": sorted(d["sales_person"].unique().tolist())}


def _filter(d, f):
    for key, col in (("owner", "owner"), ("sales_person", "sales_person"), ("month", "month")):
        if f.get(key):
            d = d[d[col].isin(f[key])]
    return d


def needs_action(data) -> list[dict]:
    """One line per CRM member with pending payments not followed up — feeds the Today page."""
    d = data["orders"]
    if d.empty:
        return []
    out = []
    for who, g in d[d["state"] == "pending"].groupby("owner"):
        stale = g[g["stale"]]
        fix = g[g["status_not_updated"]]
        if len(fix) and not len(stale):
            out.append({"who": who, "stage": "Payments", "late": len(fix), "due": 0, "tone": "warn",
                        "what": f"{len(fix)} paid order{'s' if len(fix) != 1 else ''} still not marked RECIEVED",
                        "oldest_days": 0})
            continue
        if len(stale):
            extra = f" · {len(fix)} paid but not marked RECIEVED" if len(fix) else ""
            out.append({"who": who, "stage": "Payments", "late": len(stale), "due": 0,
                        "what": f"{len(stale)} pending payment{'s' if len(stale) != 1 else ''} not followed up "
                                f"for {FOLLOWUP_DAYS}+ days ({_lakh(stale['amount_n'].sum())}){extra}",
                        "oldest_days": int(stale["days_since_touch"].max()), "tone": "bad"})
        else:
            out.append({"who": who, "stage": "Payments", "late": 0, "due": 0,
                        "what": "all pending payments followed up", "oldest_days": 0, "tone": "good"})
    return out


def payments_dashboard(data, f: dict, today=None) -> dict:
    today = pd.Timestamp(today) if today is not None else today_ist()
    d = _filter(data["orders"], {k: f.get(k) for k in ("owner", "sales_person")}) if not data["orders"].empty \
        else data["orders"]
    if d.empty:
        return {"title": "Payments", "kpis": [], "members": table(pd.DataFrame()), "pending": table(pd.DataFrame()),
                "notices": data.get("issues", []), "options": options(data)}
    this_month = month_label(pd.Series([today])).iloc[0]
    pending = d[d["state"] == "pending"]
    stale = pending[pending["stale"]]
    paid_m = d[(d["state"] == "received") & (d["paid_at"].dt.normalize() >= today.normalize().replace(day=1))]
    cancel_m = d[(d["state"] == "cancelled") & (d["month"] == this_month)]
    kpis = [
        kpi("Pending payments", float(pending["amount_n"].sum()), fmt="inr", hint=f"{len(pending)} orders", id="pending"),
        kpi("Not followed up", len(stale), hint=f"{FOLLOWUP_DAYS}+ days · {_lakh(stale['amount_n'].sum())}",
            tone="alert", id="stale"),
        kpi("Collected this month", float(paid_m["amount_n"].sum()), fmt="inr", hint=f"{len(paid_m)} orders",
            id="collected"),
        kpi("Cancelled this month", len(cancel_m), hint=_lakh(cancel_m["amount_n"].sum()), id="cancelled"),
    ]
    mem = []
    for who, g in d.groupby("owner"):
        p = g[g["state"] == "pending"]
        got = g[(g["state"] == "received") & g["collect_days"].notna()]
        mem.append({"CRM member": who, "Pending": len(p), "Pending ₹": round(p["amount_n"].sum()),
                    "Not followed up": int(p["stale"].sum()),
                    "Status not updated": int(p["status_not_updated"].sum()),
                    "Followed up today": int((p["last_touch"].dt.normalize() == today.normalize()).sum()),
                    "Collected this month ₹": round(g.loc[g.index.isin(paid_m.index), "amount_n"].sum()),
                    "Usual days to collect": float(got["collect_days"].median()) if len(got) else None})
    members = pd.DataFrame(mem).sort_values("Not followed up", ascending=False)
    p = pending.sort_values(["stale", "days_since_touch", "amount_n"], ascending=False)
    def _status(r):
        if r["status_not_updated"]:
            return "note says paid — set status to RECIEVED"
        if r["stale"]:
            return (f"no follow-up for {r['days_since_touch']} days" if r["follow_ups"]
                    else f"never followed up ({r['days_since_touch']} days)")
        return "followed up"
    status = p.apply(_status, axis=1) if len(p) else pd.Series(dtype=str)
    pend = pd.DataFrame({
        "Client": p["client"], "SO": p["so"], "Amount ₹": p["amount_n"].round(), "Sales person": p["sales_person"],
        "CRM member": p["owner"], "Order date": p["created"].dt.strftime("%d %b"), "Days pending": p["days_pending"],
        "Last follow-up": p["last_touch"].dt.strftime("%d %b").fillna("—"), "Last note": p["last_note"],
        "Status": status,
    })
    pend_tbl = table(pend, sort=False, title="Pending payments",
                     fmt={"Amount ₹": "inr", "SO": "text", "Order date": "text", "Last follow-up": "text"})
    pend_tbl["states"] = ["late" if s else "due" if u else "ok" for s, u in zip(p["stale"], p["status_not_updated"])]
    return {"title": "Payments", "kpis": kpis,
            "members": table(members, sort=False, title="By CRM member",
                             fmt={"Pending ₹": "inr", "Collected this month ₹": "inr", "Usual days to collect": "dec1"}),
            "pending": pend_tbl, "notices": data.get("issues", []), "options": options(data)}


def alerts(data, today=None) -> list[dict]:
    """One WhatsApp message per CRM member with pending payments not followed up."""
    d = data["orders"]
    if d.empty:
        return []
    msgs = []
    for who, g in d[d["stale"]].sort_values("days_since_touch", ascending=False).groupby("owner"):
        names = ", ".join(f"{r['client']} ({_lakh(r['amount_n'])}, {r['days_since_touch']}d)" for _, r in g.head(5).iterrows())
        more = f" and {len(g) - 5} more" if len(g) > 5 else ""
        msgs.append({"to": who, "kind": "payments", "count": len(g),
                     "text": f"{who}: {len(g)} pending payment{'s' if len(g) != 1 else ''} not followed up for "
                             f"{FOLLOWUP_DAYS}+ days — {names}{more}. Please call and update the follow-up form."})
    return msgs


# ====================================================================================== PO follow-up views
ROLES = {"crm": ("owner", "CRM member"), "sp": ("sales_person", "Sales person")}


def _day_word(n: int) -> str:
    return "today" if n == 0 else f"day {n}"


def action_text(r) -> str:
    """What the person should do about one open PO — one short sentence."""
    if r["status_not_updated"]:
        return "Note says paid — set PAYMENT STATUS to RECIEVED"
    n, b = int(r["days_out"]), r["bucket"]
    if r.get("promise_broken"):
        return f"Day {n}, client promised {r['promised']:%d %b} and has not paid — call now"
    if r.get("promise_kept_wait"):
        return f"Day {n}, client promised {r['promised']:%d %b} — wait, then check"
    if r.get("held") and b in ("past_limit", "overdue"):
        return f"Day {n}, part payment ₹{r['part_paid_n']:,.0f} received, on hold — collect the balance ₹{max(r['amount_n'] - r['part_paid_n'], 0):,.0f}"
    if b == "not_sent":
        return "PO not sent yet — send the PO to the client"
    if b == "past_limit":
        return f"Day {n}, past the {LIMIT_DAYS}-day limit — get the payment or confirm the cancel today"
    if b == "overdue":
        return f"Day {n}, overdue — ask the client for a payment date"
    if b == "due_soon":
        left = DUE_DAYS - n
        due = "payment due today" if left == 0 else f"payment due in {left} day{'s' if left != 1 else ''}"
        return f"Day {n}, {due} — call and remind"
    if r["follow_ups"] == 0:
        return f"PO sent {n} day{'s' if n != 1 else ''} ago — first follow-up call"
    if r["stale"]:
        return f"Day {n}, not followed up for {int(r['days_since_touch'])} days — call"
    return f"Day {n}, on track"


def _stats(g: pd.DataFrame) -> dict:
    p = g[g["state"] == "pending"]
    rec = g[g["state"] == "received"]
    can = g[g["state"] == "cancelled"]
    total = g["amount_n"].sum()
    return {
        "pos": len(g), "open": len(p), "open_amt": float(p["amount_n"].sum()),
        "on_track": int((p["bucket"] == "on_track").sum()),
        "due_soon": int((p["bucket"] == "due_soon").sum()), "overdue": int((p["bucket"] == "overdue").sum()),
        "past_limit": int((p["bucket"] == "past_limit").sum()),
        "past_limit_amt": float(p.loc[p["bucket"] == "past_limit", "amount_n"].sum()),
        "not_sent": int((p["bucket"] == "not_sent").sum()),
        "paid": len(rec), "paid_amt": float(rec["amount_n"].sum()),
        "paid_pct": float(rec["amount_n"].sum() / total * 100) if total else 0.0,
        "cancelled": len(can), "cancelled_amt": float(can["amount_n"].sum()),
        "days_to_pay": float(rec["collect_days"].median()) if rec["collect_days"].notna().any() else None,
        "todo": int(g["todo"].sum()), "done_today": int(g["done_today"].sum()),
        "paid_today_amt": float(g.loc[g["paid_today"], "amount_n"].sum()),
        "never": int(((g["state"] == "pending") & (g["follow_ups"] == 0)).sum()),
        "fix": int(g["status_not_updated"].sum()),
        "stale": int(g["stale"].sum()),
    }


def _people(d: pd.DataFrame, role: str) -> list[dict]:
    col, _ = ROLES[role]
    out = []
    for who, g in d.groupby(col):
        out.append({"name": who, **_stats(g)})
    key = (lambda x: (-(x["past_limit"] + x["overdue"]), -x["todo"], x["name"])) if role == "sp" else \
          (lambda x: (-x["todo"], -x["past_limit"], x["name"]))
    return sorted(out, key=key)


def scope_period(d: pd.DataFrame, period: str) -> pd.DataFrame:
    """Keep every paid / cancelled PO, but only the open POs whose age is in `period` (same bands as Orders)."""
    if period not in PERIODS or d.empty:
        return d
    return d[(d["state"] != "pending") | (d["period"] == period)]


def scope_bucket(d: pd.DataFrame, bucket: str) -> pd.DataFrame:
    """Keep every paid / cancelled PO, but only the open POs in one waiting-time box."""
    if bucket not in BUCKET_KEYS or d.empty:
        return d
    return d[(d["state"] != "pending") | (d["bucket"] == bucket)]


def scope_focus(d: pd.DataFrame, focus: str) -> pd.DataFrame:
    """focus='stale': only open POs nobody has followed up for FOLLOWUP_DAYS+ days (paid / cancelled stay counted)."""
    if focus != "stale" or d.empty:
        return d
    return d[(d["state"] != "pending") | d["stale"]]


def periods_summary(d: pd.DataFrame) -> list[dict]:
    pend = d[d["state"] == "pending"] if not d.empty else d
    out = []
    for k, label in PERIOD_LABELS:
        g = pend[pend["period"] == k] if len(pend) else pend
        out.append({"key": k, "label": label, "count": int(len(g)),
                    "amount": float(g["amount_n"].sum()) if len(g) else 0.0})
    return out


def po_overview(data, today=None, period: str = "", bucket: str = "") -> dict:
    """Kavita's view: headline numbers, how many POs sit in each age band, and one row per caller / sales person."""
    today = pd.Timestamp(today) if today is not None else today_ist()
    d = data["orders"]
    win = data.get("window", {})
    base = {"title": "PO follow-up", "notices": data.get("issues", []), "window": win, "rules": {
        "due_days": DUE_DAYS, "limit_days": LIMIT_DAYS}, "period": period if period in PERIODS else "",
        "bucket": bucket if bucket in BUCKET_KEYS else "", "periods": periods_summary(d)}
    d = scope_period(d, period)
    boxes = d                                    # the boxes stay visible when one is chosen
    d = scope_bucket(d, bucket)
    if d.empty:
        return base | {"kpis": [], "buckets": [], "callers": table(pd.DataFrame()), "sales": table(pd.DataFrame()),
                       "people": {"crm": [], "sp": []}}
    pend = d[d["state"] == "pending"]
    late = pend[pend["bucket"].isin(["overdue", "past_limit"])]
    soon = pend[pend["bucket"] == "due_soon"]
    past = pend[pend["bucket"] == "past_limit"]
    paid_t = d[d["paid_today"]]
    kpis = [
        kpi("Open POs", len(pend), hint=_lakh(pend["amount_n"].sum()), id="open"),
        kpi(f"Due in {DUE_DAYS} days", len(soon), hint=_lakh(soon["amount_n"].sum()), tone="warn", id="soon"),
        kpi(f"Overdue ({DUE_DAYS + 1}+ days)", len(late), hint=_lakh(late["amount_n"].sum()), tone="alert", id="late"),
        kpi(f"{LIMIT_DAYS + 1}+ days: at risk", len(past), hint=_lakh(past["amount_n"].sum()), tone="alert", id="past"),
        kpi("Paid today", len(paid_t), hint=_lakh(paid_t["amount_n"].sum()), id="paid_today"),
    ]
    bp = boxes[boxes["state"] == "pending"]
    buckets = [{"key": k, "label": lab, "count": int((bp["bucket"] == k).sum()),
                "amount": float(bp.loc[bp["bucket"] == k, "amount_n"].sum())} for k, lab in BUCKETS]
    people = {r: _people(d, r) for r in ROLES}
    if bucket in BUCKET_KEYS:                    # only people who have POs in this box
        people = {r: [p for p in v if p["open"] > 0] for r, v in people.items()}
    people["crm"] = [p for p in people["crm"] if p["open"] > 0]          # a caller with nothing open is not a to-do
    callers = pd.DataFrame([{
        "CRM member": p["name"], "To call today": p["todo"], "Done today": p["done_today"], "Open": p["open"],
        "Open ₹": round(p["open_amt"]), "Overdue": p["overdue"], f"{LIMIT_DAYS + 1}+ days": p["past_limit"],
        "Never followed up": p["never"], "Status not updated": p["fix"], "Paid today ₹": round(p["paid_today_amt"])}
        for p in people["crm"]])
    sales = pd.DataFrame([{
        "Sales person": p["name"], "POs": p["pos"], "Open": p["open"], "Open ₹": round(p["open_amt"]),
        f"Due in {DUE_DAYS} days": p["due_soon"], "Overdue": p["overdue"], f"{LIMIT_DAYS + 1}+ days": p["past_limit"],
        "Paid %": p["paid_pct"], "Days to pay": p["days_to_pay"], "Cancelled": p["cancelled"],
        "Not followed up": p["stale"]} for p in people["sp"]])
    return base | {
        "kpis": kpis, "buckets": buckets, "people": people,
        "callers": table(callers, sort=False, title="Calling team",
                         fmt={"Open ₹": "inr", "Paid today ₹": "inr"}),
        "sales": table(sales, sort=False, title="Sales people",
                       fmt={"Open ₹": "inr", "Paid %": "pct", "Days to pay": "dec1"}),
    }


def person_rows(data, role: str, name: str, today=None, period: str = "", bucket: str = "", order: str = "", focus: str = "") -> pd.DataFrame:
    """The open POs of one caller / sales person, most urgent first, with what to do about each."""
    d = data["orders"]
    if d.empty or role not in ROLES:
        return pd.DataFrame()
    col, _ = ROLES[role]
    g = d[(d[col].str.casefold() == str(name).strip().casefold()) & (d["state"] == "pending")].copy()
    if period in PERIODS:
        g = g[g["period"] == period]
    if bucket in BUCKET_KEYS:
        g = g[g["bucket"] == bucket]
    if focus == "stale":
        g = g[g["stale"]]
    if g.empty:
        return g
    g["rank"] = g["bucket"].map(_RANK)
    g["action"] = g.apply(action_text, axis=1)
    g["priority"] = g["todo"] | g["status_not_updated"]
    if focus == "stale":                    # the longest without a follow-up first
        return g.sort_values(["days_since_touch", "amount_n"], ascending=[order == "newest", False], kind="stable")
    if order in ("oldest", "newest"):       # by days since the PO went out; POs already followed up today go last
        return g.sort_values(["done_today", "days_out", "amount_n"], ascending=[True, order == "newest", False],
                             kind="stable")
    return g.sort_values(["priority", "rank", "days_out", "amount_n"], ascending=[False, True, False, False],
                         kind="stable")


def person_dashboard(data, role: str, name: str, today=None, period: str = "", bucket: str = "", order: str = "", focus: str = "") -> dict:
    today = pd.Timestamp(today) if today is not None else today_ist()
    d = data["orders"]
    col, label = ROLES[role]
    mine = d[d[col].str.casefold() == str(name).strip().casefold()] if not d.empty else d
    if mine.empty:
        raise KeyError(name)
    st = _stats(scope_bucket(scope_period(mine, period), bucket))
    rows = person_rows(data, role, name, today, period, bucket, order, focus)
    if role == "crm":
        k = [kpi("To call today", st["todo"], hint=_lakh(rows.loc[rows["todo"], "amount_n"].sum()) if len(rows) else "₹0",
                 tone="alert" if st["todo"] else "good", id="todo"),
             kpi("Done today", st["done_today"], id="done"),
             kpi("Open POs", st["open"], hint=_lakh(st["open_amt"]), id="open"),
             kpi(f"Past {LIMIT_DAYS} days", st["past_limit"], hint=_lakh(st["past_limit_amt"]),
                 tone="alert" if st["past_limit"] else None, id="past")]
    else:
        k = [kpi("Open POs", st["open"], hint=_lakh(st["open_amt"]), id="open"),
             kpi("Overdue + past limit", st["overdue"] + st["past_limit"], tone="alert" if st["overdue"] + st["past_limit"] else None, id="late"),
             kpi("Paid", round(st["paid_pct"]), unit="%", hint=f"{st['paid']} POs · {_lakh(st['paid_amt'])}", id="paid"),
             kpi("Cancelled", st["cancelled"], hint=_lakh(st["cancelled_amt"]), id="cancelled")]
    shown = pd.DataFrame()
    if len(rows):
        shown = pd.DataFrame({
            "Client": rows["client"], "PO": rows["so"], "Amount ₹": rows["amount_n"].round(),
            "Sales person" if role == "crm" else "CRM member": rows["sales_person"] if role == "crm" else rows["owner"],
            "Day": rows["days_out"], "Calls": rows["calls"],
            "Promised": [("" if pd.isna(t) else f"{t:%d %b}") for t in rows["promised"]],
            "Part paid ₹": rows["part_paid_n"].round(), "Last follow-up": [("—" if pd.isna(t) else f"{t:%d %b} ({n}d ago)") for t, n in zip(rows["last_touch"], rows["days_since_touch"])],
            "Last note": rows["last_note"], "What to do": rows["action"], "Phone": rows["contact"]})
    tbl = table(shown, sort=False, title=f"{name.title()}: open POs",
                fmt={"Amount ₹": "inr", "PO": "text", "Last follow-up": "text", "Phone": "text", "Day": "int", "Calls": "int",
                              "Promised": "text", "Part paid ₹": "inr"})
    tbl["states"] = [("late" if b in ("overdue", "past_limit") else "due" if b in ("due_soon", "not_sent") else "ok")
                     for b in rows["bucket"]] if len(rows) else []
    tbl["done"] = [bool(x) for x in rows["done_today"]] if len(rows) else []
    return {"role": role, "role_label": label, "name": name.title(), "kpis": k, "stats": st, "table": tbl,
            "count": len(rows), "todo": int(rows["todo"].sum()) if len(rows) else 0}


def person_report(data, role: str, name: str, today=None) -> dict:
    """A one-screen performance report for one sales person or caller: money, age, follow-up health, worst POs."""
    today = pd.Timestamp(today) if today is not None else today_ist()
    d = data["orders"]
    col, label = ROLES[role]
    mine = d[d[col].str.casefold() == str(name).strip().casefold()] if not d.empty else d
    if mine.empty:
        raise KeyError(name)
    st = _stats(mine)
    op = mine[mine["state"] == "pending"]
    recent = mine[mine["created"] >= today.normalize() - pd.Timedelta(days=30)]
    r_paid = recent[recent["state"] == "received"]
    r_total = float(recent["amount_n"].sum())
    ages = [{"key": k, "label": lbl.split(":")[0], "count": int((op["bucket"] == k).sum()),
             "amount": float(op.loc[op["bucket"] == k, "amount_n"].sum())} for k, lbl in BUCKETS]
    ages = list(reversed(ages))                                    # youngest first: 0-4, 5-7, 8-10, 11+
    worst = op[op["bucket"].isin(["overdue", "past_limit"])].sort_values(["days_out", "amount_n"], ascending=False).head(5)
    other_col, other_label = ROLES["crm" if role == "sp" else "sp"]
    split = []
    for who, g in op.groupby(other_col):
        split.append({"name": who, "open": len(g), "amount": float(g["amount_n"].sum()), "stale": int(g["stale"].sum()),
                      "late": int(g["bucket"].isin(["overdue", "past_limit"]).sum())})
    split.sort(key=lambda x: -x["amount"])
    clients = []
    for who, g in op.groupby("client"):
        clients.append({"client": who, "open": len(g), "amount": float(g["amount_n"].sum()), "oldest": int(g["days_out"].max())})
    clients.sort(key=lambda x: -x["amount"])
    calls = float(op["calls"].mean()) if len(op) else 0.0
    out = {
        "role": role, "role_label": label, "name": name.title(),
        "open": {"count": st["open"], "amount": st["open_amt"]},
        "late": {"count": st["overdue"] + st["past_limit"],
                 "amount": float(op.loc[op["bucket"].isin(["overdue", "past_limit"]), "amount_n"].sum())},
        "paid_pct": round(st["paid_pct"]), "paid": {"count": st["paid"], "amount": st["paid_amt"]},
        "cancelled": {"count": st["cancelled"], "amount": st["cancelled_amt"]},
        "days_to_pay": st["days_to_pay"],
        "recent": {"sent": len(recent), "sent_amount": r_total, "paid": len(r_paid), "paid_amount": float(r_paid["amount_n"].sum()),
                   "paid_pct": round(float(r_paid["amount_n"].sum()) / r_total * 100) if r_total else 0},
        "ages": ages,
        "followup": {"not_followed_up": st["stale"], "never_called": st["never"], "status_not_updated": st["fix"],
                     "avg_calls": round(calls, 1), "on_hold": int(op["held"].sum())},
        "worst": [{"client": r["client"], "so": r["so"], "amount": float(r["amount_n"]), "day": int(r["days_out"]),
                   "calls": int(r["calls"]), "note": r["last_note"]} for _, r in worst.iterrows()],
        "clients": clients[:5], "split": split[:8], "split_label": other_label,
    }
    out["summary"] = (
        f"{out['name']} - PO report ({today:%d %b %Y})\n"
        f"Open: {out['open']['count']} POs, {_lakh(out['open']['amount'])}. Overdue or past the limit: {out['late']['count']} POs, {_lakh(out['late']['amount'])}.\n"
        f"Paid so far: {out['paid_pct']}% by value ({out['paid']['count']} POs). Cancelled: {out['cancelled']['count']}.\n"
        f"Last 30 days: {out['recent']['sent']} POs sent ({_lakh(out['recent']['sent_amount'])}), {out['recent']['paid_pct']}% paid.\n"
        + "By age: " + ", ".join(f"{a['label']} {a['count']}" for a in ages) + ".")
    return out


def nudge_rows(data, group: str, scope: str) -> pd.DataFrame:    # scope: todo / overdue / due / all / today / week / month / older
    """Rows for a WhatsApp message to one person. group = 'crm:Kiran' / 'sp:Piyush'; scope picks which POs."""
    role, _, name = str(group).partition(":")
    if role not in ROLES or not name:
        raise KeyError(group)
    g = person_rows(data, role, name)
    if g.empty:
        return g
    if scope == "todo":
        g = g[g["priority"]]
    elif scope == "overdue":
        g = g[g["bucket"].isin(["overdue", "past_limit"])]
    elif scope == "due":
        g = g[g["bucket"] == "due_soon"]
    elif scope == "stale":
        g = g[g["stale"]]
    elif scope in PERIODS:
        g = g[g["period"] == scope]
    elif scope.startswith("b:") and scope[2:] in BUCKET_KEYS:
        g = g[g["bucket"] == scope[2:]]
    elif scope != "all":
        raise ValueError(scope)
    return g


def po_actions(data) -> list[dict]:
    """Home page 'Needs action': one line per caller — how many POs to call today and how many are overdue."""
    d = data["orders"]
    if d.empty:
        return []
    out = []
    for who, g in d.groupby("owner"):
        st = _stats(g)
        late = st["overdue"] + st["past_limit"]
        todo_amt = float(g.loc[g["todo"], "amount_n"].sum())
        if st["todo"] == 0:
            out.append({"who": who, "stage": "Payments", "late": 0, "due": 0, "tone": "good", "oldest_days": 0,
                        "what": "all PO calls done" if st["open"] else "no open POs"})
            continue
        out.append({"who": who, "stage": "Payments", "late": st["todo"], "due": 0,
                    "tone": "bad" if late else "warn", "oldest_days": int(g.loc[g["todo"], "days_out"].max()),
                    "what": f"{st['todo']} PO{'s' if st['todo'] != 1 else ''} to call today ({_lakh(todo_amt)})"
                            + (f", {late} overdue" if late else "")})
    return out
