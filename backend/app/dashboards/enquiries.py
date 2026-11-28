"""Flo-Wing customer-care enquiries (ENQUIRY SHEET 2025-2026).

Three tabs are read, all written by the customer-care team:
  * "daily enquiry update"   - enquiries that arrive by call (DATE & TIME, DATE, CLIENT NAME, Number, ENQUIRY ABOUT,
                                REMARK, SOLVE/ PENDING, FOLLOW UP, Client reply);
  * "BILL T LOGISTIC ENQUIRY" - parcel / transport cases the team picks from a WhatsApp group;
  * "PARTY BILLING ISSUE"     - billing cases picked from the other WhatsApp group.
"NEW DATA", "OLD DATA" and the other tabs are not used.

The dashboard shows the sheet as it is recorded (same rule as Orders): an enquiry is SOLVED when the sheet says so
(any spelling of "solve" / "solved"); every other row is open, whatever the team wrote ("Pending", "in process", or
nothing yet). What an enquiry is about is the team's own text, only tidied for capitals and spaces, so a typo stays a
separate group. Old pending items are not "late": some are lost-parcel claims the team keeps open on purpose, so they
simply show their age and sit under "Older than 30 days".
"""
from __future__ import annotations

import re

import pandas as pd

from ..core import clean_text, norm_key, parse_dates, today_ist
from ..core import idx_to_col
from ..locate import Col, SheetLayoutError, locate, read_table
from ..tables import kpi, notice, table
from .orders import RANGES, in_range

# tab (as named in the sheet) -> label shown on the dashboard
# The real sheet is read through the Flo-Wing Data Mirror (IMPORTRANGE), like the orders: tab in the mirror -> label.
TABS = [
    ("ENQ CALLS", "Calls"),                    # = 'daily enquiry update'
    ("ENQ LOGISTICS", "Logistics group"),      # = 'BILL T LOGISTIC ENQUIRY'
    ("ENQ BILLING", "Billing group"),          # = 'PARTY BILLING ISSUE'
]

ENQ_COLS = [
    Col("created", "DATE & TIME", "TIMESTAMP", required=False),
    Col("date", "DATE", "ENQUIRY DATE", required=False),   # the calls tab has only DATE & TIME
    Col("client", "CLIENT NAME", "PARTY NAME", "CLIENT", expect="text"),
    Col("number", "NUMBER", "PHONE", "CONTACT NO", required=False),
    Col("about", "ENQUIRY ABOUT", "ENQUIRY", "ENQUIRY TYPE"),
    Col("remark", "REMARK", "REMARKS", required=False),
    Col("given", "GIVEN", "GIVEN TO", required=False),
    Col("status", "SOLVE/ PENDING", "SOLVE / PENDING", "STATUS"),
    Col("follow", "FOLLOW UP", "FOLLOW UP -1", "FOLLOW UP 1", required=False),
    Col("reply", "CLIENT REPLY", required=False),
    # added by the team in Nov 2026 (dropdown / typed / filled by script); all optional so old layouts still load
    Col("category", "CATEGORY", required=False),
    Col("assigned", "ASSIGNED TO", "ASSIGNED", required=False),
    Col("bill_no", "BILL NO", "BILL NUMBER", "BILL NO.", required=False),
    Col("solved_on", "SOLVED DATE", "SOLVED ON", required=False),
]

CATEGORIES = ["Parcel tracking / LR / GR", "Parcel problem (transport)", "Article issue", "Short / extra / missing pieces",
              "Rate difference / bill correction", "Invoice / bill / credit note copy", "Payment / ledger / refund",
              "Order / stock / product enquiry", "Party detail update", "Other"]

# First match wins, so the order matters. Words seen in the real sheet (typos included: parcer, dmamage, diffrence...).
_RULES = [
    (CATEGORIES[8], r"address|gst|add number|number into group|number in group|trans\w* change|shipping detail"),
    (CATEGORIES[4], r"wrong bill|bill change|bill me .*(mention|pcs)|rate ?diff|price ?diff|rate issue|rate .*set send|amount ?diff|double order|"
                    r"b+i+l+i*n+g+|ladger"),
    (CATEGORIES[5], r"credit note|debit note|\bcn\b|\bcr note"),
    (CATEGORIES[6], r"payment|ledger|refund|balance|credit amount|cr amount|transport charge|\bcredit\b"),
    (CATEGORIES[1], r"parcel (not|wrong|missing|missed|stolen|delay|rebook|return|exchange|resend)|parc[ea]r delay|(not|wrong) deliver|"
                    r"resend|stolen|transported? query|weight|rebook|wrong parcel|\bgr return|pcs return|miss(ed|ing)? on flo"),
    (CATEGORIES[7], r"du+p+at+a\s+(require|need)|size ?(enqu|avail)"),
    (CATEGORIES[3], r"short|extra|less quantity|missing|miassing|\bpcs? missing"),
    (CATEGORIES[0], r"parc[ea]l|parcer|\blr\b|\bgre?\b|\bgr[a-z]*\b track|track|\bpod\b|dispatch|bilt?y|billty|tracking|meed lr"),
    (CATEGORIES[2], r"dam+a?g|dmam|dmaa|defect|deffect|fade|shade|fitting|barcode|wrong (article|size|pant)|\bsize|article issue|"
                    r"article query|article lost|fabric|colou?r"),
    (CATEGORIES[5], r"invoice|need (urgent |old )?bill|shared bill|bill pdf|old bill|bill (share|copy|require)"),
    (CATEGORIES[7], r"enqu?[ie]+ry|enquery|stock|price|\bpo\b|p\s?\.\s?o\b|add more|need to add|purchase|photoshoot|video call|order|query|require|asking"),
]
_RULES = [(c, re.compile(p, re.I)) for c, p in _RULES]


def auto_category(about: str, remark: str = "") -> str:
    """A best-guess category from what the team typed ('' when both are blank). Used only where CATEGORY is empty."""
    for text in (str(about or ""), str(remark or "")):
        t = re.sub(r"\s+", " ", text.strip())
        if not t:
            continue
        for cat, rx in _RULES:
            if rx.search(t):
                return cat
    return CATEGORIES[-1] if str(about or "").strip() else ""


SOLVED, IN_PROCESS, PENDING, NOT_MARKED = "Solved", "In process", "Pending", "Not marked yet"
STATUS_ORDER = [PENDING, IN_PROCESS, NOT_MARKED, SOLVED]
OLD_DAYS = 30
OTHER_KEY = "other"
NOT_CATEGORISED = "Not categorised yet"
TOP_ABOUT = 10


def status_word(raw: str) -> str:
    """The team's own status word, with only the spelling folded ('solve', 'SOLVED ' -> Solved)."""
    s = str(raw or "").upper()
    if "SOLV" in s:
        return SOLVED
    if "PEND" in s:
        return PENDING
    if "PROCESS" in s:
        return IN_PROCESS
    return NOT_MARKED


def tidy_about(raw: str) -> str:
    """'Parcel  track ' / 'PARCEL TRACK' -> 'Parcel track'. Capitals and spaces only; spelling is left as written."""
    t = re.sub(r"\s+", " ", str(raw or "").strip())
    return (t[:1].upper() + t[1:].lower()) if t else "(not written)"


def slug(label: str) -> str:
    return norm_key(label).lower() or "blank"


def parse_enquiries(tab_grids: list[tuple[str, str, list]], today=None) -> dict:
    """[(tab, label, grid), ...] -> {"enquiries": DataFrame, "issues": [...]} (one row per enquiry)."""
    frames, issues = [], []
    for tab, label, grid in tab_grids:
        try:
            df, _lay = read_table(grid, ENQ_COLS, tab=tab, key_fields=["client", "about"])
        except SheetLayoutError as e:
            issues.append(notice(f"{tab}: layout changed - {', '.join(e.missing)} not found. "
                                 "That tab is left out until it is fixed.", "warning"))
            continue
        df["source"] = label
        frames.append(df)
    cols = [c.field for c in ENQ_COLS] + ["source"]
    if not frames:
        return {"enquiries": pd.DataFrame(columns=cols), "issues": issues}
    d = pd.concat(frames, ignore_index=True)
    for c in [c.field for c in ENQ_COLS]:
        d[c] = clean_text(d[c])
    day = parse_dates(d["date"]).dt.normalize()
    made = parse_dates(d["created"].str.split(" ").str[0]).dt.normalize()
    d["date"] = day.where(day.notna(), made)
    d = d[d["date"].notna()].copy()                       # a row with no date anywhere cannot be placed
    d["status_word"] = d["status"].map(status_word)
    d["solved"] = d["status_word"] == SOLVED
    d["about_tidy"] = d["about"].map(tidy_about)
    # Group by the team's CATEGORY when the row has one; until a row is categorised, by what was typed.
    # The groups are the team's own CATEGORY values from the sheet, nothing guessed. A row with no category yet is
    # listed under "Not categorised yet" so it is easy to find and fill in.
    cat = d["category"].str.replace(r"\s+", " ", regex=True).str.strip()
    d["auto_category"] = False
    d["category"] = cat
    d["group_label"] = cat.map(lambda t: (t[:1].upper() + t[1:]) if t else NOT_CATEGORISED)
    d["about_key"] = d["group_label"].map(slug)
    d["solved_on_dt"] = parse_dates(d["solved_on"]).dt.normalize()
    d["client_tidy"] = d["client"].str.strip()
    today = pd.Timestamp(today).normalize() if today is not None else today_ist().normalize()
    d["days_open"] = (today - d["date"]).dt.days.clip(lower=0).astype(int)
    return {"enquiries": d.reset_index(drop=True), "issues": issues}


# ----------------------------------------------------------------------------------------------- pages
DETAIL_COLUMNS = [("Client", "client_tidy"), ("Date", "date"), ("Days open", "days_open"), ("Source", "source"),
                  ("Category", "category"), ("About", "about_tidy"), ("Status", "status_word"), ("Assigned to", "assigned"),
                  ("Bill no", "bill_no"), ("Remark", "remark"), ("Follow up", "follow"),
                  ("Client reply", "reply"), ("Given to", "given")]


def _open(d: pd.DataFrame) -> pd.DataFrame:
    return d[~d["solved"]]


def _groups(op: pd.DataFrame) -> list[tuple[str, str, pd.DataFrame]]:
    """The open enquiries grouped by what they are about: the biggest groups, the rest as one 'Other'."""
    counts = op["about_key"].value_counts()
    keys = sorted(counts.index, key=lambda k: (op.loc[op["about_key"] == k, "group_label"].iloc[0] == NOT_CATEGORISED, -counts[k]))
    return [(k, op.loc[op["about_key"] == k, "group_label"].iloc[0], op[op["about_key"] == k]) for k in keys]   # every category


def home_dashboard(data, today=None) -> dict:
    d = data["enquiries"]
    today = pd.Timestamp(today).normalize() if today is not None else today_ist().normalize()
    day = d[d["date"] == today]
    op = _open(d)
    counts = {w: int((day["status_word"] == w).sum()) for w in STATUS_ORDER}
    kpis = [
        kpi("Enquired today", len(day), hint=f"{counts[SOLVED]} solved", id="today"),
        kpi("Total open", len(op), hint="all days, not marked Solved", id="open"),
        kpi("Not picked up yet", int(((op["status_word"] == NOT_MARKED) & (op["days_open"] <= OLD_DAYS)).sum()),
            hint=f"no status yet, last {OLD_DAYS} days", id="notpicked"),
        kpi("Older than 30 days", int((op["days_open"] > OLD_DAYS).sum()), hint="still open", id="old"),
    ]
    causes = []
    for key, label, rows in _groups(op):
        causes.append({"key": key, "label": label, "open": len(rows), "today": int((rows["date"] == today).sum()),
                       "older": int((rows["days_open"] > OLD_DAYS).sum()), "oldest_days": int(rows["days_open"].max())})
    by_source = [{"source": s, "open": int((op["source"] == s).sum()), "total": int((d["source"] == s).sum())}
                 for _t, s in TABS]
    auto = int((op["group_label"] == NOT_CATEGORISED).sum())      # open enquiries whose CATEGORY is still blank
    return {"auto_categorised": auto, "kpis": kpis, "today": {"received": len(day), "status": counts}, "causes": causes, "by_source": by_source,
            "total_open": len(op), "notices": data.get("issues", [])}


def open_rows(data, key: str, period: str = "", status: str = "") -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """(rows after the period/status choice, every open row of the group, group title). KeyError for an unknown group."""
    op = _open(data["enquiries"])
    if key == "v-today":                       # everything received today, solved or not
        rows, title = data["enquiries"][data["enquiries"]["days_open"] == 0], "Enquiries received today"
    elif key == "v-old":
        rows, title = op[op["days_open"] > OLD_DAYS], f"Open for more than {OLD_DAYS} days"
    elif key == "v-notpicked":
        rows, title = op[(op["status_word"] == NOT_MARKED) & (op["days_open"] <= OLD_DAYS)], f"Not picked up (no status yet, last {OLD_DAYS} days)"
    elif key == "all":
        rows, title = op, "All open enquiries"
    elif key == OTHER_KEY:
        top = {k for k, _l, _r in _groups(op) if k != OTHER_KEY}
        rows, title = op[~op["about_key"].isin(top)], "Other topics"
    else:
        rows = op[op["about_key"] == key]
        if rows.empty:
            raise KeyError(key)
        title = rows["group_label"].iloc[0]
    total = rows
    if status in STATUS_ORDER:
        rows = rows[rows["status_word"] == status]
    rows = rows[in_range(rows["days_open"], period)] if period in RANGES else rows
    return rows, total, title


def cause_dashboard(data, key: str, today=None, period: str = "", order: str = "oldest", status: str = "") -> dict:
    rows, whole, title = open_rows(data, key, period, status)
    total = len(whole)
    rows = rows.sort_values("date", ascending=(order != "newest"), kind="stable")
    df = pd.DataFrame({name: rows[col] for name, col in DETAIL_COLUMNS})
    df["Date"] = rows["date"].dt.strftime("%d %b %Y").values
    for name in ("Category", "Assigned to", "Bill no", "Remark", "Follow up", "Client reply", "Given to"):     # blank columns say nothing: leave them out
        if not (df[name].astype(str).str.strip() != "").any():
            df = df.drop(columns=name)
    fmt = {c: "text" for c in df.columns if c != "Days open"} | {"Days open": "int"}
    tbl = table(df, fmt=fmt, sort=False, title=title)
    return {"title": title, "table": tbl, "count": len(rows), "total": total}


def suggest_column(grid: list, tab: str = "") -> dict:
    """One value per sheet row under the heading row: the team's own CATEGORY where they filled it, otherwise the
    best guess ('' for a blank row). Pasted into the CATEGORY column from `first_row`, it fills the gaps and keeps
    every category the team chose."""
    lay = locate(grid, ENQ_COLS, tab=tab)
    c = lay.columns
    get = lambda row, f: str(row[c[f]]).strip() if f in c and c[f] < len(row) and row[c[f]] is not None else ""
    values = []
    for row in grid[lay.header_row + 1:]:
        own = get(row, "category")
        values.append(own or auto_category(get(row, "about"), get(row, "remark")))
    while values and values[-1] == "":
        values.pop()
    return {"tab": tab, "first_row": lay.header_row + 2, "column": idx_to_col(c["category"]) if "category" in c else None,
            "values": values}
