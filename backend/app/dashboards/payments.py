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

TAB = "Form responses 1"
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
]

_STAMP = re.compile(r"[—–-]{1,2}\s*(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?\s*[APap][Mm])")
RECEIVED_WORDS = ("RECIEVED", "RECEIVED", "DONE", "PAID")
PAID_NOTE = re.compile(r"\b(PAYMENT\s+DONE|DONE|PAID|RECEIVED|RECIEVED)\b", re.I)


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
    d = d.drop_duplicates("so_key", keep="last") if len(d) else d

    def touches(notes):
        return [(t, ts) for t, ts in notes if pd.notna(ts) and (norm_key(t), ts) not in bulk]

    d["real_notes"] = d["notes"].map(touches)
    d["follow_ups"] = d["real_notes"].map(len)
    d["last_touch"] = d["real_notes"].map(lambda ns: max((ts for _, ts in ns), default=pd.NaT))
    d["last_note"] = d["real_notes"].map(lambda ns: max(ns, key=lambda n: n[1])[0] if ns else "")
    d["paid_at"] = d["real_notes"].map(
        lambda ns: min((ts for t, ts in ns if PAID_NOTE.search(t)), default=pd.NaT))
    st = d["status"].str.upper()
    d["state"] = "pending"
    d.loc[st.str.contains("CANCEL"), "state"] = "cancelled"
    d.loc[st.map(lambda s: any(w in s for w in RECEIVED_WORDS)), "state"] = "received"
    d["amount_n"] = d["amount"].map(_amount)
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
