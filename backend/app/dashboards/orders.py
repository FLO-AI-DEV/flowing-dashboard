"""Flo-Wing order sheet (NEW ORDERSHEET-2026-27): parsing, the order pipeline, who is late, and alert messages.

The sheet has one tab per month and channel (NOV CREDIT SALE, NOV CASH SALE, Nov MUMBAI SALE, OCT …). Every tab is
read by heading, never by column letter (app/locate.py), because the tabs differ:
  * CREDIT tabs have headings in row 1 and a count row under them; CASH / MUMBAI have a blank row 1, headings in row 2.
  * Mona's column is "MONA REPLY" on one tab and "BILL/PO BY MONA" on another.
  * Quantities are typed as "4", "1 pcs", "3+6 pcs".
Add a new heading spelling to ORDER_COLS when a tab uses one — never a column letter.

CREDIT orders:        Mona's reply (BILL or PO)  →  PO (only when Mona said PO)  →  Bill DONE.
CASH / MUMBAI orders: PO  →  Bill DONE (no Mona step; PO is skipped only when the row says BILL in Mona's column).
A HOLD REASON parks the order with its sales person. Each stage has an owner and a deadline in days from the order
date (STAGES below). The dashboard pages and the WhatsApp alerts are built from the same `stage_view` so they never
disagree.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from ..core import clean_text, month_label, month_sort_key, now_ist, parse_dates, today_ist
from ..locate import Col, SheetLayoutError, read_table
from ..tables import kpi, notice, table

# ----------------------------------------------------------------------------------------------- configuration
ORDER_COLS = [
    Col("sr", "SR NO.", "SR NO", "S.NO", required=False),
    # JUNE / JULY CREDIT SALE have a blank heading over the dates (next to an empty TIMESTAMP column)
    # NOV CREDIT SALE has blank headings over both SR NO and the dates -> also found as "the column before TIMESTAMP"
    Col("date", "DATE", "ORDER DATE", after="sr", before="timestamp", expect="date"),
    Col("timestamp", "TIMESTAMP", required=False),
    # APR CASH SALE had a client's name typed over this heading -> also found as "the column before ORDER TYPE"
    Col("client", "CLIENT NAME", "PARTY NAME", "CLIENT", before="order_type", expect="text"),
    Col("order_type", "ORDER TYPE", required=False),
    Col("sales_person", "SALES PERSON", "SALESPERSON", "SALES MAN", required=False),
    Col("ledger", "LEDGER", required=False),
    # APR CREDIT SALE has Mona's two columns with blank headings -> "the column after LEDGER" holding BILL / PO
    Col("mona", "MONA REPLY", "BILL/PO BY MONA", "BILL PO BY MONA", required=False, after="ledger",
        expect=("BILL", "PO")),
    # Mona's reply date: its heading is a date ("03/08/2026") or blank, so it is only ever found by position
    Col("mona_time", required=False, after="mona", expect="date"),
    Col("hold_reason", "HOLD REASON", required=False),
    Col("sets", "ORDER (NO. OF SETS)", "ORDER NO OF SETS", "ORDER", required=False),
    Col("pending", "PENDING (NO. OF SETS)", "PENDING", required=False),
    Col("box_reason", "BOX NOT OKAY REASON", required=False),
    Col("po_status", "PO STATUS", required=False),
    Col("po_reason", "PO NOT DONE REASON", required=False),
    Col("po_time", "PO STATUS DATE TIME", "PO STATUS TIME", "PO DATE", required=False),
    Col("bill_status", "BILL STATUS", required=False),
    Col("bill_reason", "BILL NOT DONE REASON", required=False),
    Col("bill_time", "BILL STATUS TIME AND DATE", "BILL STATUS TIME", "BILL DATE", required=False),
]


@dataclass(frozen=True)
class Stage:
    key: str
    waiting: str        # what the order is waiting for, in plain words
    owner: str          # who must act (shown on the dashboard and used for alerts)
    deadline: int       # days after the order date by which this stage should be done
    reason_field: str   # sheet column that explains a delay at this stage


# Owners and deadlines are first guesses: change them here (or confirm with the owner) — nothing else needs editing.
STAGES = [
    Stage("reply", "Mona's reply", "Mona", 1, "hold_reason"),
    Stage("po", "PO", "PO team", 3, "po_reason"),
    Stage("bill", "Billing", "Billing team", 3, "bill_reason"),
]
STAGE = {s.key: s for s in STAGES}
OPEN_WINDOW_DAYS = 45    # an order older than this that was never marked done is a sheet-update gap, not "late work"
OLD_LABEL = "Not marked billed"
HOLD_LABEL = "On hold"
DONE_LABEL = "Billed"
DONE_WORDS = {"DONE", "YES", "OK", "COMPLETE", "COMPLETED", "RECEIVED", "BILLED"}
NO_SALES_PERSON = "(no sales person)"


# ----------------------------------------------------------------------------------------------- parsing
def parse_qty(v) -> float:
    """'4' -> 4, '1 pcs' -> 1, '3+6 pcs' -> 9, '' -> 0. Numbers joined by + are added."""
    s = str(v if v is not None else "").replace(",", "")
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", s)]
    if not nums:
        return 0.0
    return float(sum(nums)) if "+" in s else nums[0]


def tab_channel(tab: str) -> str:
    t = tab.upper()
    return "Mumbai" if "MUMBAI" in t else "Cash" if "CASH" in t else "Credit" if "CREDIT" in t else "Other"


_MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10,
           "NOV": 11, "DEC": 12}


def tab_month(tab: str) -> int | None:
    """'NOV CREDIT SALE' -> 11, 'SEP. CASH SALE' -> 9, 'JULY MUMBAI SALE' -> 7. None when the name has no month."""
    m = re.match(r"\s*([A-Za-z]{3})", tab)
    return _MONTHS.get(m.group(1).upper()) if m else None


def is_recent_tab(tab: str, today=None) -> bool:
    """This month's and last month's tabs change all day; older months rarely do (they are re-read less often)."""
    today = pd.Timestamp(today) if today is not None else today_ist()
    m = tab_month(tab)
    return m is None or m in (today.month, (today.month - 2) % 12 + 1)


def is_order_tab(tab: str) -> bool:
    t = tab.upper()
    return bool(re.search(r"(CREDIT|CASH|MUMBAI)\s*SALE", t)) and "FULL PAYMENT" not in t


def read_order_tab(grid, tab: str):
    """One order tab -> (DataFrame, Layout). Rows without a client name (count rows, blanks, TOTAL) are dropped."""
    df, lay = read_table(grid, ORDER_COLS, tab=tab, key_fields=["client"])
    df["tab"] = tab
    df["channel"] = tab_channel(tab)
    df["sets_n"] = df["sets"].map(parse_qty)
    return df, lay


def _done(s: pd.Series) -> pd.Series:
    return s.map(lambda v: any(w in str(v).upper() for w in DONE_WORDS))


def parse_orders(tab_grids: list[tuple[str, list]]):
    """[(tab, grid), …] -> {"orders": DataFrame, "issues": [notice…], "tabs": [...]}. A tab whose headings can't be
    found is skipped with a notice; the other tabs still load."""
    frames, issues, used = [], [], []
    for tab, grid in tab_grids:
        first = str(grid[0][0]).strip() if grid and grid[0] else ""
        if len(grid) <= 1 and first.upper() in ("#REF!", "#N/A", "#ERROR!", "LOADING...", "LOADING…", ""):
            issues.append(notice(f"{tab}: the mirror is not showing data yet ({first or 'empty'}). Open "
                                 "'Flo-Wing Data Mirror' as ai@floindia.com and click Allow access, or wait for "
                                 "Google to finish loading.", "warning"))
            continue
        try:
            df, _lay = read_order_tab(grid, tab)
        except SheetLayoutError as e:
            issues.append(notice(f"{tab}: layout changed — {', '.join(e.missing)} not found. "
                                 "That tab is left out until it is fixed.", "warning"))
            continue
        used.append(tab)
        if not df.empty:
            frames.append(df)
    if not frames:
        return {"orders": pd.DataFrame(columns=[c.field for c in ORDER_COLS] + ["tab", "channel", "sets_n"]),
                "issues": issues, "tabs": used}
    d = pd.concat(frames, ignore_index=True)
    for c in [c.field for c in ORDER_COLS]:
        d[c] = clean_text(d[c])
    d["date"] = parse_dates(d["date"]).dt.normalize()
    for c in ("bill_time", "po_time", "mona_time"):
        d[c] = parse_dates(d[c]).dt.normalize()
    d["month"] = month_label(d["date"])
    sp = d["sales_person"].str.strip()
    d["sales_person"] = sp.where(sp != "", NO_SALES_PERSON).map(lambda v: v if v == NO_SALES_PERSON else v.title())
    d["client_key"] = d["client"].str.upper().str.replace(r"\s+", " ", regex=True)
    d["billed"] = _done(d["bill_status"])
    mona = d["mona"].str.upper()
    credit = d["channel"] == "Credit"
    d["has_reply_step"] = credit
    d["replied"] = (d["mona"] != "") | ~credit
    says_bill = mona.str.contains("BILL") & ~mona.str.contains("PO")
    says_po = mona.str.contains("PO") & ~mona.str.contains("BILL")
    d["needs_po"] = says_po | (~credit & ~says_bill)
    d["po_done"] = _done(d["po_status"])
    # Done, as the team defines it: an order that goes through a bill is done when BILL STATUS says DONE; an order that
    # goes through a PO (CASH and MUMBAI, and CREDIT orders where Mona said PO because the client pays) is done when
    # PO STATUS says DONE. A DONE bill always counts.
    d["finished"] = d["billed"] | (d["po_done"] & d["needs_po"])
    d["on_hold"] = (d["hold_reason"] != "") & ~d["finished"]
    return {"orders": d, "issues": issues, "tabs": used}


# ----------------------------------------------------------------------------------------------- the pipeline
_SV_MEMO: list = []     # [(source frame, day, result)] - the same numbers are asked for by several pages


def stage_view(d: pd.DataFrame, today=None) -> pd.DataFrame:
    day = pd.Timestamp(today) if today is not None else today_ist()
    for src, dy, res in _SV_MEMO:
        if src is d and dy == day:
            return res
    res = _stage_view(d, day)
    _SV_MEMO.append((d, day, res))
    del _SV_MEMO[:-3]
    return res


def _stage_view(d: pd.DataFrame, today=None) -> pd.DataFrame:
    """Adds, per order: stage (key), waiting (plain words), owner, days_open, deadline, days_late, state
    ("late" / "due" / "ok" / "hold" / "done") and reason."""
    today = pd.Timestamp(today) if today is not None else today_ist()
    v = d.copy()
    stage = pd.Series("bill", index=v.index)
    stage[v["needs_po"] & ~v["po_done"]] = "po"
    stage[~v["replied"]] = "reply"
    stage[v["on_hold"]] = "hold"
    stage[v["finished"]] = "done"
    age = (today - v["date"]).dt.days
    v["cause"] = stage                       # what the order is really waiting for, even when it is very old
    stage[~v["finished"] & (age > OPEN_WINDOW_DAYS)] = "old"
    v["stage"] = stage
    v["waiting"] = stage.map(lambda s: STAGE[s].waiting if s in STAGE else HOLD_LABEL if s == "hold"
                             else OLD_LABEL if s == "old" else DONE_LABEL)
    v["owner"] = [STAGE[s].owner if s in STAGE else (sp if s == "hold" else STAGE["bill"].owner if s == "old" else "")
                  for s, sp in zip(stage, v["sales_person"])]
    v["days_open"] = (today - v["date"]).dt.days.fillna(0).clip(lower=0).astype(int)
    v["deadline"] = stage.map(lambda s: STAGE[s].deadline if s in STAGE else 0).astype(int)
    v["days_late"] = (v["days_open"] - v["deadline"]).where(stage.isin(list(STAGE)), 0).clip(lower=0).astype(int)
    state = pd.Series("ok", index=v.index)
    state[stage.isin(list(STAGE)) & (v["days_open"] == v["deadline"])] = "due"
    state[stage.isin(list(STAGE)) & (v["days_open"] > v["deadline"])] = "late"
    state[stage == "hold"] = "hold"
    state[stage == "done"] = "done"
    state[stage == "old"] = "old"
    v["state"] = state
    v["reason"] = [(r[STAGE[s].reason_field] if s in STAGE else r["hold_reason"] if s == "hold" else "")
                   for s, (_, r) in zip(stage, v.iterrows())]
    v["bill_days"] = (v["bill_time"] - v["date"]).dt.days.where(v["billed"])
    v["po_days"] = (v["po_time"] - v["date"]).dt.days.where(v["po_done"])
    v["reply_days"] = (v["mona_time"] - v["date"]).dt.days.where(v["has_reply_step"] & v["replied"])
    return v


def quality_issues(v: pd.DataFrame) -> pd.DataFrame:
    """Rows that someone forgot to fill properly, with who should fix them (the order's sales person)."""
    checks = [
        (v["sets_n"] <= 0, "no quantity"),
        (v["sales_person"] == NO_SALES_PERSON, "no sales person"),
        (v["date"].isna(), "no date"),
        (v["billed"] & v["bill_time"].isna(), "bill DONE without date"),
        (v["po_done"] & v["po_time"].isna(), "PO DONE without date"),
    ]
    rows = []
    for mask, what in checks:
        for _, r in v[mask].iterrows():
            rows.append({"who": r["sales_person"], "problem": what, "client": r["client"], "tab": r["tab"]})
    return pd.DataFrame(rows, columns=["who", "problem", "client", "tab"])


# ----------------------------------------------------------------------------------------------- filters
def options(data) -> dict:
    d = data["orders"]
    months = sorted([m for m in d["month"].unique() if m != "(NO DATE)"], key=month_sort_key)
    return {"month": months, "channel": sorted(d["channel"].unique().tolist()),
            "sales_person": sorted(d["sales_person"].unique().tolist()),
            "stage": [s.waiting for s in STAGES] + [HOLD_LABEL, OLD_LABEL, DONE_LABEL]}


def _filter(v: pd.DataFrame, f: dict) -> pd.DataFrame:
    for key, col in (("month", "month"), ("channel", "channel"), ("sales_person", "sales_person"),
                     ("stage", "waiting")):
        vals = f.get(key) or []
        if vals:
            v = v[v[col].isin(vals)]
    return v


def _current_month(v: pd.DataFrame, today) -> str:
    return month_label(pd.Series([pd.Timestamp(today)])).iloc[0]


def _tone(n_late: int, n_due: int) -> str:
    return "bad" if n_late else "warn" if n_due else "good"


# ----------------------------------------------------------------------------------------------- pages
def needs_action(v: pd.DataFrame, q: pd.DataFrame) -> list[dict]:
    """One line per person who must act, worst first. Stage owners always appear (green when clear)."""
    open_ = v[v["state"].isin(["late", "due"])]
    out = []
    for s in STAGES:
        rows = open_[open_["stage"] == s.key]
        late, due = rows[rows["state"] == "late"], rows[rows["state"] == "due"]
        oldest = int(rows["days_open"].max()) if len(rows) else 0
        if len(late):
            what = f"{len(late)} order{'s' if len(late) != 1 else ''} late for {s.waiting}"
        elif len(due):
            what = f"{len(due)} due today for {s.waiting}"
        else:
            what = "all on time"
        out.append({"who": s.owner, "stage": s.waiting, "what": what, "late": len(late), "due": len(due),
                    "oldest_days": oldest, "tone": _tone(len(late), len(due))})
    old = v[v["state"] == "old"]
    if len(old):
        out.append({"who": STAGE["bill"].owner, "stage": OLD_LABEL, "late": 0, "due": len(old),
                    "what": f"{len(old):,} orders older than {OPEN_WINDOW_DAYS} days never marked billed in the sheet",
                    "oldest_days": int(old["days_open"].max()), "tone": "warn"})
    people: dict[str, dict] = {}       # sales persons: on-hold orders + incomplete rows, one line each
    hold = v[(v["state"] == "hold") & (v["days_open"] > 2)]
    for who, g in hold.groupby("sales_person"):
        p = people.setdefault(who, {"parts": [], "late": 0, "oldest": 0})
        p["parts"].append(f"{len(g)} order{'s' if len(g) != 1 else ''} on hold over 2 days")
        p["late"] += len(g)
        p["oldest"] = max(p["oldest"], int(g["days_open"].max()))
    for who, g in q.groupby("who"):
        p = people.setdefault(who, {"parts": [], "late": 0, "oldest": 0})
        p["parts"].append(f"{len(g)} row{'s' if len(g) != 1 else ''} to complete "
                          f"({', '.join(sorted(g['problem'].unique()))})")
        p["late"] += len(g)
    for who, p in people.items():
        out.append({"who": who, "stage": "Sales", "what": " · ".join(p["parts"]), "late": p["late"], "due": 0,
                    "oldest_days": p["oldest"], "tone": "warn"})
    rank = {"bad": 0, "warn": 1, "good": 2}
    return sorted(out, key=lambda r: (rank[r["tone"]], -r["late"], -r["oldest_days"]))


CUTOFF_HOUR = 17            # the team's daily close: every bill received by 5 PM should be done today
CAUSE_LABEL = {"reply": "Mona hasn't replied", "po": "PO not done", "bill": "Bill not done", "hold": "On hold"}


def daily_close(v: pd.DataFrame, today, after_cutoff: bool) -> dict:
    """The team's own check, in the sheet's own words: of today's orders, how many are DONE (see `finished`); and what is
    left over from earlier days. For every order not done, the first thing missing in the sheet says what is wrong."""
    mine = v[v["state"] != "old"]
    day = mine[mine["date"] == today]
    back = mine[(mine["date"] < today) & ~mine["finished"]]
    pending = day[~day["finished"]]
    by_channel = [{"channel": ch, "received": len(g), "done": int(g["finished"].sum())}
                  for ch, g in day.groupby("channel")]
    wrong = []
    for key in ("reply", "po", "bill", "hold"):
        b, t = back[back["stage"] == key], pending[pending["stage"] == key]
        if not len(b) and not len(t):
            continue
        owner = STAGE[key].owner if key in STAGE else "Sales person"
        wrong.append({
            "key": key, "label": CAUSE_LABEL[key], "who": owner, "backlog": len(b), "today": len(t),
            "oldest_days": int(b["days_open"].max()) if len(b) else int(t["days_open"].max())})
    wrong.sort(key=lambda w: (-w["backlog"], -w["today"]))
    old = v[v["state"] == "old"]
    return {"received": len(day), "done": int(day["finished"].sum()), "pending": len(pending),
            "backlog": len(back), "after_cutoff": after_cutoff, "cutoff": f"{CUTOFF_HOUR - 12} PM",
            "by_channel": by_channel, "wrong": wrong, "never_marked": len(old)}


# How long ago the order was placed (today = day 0). The last range has no upper end: it also holds every order
# that is older than OPEN_WINDOW_DAYS and so is left out of the counts.
RANGES = {"today": (0, 0), "week": (1, 7), "month": (8, 30), "older": (31, None)}


def in_range(days_open: pd.Series, key: str) -> pd.Series:
    lo, hi = RANGES[key]
    keep = days_open >= lo
    return keep if hi is None else keep & (days_open <= hi)


CAUSE_COLUMNS = {   # the sheet's own columns that matter for each cause, in reading order
    "reply": [("Client", "client"), ("Order date", "date"), ("Days waiting", "days_open"), ("Sales person", "sales_person"),
              ("Channel", "channel"), ("Sets", "sets_n"), ("Hold reason", "hold_reason")],
    "po": [("Client", "client"), ("Order date", "date"), ("Days waiting", "days_open"), ("Sales person", "sales_person"),
           ("Channel", "channel"), ("Sets", "sets_n"), ("Mona said", "mona"), ("PO status", "po_status"),
           ("Reason", "po_reason")],
    "bill": [("Client", "client"), ("Order date", "date"), ("Days waiting", "days_open"), ("Sales person", "sales_person"),
             ("Channel", "channel"), ("Sets", "sets_n"), ("Mona said", "mona"), ("PO status", "po_status"),
             ("Bill status", "bill_status"), ("Reason", "bill_reason")],
    "hold": [("Client", "client"), ("Order date", "date"), ("Days on hold", "days_open"), ("Sales person", "sales_person"),
             ("Channel", "channel"), ("Sets", "sets_n"), ("Reason", "hold_reason")],
}


def cause_dashboard(data, key: str, today=None, period: str = "", order: str = "oldest") -> dict:
    """Every order stuck for one cause, with only the relevant columns. `period` is one of RANGES (when the order was
    placed), so today's orders are not buried under the old ones. Oldest first."""
    if key not in CAUSE_COLUMNS:
        raise KeyError(key)
    v = stage_view(data["orders"], today)
    rows = v[v["cause"] == key]
    total = len(rows)
    rows = rows[in_range(rows["days_open"], period)] if period in RANGES else rows[rows["state"] != "old"]
    rows = rows.sort_values("date", ascending=(order != "newest"), kind="stable")
    cols = CAUSE_COLUMNS[key]
    df = pd.DataFrame({name: rows[col] for name, col in cols})
    df["Order date"] = rows["date"].dt.strftime("%d %b").values
    df["Sets"] = rows["sets_n"].astype(int).values
    for name, col in cols:                      # blank columns carry no information: leave them out
        if name in ("Reason", "Hold reason", "Mona said", "PO status", "Bill status") and not (df[name].astype(str).str.strip() != "").any():
            df = df.drop(columns=name)
    fmt = {c: "text" for c in df.columns if c not in ("Days waiting", "Days on hold", "Sets")}
    tbl = table(df, fmt={**fmt, "Days waiting": "int", "Days on hold": "int", "Sets": "int"}, sort=False, title=CAUSE_LABEL[key])
    return {"title": CAUSE_LABEL[key], "table": tbl, "count": len(rows), "total": total}


def home_dashboard(data, f: dict, today=None, now_hour=None) -> dict:
    after_cutoff = now_hour is not None and now_hour >= CUTOFF_HOUR
    if today is None and now_hour is None:
        now = now_ist()
        after_cutoff = now.hour >= CUTOFF_HOUR
    today = pd.Timestamp(today) if today is not None else today_ist()
    v = stage_view(data["orders"], today)
    f = dict(f)
    if not f.get("month"):
        f["month"] = [_current_month(v, today)]
    scoped = _filter(v, {k: f.get(k) for k in ("channel", "sales_person")})
    month = _filter(scoped, {"month": f["month"]})
    open_all = scoped[~scoped["finished"]]
    late = open_all[open_all["state"] == "late"]
    today_rows = scoped[scoped["date"] == today]
    kpis = [
        kpi("Orders today", len(today_rows), hint=f"{int(today_rows['sets_n'].sum())} sets", id="today"),
        kpi("Orders this month", len(month), hint=f"{int(month['sets_n'].sum())} sets", id="month"),
        kpi("Open orders", int((open_all["stage"] != "old").sum()), hint=f"not billed, last {OPEN_WINDOW_DAYS} days",
            id="open"),
        kpi("Late", len(late), hint="past their deadline", tone="alert", id="late"),
    ]
    pipeline = []
    for s in STAGES:
        rows = open_all[open_all["stage"] == s.key]
        pipeline.append({"key": s.key, "label": f"Waiting for {s.waiting}", "owner": s.owner,
                         "count": len(rows), "late": int((rows["state"] == "late").sum())})
    pipeline.append({"key": "hold", "label": HOLD_LABEL, "owner": "Sales", "count": int((open_all["stage"] == "hold").sum()),
                     "late": 0})
    pipeline.append({"key": "old", "label": f"{OLD_LABEL} (over {OPEN_WINDOW_DAYS} days)", "owner": STAGE["bill"].owner,
                     "count": int((open_all["stage"] == "old").sum()), "late": 0})
    pipeline.append({"key": "done", "label": f"{DONE_LABEL} this month", "owner": "",
                     "count": int(month["finished"].sum()), "late": 0})
    channels = [{"channel": ch, "orders": len(g), "sets": int(g["sets_n"].sum())}
                for ch, g in month.groupby("channel")]
    close = daily_close(scoped, today, after_cutoff)
    return {"title": "Today", "month": f["month"], "kpis": kpis, "close": close, "pipeline": pipeline,
            "actions": needs_action(open_all, quality_issues(month)), "channels": channels,
            "notices": data.get("issues", []), "options": options(data)}


def orders_dashboard(data, f: dict, today=None) -> dict:
    """Open orders (or every order of the chosen stage) placed in the chosen period, newest first."""
    v = _filter(stage_view(data["orders"], today), f)
    period = f.get("range") if f.get("range") in RANGES else ""
    keep_old = period == "older"            # "older than 30 days" shows everything, including never-billed orders
    show = v if f.get("stage") else v[~v["finished"] & ((v["state"] != "old") | keep_old)]
    if f.get("late_only"):
        show = show[show["state"] == "late"]
    if period:
        show = show[in_range(show["days_open"], period)]
    if f.get("days"):                       # placed in the last N days (today counts as day 0)
        show = show[show["days_open"] < int(f["days"])]
    show = show.sort_values("date", ascending=(f.get("order") == "oldest"), kind="stable")   # newest first unless asked
    status = show.apply(lambda r: f"{r['days_late']} day{'s' if r['days_late'] != 1 else ''} late" if r["state"] == "late"
                        else {"due": "due today", "hold": "on hold", "done": "billed",
                              "old": "never marked billed"}.get(r["state"], "on time"), axis=1) \
        if len(show) else pd.Series(dtype=str)
    df = pd.DataFrame({
        "Client": show["client"], "Order date": show["date"].dt.strftime("%d %b"),
        "Sales person": show["sales_person"], "Channel": show["channel"], "Waiting for": show["waiting"],
        "Who must act": show["owner"], "Days open": show["days_open"], "Status": status, "Reason": show["reason"],
    })
    tbl = table(df, fmt={"Order date": "text", "Days open": "int"}, sort=False, title="Orders")
    tbl["states"] = show["state"].tolist()
    kpis = [kpi("Showing", len(show), id="showing"),
            kpi("Late", int((show["state"] == "late").sum()), tone="alert", id="late"),
            kpi("Sets", int(show["sets_n"].sum()), id="sets")]
    return {"title": "Orders", "kpis": kpis, "table": tbl, "options": options(data)}


def team_dashboard(data, f: dict, today=None) -> dict:
    v = _filter(stage_view(data["orders"], today), {k: f.get(k) for k in ("month", "channel")})
    sales_rows = []
    for who, g in v.groupby("sales_person"):
        billed = g[g["billed"]]
        sales_rows.append({"Sales person": who, "Orders": len(g), "Sets": int(g["sets_n"].sum()),
                           "Clients": g["client_key"].nunique(), "Open": int((~g["finished"]).sum()),
                           "Late": int((g["state"] == "late").sum()),
                           "Avg days to bill": round(float(billed["bill_days"].mean()), 1) if billed["bill_days"].notna().any() else None})
    sales = pd.DataFrame(sales_rows).sort_values("Orders", ascending=False) if sales_rows else pd.DataFrame()
    owner_rows = []
    for s in STAGES:
        g = v[v["stage"] == s.key]
        row = {"Who": s.owner, "Stage": s.waiting, "Waiting now": len(g), "Late now": int((g["state"] == "late").sum()),
               "Oldest (days)": int(g["days_open"].max()) if len(g) else 0, "On time %": None, "Usual days": None}
        days = v[f"{s.key}_days"].dropna()
        days = days[days >= 0]
        if len(days):
            row["On time %"] = round(100 * float((days <= s.deadline).mean()), 0)
            row["Usual days"] = float(days.median())
        owner_rows.append(row)
    owners = pd.DataFrame(owner_rows)
    q = quality_issues(v)
    fixes = q.rename(columns={"who": "Who should fix", "problem": "Problem", "client": "Client", "tab": "Tab"})
    return {"title": "Team",
            "sales": table(sales, sort=False, title="Sales team", fmt={"Avg days to bill": "dec1"}),
            "owners": table(owners, sort=False, title="Who is holding orders",
                            fmt={"On time %": "pct", "Stage": "text", "Usual days": "dec1"},
                            rates={"On time %": {"good": 80, "mid": 60}}),
            "fixes": table(fixes, sort=False, title="Rows to complete in the sheet"),
            "options": options(data)}


def clients_dashboard(data, f: dict, today=None) -> dict:
    today = pd.Timestamp(today) if today is not None else today_ist()
    v = _filter(stage_view(data["orders"], today), {k: f.get(k) for k in ("channel", "sales_person")})
    rows = []
    for _, g in v.groupby("client_key"):
        last = g["date"].max()
        rows.append({"Client": g["client"].iloc[-1], "Orders": len(g), "Sets": int(g["sets_n"].sum()),
                     "Open": int((~g["finished"]).sum()), "Sales person": g["sales_person"].mode().iloc[0],
                     "Last order": last.strftime("%d %b") if pd.notna(last) else "",
                     "Days since": int((today - last).days) if pd.notna(last) else None})
    df = pd.DataFrame(rows).sort_values(["Sets", "Orders"], ascending=False) if rows else pd.DataFrame()
    repeat = int((df["Orders"] > 1).sum()) if len(df) else 0
    kpis = [kpi("Clients", len(df), id="clients"), kpi("Ordered more than once", repeat, id="repeat"),
            kpi("Quiet 30+ days", int((df["Days since"].fillna(0) >= 30).sum()) if len(df) else 0, id="quiet")]
    return {"title": "Clients", "kpis": kpis,
            "table": table(df, sort=False, title="Clients", fmt={"Last order": "text", "Sales person": "text"}),
            "options": options(data)}


# ----------------------------------------------------------------------------------------------- alerts
def _names(rows: pd.DataFrame, n=5) -> str:
    parts = [f"{r['client']} ({r['days_open']}d)" for _, r in rows.head(n).iterrows()]
    more = len(rows) - n
    return ", ".join(parts) + (f" and {more} more" if more > 0 else "")


def alerts(data, today=None) -> dict:
    """WhatsApp-ready messages built from the same pipeline the dashboard shows.

    employees: one message per person who has late work (stage owners and sales persons).
    owner    : the morning summary for the owner.
    """
    today = pd.Timestamp(today) if today is not None else today_ist()
    v = stage_view(data["orders"], today)
    open_ = v[~v["finished"]].sort_values("days_open", ascending=False)
    msgs = []
    for s in STAGES:
        rows = open_[(open_["stage"] == s.key) & (open_["state"] == "late")]
        if len(rows):
            msgs.append({"to": s.owner, "kind": "late", "count": len(rows),
                         "text": f"{s.owner}: {len(rows)} order{'s' if len(rows) != 1 else ''} waiting for "
                                 f"{s.waiting} past the {s.deadline}-day deadline — {_names(rows)}. "
                                 "Please update the order sheet."})
    month = v[v["month"] == _current_month(v, today)]
    for who, g in quality_issues(month).groupby("who"):
        if who == NO_SALES_PERSON:
            continue
        msgs.append({"to": who, "kind": "fix", "count": len(g),
                     "text": f"{who}: {len(g)} order row{'s' if len(g) != 1 else ''} need completing — "
                             + "; ".join(f"{r['client']} ({r['problem']}, {r['tab']})" for _, r in g.head(5).iterrows())})
    yday = today - pd.Timedelta(days=1)
    y = v[v["date"] == yday]
    late = open_[open_["state"] == "late"]
    worst = needs_action(open_, quality_issues(month))
    worst = [a for a in worst if a["tone"] != "good"][:3]
    summary = (f"Good morning. Yesterday: {len(y)} orders, {int(y['sets_n'].sum())} sets. "
               f"Open now: {len(open_)}, late: {len(late)}.")
    if worst:
        summary += " Needs attention: " + "; ".join(f"{a['who']} — {a['what']}" for a in worst) + "."
    return {"date": today.strftime("%Y-%m-%d"), "owner": summary, "employees": msgs}
