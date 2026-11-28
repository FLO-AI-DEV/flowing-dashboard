"""Flo-Wing sales returns (GR): the "Quality Check Sheet" tab of SALES RETURN 2025-2026.

One row per returned barcode: the date the goods came back, the bill they belong to, the client, how many pieces, and
what quality check decided: QC Pass (the goods are fine, the calling team calls the client and the goods go back) or
QC FAIL (a real defect, the return is accepted). The sheet also has a reason text next to the CR number, a Calling
Remark, Return To Client and Return Approved By.

Rules from the team (Nov 2026):
  * QC FAIL pieces are accepted; QC Pass pieces need a call to the client, and the goods go back at the client's cost;
  * a return is accepted only within POLICY_DAYS days of the bill date, and only for a genuine defect;
  * the sheet is not tidy: remarks are missing here and there, and one bill is split over several rows (one per barcode),
    so rows are merged per CR number (else per bill) for the lists.

Headings are found by name (row 1 of the tab is empty, the headings are on row 2), "CR No." appears twice (number, then
the reason the team typed), and the date formats vary (14/02/2025, 06/09/25, 17/3/2026 00:00).
"""
from __future__ import annotations

import re

import pandas as pd

from ..core import month_label, month_sort_key, norm_key, parse_dates, today_ist
from ..tables import kpi, notice, table

TAB = "Quality Check Sheet"
POLICY_DAYS = 90         # a client may return within this many days of the bill
FY_START = pd.Timestamp("2026-04-01")
CALL_BOXES = [("0-2", "0–2 days since received", 0, 2), ("3-7", "3–7 days", 3, 7), ("8-15", "8–15 days", 8, 15),
              ("16+", "16+ days: calling is late", 16, None)]
BOX_KEYS = [k for k, *_ in CALL_BOXES]

# first match wins; words as the team types them (daag/dhag = stain, chhika/fata = torn, hat rha = coming off...)
REASONS = [
    ("Torn / hole / line", re.compile(r"fat|chh?ik|chik|hole|torn|\bcut|line|phat", re.I)),
    ("Stain / mark / colour", re.compile(r"d(aa|h)a?g|stain|mark|colou?r|fade|\bdag\b|rang|daf|dhab", re.I)),
    ("Work / button / stitching", re.compile(r"hat\s*r|hati|button|work|moti|mohi|silai|stitch|thread|dhaga|loose", re.I)),
    ("Wrong / missing / extra piece", re.compile(r"wrong|missing|short|extra|size|less|more", re.I)),
    ("Damage (general)", re.compile(r"dam+a?g|dmam|defect|deffect|bad", re.I)),
]
PCS_OK = re.compile(r"pcs?\.?\s*(sahi|shi|sahi|ok|theek)|use\s*pcs|bill to bill|pieces? ok", re.I)


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(r"[^\d.\-]", "", regex=True), errors="coerce").fillna(0.0)


def reason_group(text: str) -> str:
    t = str(text or "").strip()
    if not t:
        return "(no reason written)"
    for name, rx in REASONS:
        if rx.search(t):
            return name
    return "Other reason"


def parse_returns(grid: list[list], today=None) -> dict:
    """Grid of the Quality Check Sheet tab -> {"lines": DataFrame (one row per barcode line), "issues": [...]}."""
    today = pd.Timestamp(today).normalize() if today is not None else today_ist().normalize()
    issues = []
    head_i = next((i for i, r in enumerate(grid[:15]) if {"CLIENTNAME", "QCPASS"} <= {norm_key(c) for c in r}), None)
    if head_i is None:
        issues.append(notice("The sales return tab has no heading row with CLIENT NAME and QC PASS, so nothing could be read.", "warning"))
        return {"lines": pd.DataFrame(), "issues": issues}
    head = [norm_key(c) for c in grid[head_i]]

    def first(*names, after=None):
        for n in names:
            for i, h in enumerate(head):
                if h == n and (after is None or i > after):
                    return i
        return None

    c = {"date": first("DATE"), "bill": first("BILLNODATE", "BILLNO"), "bill_date": first("BILLDATE"), "days": first("DAYS"),
         "client": first("CLIENTNAME"), "barcode": first("BARCODE"), "color": first("COLOR", "COLOUR"), "qty": first("QTYPCS", "QTY"),
         "pass": first("QCPASS"), "fail": first("QCFAIL"), "cr": first("CRNO"), "calling": first("CALLINGREMARK"),
         "returned": first("RETURNTOCLIENT"), "approved": first("RETURNAPPROVEDBY"), "amount": first("AMOUNT")}
    c["reason"] = first("CRNO", after=c["cr"]) if c["cr"] is not None else None       # the second "CR No." column
    if c["reason"] is None:
        c["reason"] = first("REMARK", "REASON")
    missing = [k for k in ("date", "client", "qty", "pass", "fail") if c[k] is None]
    if missing:
        issues.append(notice(f"The sales return tab is missing the column(s): {', '.join(missing)}.", "warning"))
        return {"lines": pd.DataFrame(), "issues": issues}

    rows = []
    for r in grid[head_i + 1:]:
        get = lambda k: (str(r[c[k]]).strip() if c.get(k) is not None and c[k] < len(r) and r[c[k]] is not None else "")
        if not get("client"):
            continue
        rows.append({k: get(k) for k in c})
    if not rows:
        return {"lines": pd.DataFrame(), "issues": issues}
    d = pd.DataFrame(rows)
    d["date"] = parse_dates(d["date"]).dt.normalize()
    d["bill_date"] = parse_dates(d["bill_date"]).dt.normalize()
    undated = int(d["date"].isna().sum())
    d = d[d["date"].notna()].copy()
    if undated:
        issues.append(notice(f"{undated} row(s) have no readable date and are left out.", "info"))
    d["qty"] = _num(d["qty"])
    d["pass_n"] = _num(d["pass"])
    d["fail_n"] = _num(d["fail"])
    d["unmarked_n"] = (d["qty"] - d["pass_n"] - d["fail_n"]).clip(lower=0)             # QC not written for these pieces
    d["qty"] = d["qty"].where(d["qty"] > 0, d["pass_n"] + d["fail_n"])
    d["amount_n"] = _num(d["amount"])
    d["client"] = d["client"].str.replace(r"\s+", " ", regex=True).str.strip()
    d["bill_key"] = d["bill"].str.upper().str.replace(r"\s+", "", regex=True)
    gap = (d["date"] - d["bill_date"]).dt.days
    d["bill_age"] = gap.where(gap.notna(), _num(d["days"]).where(_num(d["days"]) > 0))   # days from bill to return
    d["over_policy"] = d["bill_age"] > POLICY_DAYS
    d["called"] = d["calling"].str.strip().ne("") | d["returned"].str.strip().ne("")
    d["needs_call"] = d["pass_n"] > 0
    d["call_pending"] = d["needs_call"] & ~d["called"]
    d["since"] = (today - d["date"]).dt.days.clip(lower=0).astype(int)
    d["reason_text"] = d["reason"].str.replace(r"\s+", " ", regex=True).str.strip()
    d["reason_group"] = d["reason_text"].map(reason_group)
    d["cr_key"] = d["cr"].where(d["cr"].str.strip() != "", d["bill_key"] + "|" + d["client"])
    d["month"] = month_label(d["date"])
    if d["over_policy"].any():
        issues.append(notice(f"{int(d['over_policy'].sum())} line(s) came back more than {POLICY_DAYS} days after the bill date (outside the return policy).", "info"))
    return {"lines": d.reset_index(drop=True), "issues": issues}


# ----------------------------------------------------------------------------------------------- pages
def _lakh(x: float) -> str:
    return f"₹{x / 1e5:.1f} L" if x >= 1e5 else f"₹{x:,.0f}"


def _pct(a: float, b: float) -> float:
    return round(a / b * 100, 1) if b else 0.0


def _box(days: int) -> str:
    return next(k for k, _l, lo, hi in CALL_BOXES if days >= lo and (hi is None or days <= hi))


def pending_calls(d: pd.DataFrame) -> pd.DataFrame:
    """The returns still waiting for a calling remark, one row per CR number (several barcodes merged)."""
    p = d[d["call_pending"]]
    if p.empty:
        return pd.DataFrame()
    g = p.groupby("cr_key", sort=False).agg(
        client=("client", "first"), cr=("cr", "first"), bill=("bill", "first"), received=("date", "min"), since=("since", "max"),
        pcs=("pass_n", "sum"), amount=("amount_n", "sum"), reason=("reason_text", lambda s: next((x for x in s if x), "")),
        bill_age=("bill_age", "max"), lines=("barcode", "count")).reset_index(drop=True)
    g["box"] = g["since"].map(_box)
    return g.sort_values(["since", "pcs"], ascending=[False, False])


def returns_dashboard(data, today=None, window: str = "", box: str = "", client: str = "") -> dict:
    today = pd.Timestamp(today).normalize() if today is not None else today_ist().normalize()
    d = data["lines"]
    base = {"title": "Sales returns", "notices": data.get("issues", []), "window": data.get("window", {}),
            "policy_days": POLICY_DAYS, "box": box if box in BOX_KEYS else ""}
    if d.empty:
        return base | {"kpis": [], "boxes": [], "pending": table(pd.DataFrame()), "months": table(pd.DataFrame()),
                       "clients": table(pd.DataFrame()), "reasons": [], "policy": table(pd.DataFrame())}
    pcs, ok, bad, unm = (float(d[k].sum()) for k in ("qty", "pass_n", "fail_n", "unmarked_n"))
    pend = pending_calls(d)
    late = int((pend["since"] >= 16).sum()) if len(pend) else 0
    done_lines = d[d["needs_call"]]
    kpis = [
        kpi("Pieces returned", pcs, hint=f"{d['cr_key'].nunique()} returns · {d['client'].nunique()} clients", id="pcs"),
        kpi("QC pass", ok, hint=f"{_pct(ok, pcs)}% · goods are fine, client is called", id="pass"),
        kpi("QC fail", bad, hint=f"{_pct(bad, pcs)}% · real defect, accepted", id="fail"),
        kpi("QC not written", unm, hint="pieces with no pass or fail", tone="warn" if unm else None, id="unmarked"),
        kpi("Calls pending", len(pend), hint=f"{late} waiting 16+ days · {_lakh(float(pend['amount'].sum())) if len(pend) else '₹0'}",
            tone="alert" if late else None, id="pending"),
        kpi(f"Over {POLICY_DAYS} days", int(d["over_policy"].sum()), hint="lines returned after the policy period", id="policy"),
    ]
    boxes = []
    for k, label, _lo, _hi in CALL_BOXES:
        g = pend[pend["box"] == k] if len(pend) else pend
        boxes.append({"key": k, "label": label, "count": int(len(g)), "pcs": float(g["pcs"].sum()) if len(g) else 0.0,
                      "amount": float(g["amount"].sum()) if len(g) else 0.0})
    shown = pend
    if len(pend) and box in BOX_KEYS:
        shown = pend[pend["box"] == box]
    if len(shown) and client:
        shown = shown[shown["client"].str.casefold() == client.casefold()]
    pt = pd.DataFrame()
    if len(shown):
        pt = pd.DataFrame({
            "Client": shown["client"], "CR": shown["cr"], "Bill": shown["bill"], "Received": shown["received"].dt.strftime("%d %b %Y"),
            "Days waiting": shown["since"], "Pieces to take back": shown["pcs"].astype(int), "Amount ₹": shown["amount"].round(),
            "Reason noted": shown["reason"], "Bill age at return": shown["bill_age"].fillna(0).astype(int)})
    pending_tbl = table(pt.head(300), sort=False, title="Calls still to be made",
                        fmt={"Client": "text", "CR": "text", "Bill": "text", "Received": "text", "Reason noted": "text",
                             "Days waiting": "int", "Amount ₹": "inr"}) if len(pt) else table(pd.DataFrame())
    # by month
    mrows = []
    for m, g in d.groupby("month"):
        n = g[g["needs_call"]]
        mrows.append({"Month": m, "Pieces": int(g["qty"].sum()), "QC pass": int(g["pass_n"].sum()), "QC fail": int(g["fail_n"].sum()),
                      "Fail %": _pct(g["fail_n"].sum(), g["qty"].sum()), "Pass lines called %": _pct(int(n["called"].sum()), len(n)),
                      f"Over {POLICY_DAYS} days": int(g["over_policy"].sum())})
    months = pd.DataFrame(mrows)
    months = months.iloc[sorted(range(len(months)), key=lambda i: month_sort_key(months["Month"].iloc[i]))] if len(months) else months
    # by client
    crow = []
    for who, g in d.groupby("client"):
        crow.append({"Client": who, "Returns": int(g["cr_key"].nunique()), "Pieces": int(g["qty"].sum()), "QC pass": int(g["pass_n"].sum()),
                     "QC fail": int(g["fail_n"].sum()), "Fail %": _pct(g["fail_n"].sum(), g["qty"].sum()),
                     "Calls pending": int(g.loc[g["call_pending"], "cr_key"].nunique()), "Amount ₹": round(g["amount_n"].sum())})
    clients = pd.DataFrame(crow).sort_values("Pieces", ascending=False).head(25) if crow else pd.DataFrame()
    f = d[d["fail_n"] > 0]
    reasons = [{"reason": k, "pcs": int(v)} for k, v in f.groupby("reason_group")["fail_n"].sum().sort_values(ascending=False).items()]
    over = d[d["over_policy"]].sort_values("bill_age", ascending=False).head(50)
    policy = pd.DataFrame({"Client": over["client"], "CR": over["cr"], "Bill": over["bill"], "Received": over["date"].dt.strftime("%d %b %Y"),
                           "Bill age at return": over["bill_age"].astype(int), "Pieces": over["qty"].astype(int), "QC": over.apply(
                               lambda r: "fail" if r["fail_n"] and not r["pass_n"] else "pass" if r["pass_n"] and not r["fail_n"] else "mixed", axis=1),
                           "Reason noted": over["reason_text"]}) if len(over) else pd.DataFrame()
    return base | {
        "kpis": kpis, "boxes": boxes, "reasons": reasons,
        "pending": pending_tbl, "pending_total": int(len(shown)),
        "months": table(months, sort=False, title="By month", fmt={"Month": "text", "Fail %": "pct", "Pass lines called %": "pct"}),
        "clients": table(clients, sort=False, title="Clients with the most returns", fmt={"Client": "text", "Amount ₹": "inr", "Fail %": "pct"}),
        "policy": table(policy, sort=False, title=f"Returned after {POLICY_DAYS} days",
                        fmt={"Client": "text", "CR": "text", "Bill": "text", "Received": "text", "QC": "text", "Reason noted": "text"}),
        "ratios": {"pass_pct": _pct(ok, pcs), "fail_pct": _pct(bad, pcs), "called_pct": _pct(int(done_lines["called"].sum()), len(done_lines)),
                   "policy_pct": _pct(int(d["over_policy"].sum()), len(d))},
    }
