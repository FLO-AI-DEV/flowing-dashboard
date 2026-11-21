"""Supplier's Enquiry Sheet: several tabs, each a different list the purchase team keeps.

Tabs read (names are matched loosely, see SHEET_REGISTRY["supplier_enquiry"]["tabs"]):
  enquiries  "Sheet1" (titled "Vendor Enquiry Sheet")   one row per supplier enquiry / issue and its follow-up
  city_po    "Supplier's Enquiry Sheet"                 pending POs in side-by-side city blocks (Kolkata, Mumbai…)
  terms      "Terms Approval"                           payment days / discount agreed per supplier and approval
  inactive   "Inactive25-26"                            suppliers with no purchase in 2025-26 (qty bought before)
  issues     "purchase issues"                          purchase problems (date, supplier, issue, design, bill)

Every parser finds its header row by text and its columns by name, and tolerates a missing or empty tab.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from ..core import clean_text, month_label, month_sort_key, norm_key, num, parse_dates
from ..tables import RATE_APPROVAL, kpi, notice, table

CITIES = ["KOLKATA", "MUMBAI", "SURAT", "AHMEDABAD", "JAIPUR", "DELHI", "LUDHIANA", "BANGALORE", "CHENNAI"]
STATUS_ORDER = ["Unsolved", "In process", "No status", "Solved"]

# Topic of an enquiry, from the words in "ENQUIRY ABOUT" (English / Hinglish). First match wins.
TOPICS = [
    ("Missing / short pieces", r"missing|miss\b|\bkm\b|kam recei|short|only \d+ piece|nhi mil|not rece"),
    ("GR / return / defect", r"\bgr\b|return|defect|fad+ed|fatt?a|chhika|rectif|damage|stain"),
    ("Bill / rate / debit note", r"\bbills?\b|\brates?\b|debit|credit note|\bhsn\b|ledger|msme|invoice|\bgst\b|payment"),
    ("PO / order follow-up", r"\bpo\b|order|quantity|qty|size|production|pending"),
    ("Shoot / photos / samples", r"shoot|photo|image|sample|catalog"),
    ("Dispatch / parcel / labels", r"parcel|\blr\b|courier|couriour|transport|dispatch|address|label|lbel"),
    ("Material to be sent", r"magva|mngwa|aayega|bhejn|send|dupatta|pant|tussel|plazo|jewel"),
]


def _find(keys: list[str], *names: str):
    for n in names:
        k = norm_key(n)
        if k in keys:
            return keys.index(k)
    for n in names:
        k = norm_key(n)
        for i, h in enumerate(keys):
            if len(k) >= 4 and h.startswith(k):
                return i
    return None


def _header(grid, must: tuple[str, ...], scan=10):
    for i, row in enumerate(grid[:scan]):
        keys = [norm_key(c) for c in row]
        if all(any(m in k for k in keys) for m in must):
            return i, keys
    return None, []


def _frame(grid, h: int) -> pd.DataFrame:
    width = max(len(r) for r in grid) if grid else 0
    rows = [list(r) + [""] * (width - len(r)) for r in grid[h + 1:]]
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=range(width))


def _col(raw: pd.DataFrame, i):
    return raw[i] if i is not None and i in raw.columns else pd.Series([""] * len(raw), index=raw.index)


def topic_of(text: str) -> str:
    t = str(text or "").lower()
    for name, pat in TOPICS:
        if re.search(pat, t):
            return name
    return "Other" if t.strip() else "(not written)"


def loose_date(text, today: pd.Timestamp):
    """'29-6-2026', '21/07/2026 order', '18 may order', '3 July' -> Timestamp (no year = the most recent such date)."""
    s = str(text or "").strip().lower()
    if not s:
        return pd.NaT
    if re.fullmatch(r"\d{5}(\.\d+)?", s) and 20000 <= float(s) <= 80000:       # a real date cell (sheet serial)
        return pd.Timestamp("1899-12-30") + pd.Timedelta(days=int(float(s)))
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 100 else y
        try:
            return pd.Timestamp(year=y, month=mo, day=d)
        except ValueError:
            return pd.NaT
    m = re.search(r"(\d{1,2})\s*(?:st|nd|rd|th)?\s+([a-z]{3,9})\.?(?:\s+(\d{4}))?", s)
    if m:
        try:
            mo = pd.Timestamp(f"1 {m.group(2)[:3]} 2000").month
        except ValueError:
            return pd.NaT
        y = int(m.group(3)) if m.group(3) else (today.year if mo <= today.month else today.year - 1)
        try:
            return pd.Timestamp(year=y, month=mo, day=int(m.group(1)))
        except ValueError:
            return pd.NaT
    return pd.NaT


# ------------------------------------------------------------------------------------------------ parsers
def parse_enquiries(grid, today: pd.Timestamp) -> pd.DataFrame | None:
    if not grid:
        return None
    h, keys = _header(grid, ("PARTY", "STATUS"))
    if h is None:
        return None
    raw = _frame(grid, h)
    i = {k: _find(keys, *n) for k, n in {
        "no": ("S. NO", "S NO", "SNO"), "date": ("DATE",), "party": ("PARTY NAME", "PARTY", "SUPPLIER"),
        "about": ("ENQUIRY ABOUT", "ENQUIRY", "ISSUE"), "person": ("CONCERNED PERSON", "CONTACT PERSON"),
        "handler": ("Follow Up", "FOLLOWUP BY", "HANDLED BY"), "remarks": ("REMARKS",), "status": ("STATUS",),
    }.items()}
    status_i = i["status"]
    note_cols = [c for c in range((status_i or 0) + 1, raw.shape[1])] if status_i is not None else []
    d = pd.DataFrame({
        "no": clean_text(_col(raw, i["no"])),
        "date": parse_dates(_col(raw, i["date"])),
        "party": clean_text(_col(raw, i["party"])),
        "about": clean_text(_col(raw, i["about"])),
        "person": clean_text(_col(raw, i["person"])),
        "handler": clean_text(_col(raw, i["handler"])).str.title(),
        "remarks": clean_text(_col(raw, i["remarks"])),
        "status_raw": clean_text(_col(raw, status_i)),
    })
    d["notes"] = raw[note_cols].astype(str).apply(lambda r: " · ".join(x.strip() for x in r if x.strip()), axis=1) \
        if note_cols else ""
    # a real enquiry has a party and at least one of: date, what it is about, status
    d = d[(d["party"] != "") & ((d["date"].notna()) | (d["about"] != "") | (d["status_raw"] != ""))].copy()
    s = d["status_raw"].str.upper().str.replace(r"\s+", " ", regex=True)
    d["status"] = np.select([s.str.contains("UNSOLV|NOT SOLV|PENDING"), s.str.contains("SOLV|DONE|CLOSED"),
                             s.str.contains("PROCESS|PROGRESS|WORKING")],
                            ["Unsolved", "Solved", "In process"], default="No status")
    d["open"] = d["status"] != "Solved"
    d["age"] = np.where(d["open"] & d["date"].notna(), (today - d["date"]).dt.days, np.nan)
    d["topic"] = d["about"].map(topic_of)
    d["month"] = month_label(d["date"])
    d["party_key"] = d["party"].str.upper().str.strip()
    d["contact"] = np.where(d["remarks"].str.replace(r"\D", "", regex=True).str.len() >= 10, d["remarks"], "")
    d["handler"] = d["handler"].replace("", "(Not assigned)")
    d["person"] = d["person"].replace("", "-")
    return d.reset_index(drop=True)


def parse_city_po(grid, today: pd.Timestamp) -> pd.DataFrame | None:
    """Side-by-side blocks: '<CITY> PO' | ORDER DATE | STATUS, repeated per city on the first row."""
    if not grid:
        return None
    head = grid[0]
    blocks = []
    for c, v in enumerate(head):
        k = norm_key(v)
        if not k:
            continue
        nxt = norm_key(head[c + 1]) if c + 1 < len(head) else ""
        if "ORDERDATE" in nxt or "DATE" == nxt:
            city = next((x for x in CITIES if x in k), str(v).strip().title())
            blocks.append((c, city.title()))
    if not blocks:
        return None
    out = []
    for r in grid[1:]:
        for c, city in blocks:
            name = str(r[c]).strip() if c < len(r) else ""
            if not name:
                continue
            date_txt = str(r[c + 1]).strip() if c + 1 < len(r) else ""
            status_txt = str(r[c + 2]).strip() if c + 2 < len(r) else ""
            out.append({"city": city, "supplier": name, "date_text": date_txt.replace("\n", " "),
                        "date": loose_date(date_txt, today), "status_raw": status_txt})
    d = pd.DataFrame(out)
    if d.empty:
        return d
    d["status"] = np.where(d["status_raw"].str.upper().str.contains("DONE|ISSUED|COMPLETE|YES"), "PO issued", "Waiting for PO")
    d["age"] = np.where((d["status"] == "Waiting for PO") & d["date"].notna(), (today - d["date"]).dt.days, np.nan)
    return d


def parse_terms(grid) -> pd.DataFrame | None:
    if not grid:
        return None
    h, keys = _header(grid, ("SUPPLIER", "APPROVALSTATUS"))
    if h is None:
        return None
    raw = _frame(grid, h)
    top = [norm_key(c) for c in grid[h - 1]] if h > 0 else []
    i = {k: _find(keys, *n) for k, n in {
        "supplier": ("Supplier",), "code": ("Supplier Code",), "contact": ("Contact Person",),
        "days": ("Payment Days",), "discount": ("Discount",), "other": ("Other Special Terms",),
        "confirmed_by": ("Confirmed by",), "confirmed_on": ("Confirmed on",), "status": ("Approval Status",),
        "approved_by": ("Approved By",), "entry_by": ("Entry by",), "entry_date": ("Entry Date",),
        "checked": ("Entry Checked",)}.items()}
    date_i = top.index("DATE") if "DATE" in top else (keys.index("DATE") if "DATE" in keys else None)
    d = pd.DataFrame({
        "date": parse_dates(_col(raw, date_i)), "supplier": clean_text(_col(raw, i["supplier"])),
        "code": clean_text(_col(raw, i["code"])), "contact": clean_text(_col(raw, i["contact"])),
        "days": clean_text(_col(raw, i["days"])), "discount": clean_text(_col(raw, i["discount"])),
        "other": clean_text(_col(raw, i["other"])), "confirmed_by": clean_text(_col(raw, i["confirmed_by"])).str.title(),
        "confirmed_on": clean_text(_col(raw, i["confirmed_on"])),
        "status_raw": clean_text(_col(raw, i["status"])), "approved_by": clean_text(_col(raw, i["approved_by"])).str.title(),
        "entry_by": clean_text(_col(raw, i["entry_by"])).str.title(), "checked": clean_text(_col(raw, i["checked"])),
    })
    d = d[d["supplier"] != ""].copy()
    s = d["status_raw"].str.upper()
    d["status"] = np.select([s.str.contains("APPROV") & ~s.str.contains("NOT|PEND|REJECT"), s.str.contains("REJECT"),
                             s.str.contains("PEND")], ["Approved", "Rejected", "Pending"], default="Not filled")
    d["terms_missing"] = (d["days"] == "") | (d["discount"] == "")
    d["in_software"] = d["entry_by"] != ""
    return d.reset_index(drop=True)


def parse_simple(grid, must: tuple[str, ...]) -> pd.DataFrame | None:
    """Plain list tabs (inactive suppliers, purchase issues): header row found by text, blank rows dropped."""
    if not grid:
        return None
    h, keys = _header(grid, must)
    if h is None:
        return None
    raw = _frame(grid, h)
    names = []
    for c in range(raw.shape[1]):
        v = str(grid[h][c]).strip() if c < len(grid[h]) else ""
        names.append(v or f"Column {c + 1}")
    raw.columns = names
    raw = raw.loc[:, [c for c in raw.columns if not (c.startswith("Column ") and not raw[c].astype(str).str.strip().any())]]
    raw = raw[raw.astype(str).apply(lambda r: any(x.strip() for x in r), axis=1)]
    return raw.reset_index(drop=True)


def parse_enquiry_sheet(grids: dict, today: pd.Timestamp) -> dict:
    return {
        "enquiries": parse_enquiries(grids.get("enquiries"), today),
        "city_po": parse_city_po(grids.get("city_po"), today),
        "terms": parse_terms(grids.get("terms")),
        "inactive": parse_simple(grids.get("inactive"), ("PARTY",)),
        "issues": parse_simple(grids.get("issues"), ("SUPPLIER", "ISSUE")),
    }


# --------------------------------------------------------------------------------------------- dashboard
def _vals(s: pd.Series) -> list[str]:
    return sorted(v for v in s.unique() if v and v not in ("(BLANK)", "-", "(Not assigned)"))


def enquiry_dashboard(p: dict, f: dict, today: pd.Timestamp) -> dict:
    sections, options, notices = {}, {}, []

    # ---------------------------------------------------------------- enquiries
    e = p.get("enquiries")
    if e is not None and not e.empty:
        options.update({
            "month": sorted([m for m in e["month"].unique() if m != "(NO DATE)"], key=month_sort_key),
            "status": [s for s in STATUS_ORDER if (e["status"] == s).any()],
            "handler": sorted(e["handler"].unique()),
            "topic": [t for t, _ in TOPICS if (e["topic"] == t).any()] + [t for t in ("Other", "(not written)")
                                                                          if (e["topic"] == t).any()],
            "party": sorted(e["party_key"].unique()),
        })
        x = e
        for key, col in (("month", "month"), ("status", "status"), ("handler", "handler"), ("topic", "topic"),
                         ("party", "party_key")):
            if f.get(key):
                x = x[x[col].isin(f[key])]
        opened = x[x["open"]]
        solved = int((x["status"] == "Solved").sum())
        rate = 100 * solved / len(x) if len(x) else 0.0
        oldest = opened.sort_values("age", ascending=False).head(1)
        by_handler = []
        for hname, g in x.groupby("handler"):
            by_handler.append({"Handled by": hname, "Enquiries": len(g), "Pending": int(g["open"].sum()),
                               "Unsolved": int((g["status"] == "Unsolved").sum()),
                               "In process": int((g["status"] == "In process").sum()),
                               "Solved": int((g["status"] == "Solved").sum()),
                               "Solved %": 100 * (g["status"] == "Solved").mean(),
                               "Oldest pending (days)": float(g["age"].max()) if g["age"].notna().any() else 0.0})
        bh = pd.DataFrame(by_handler)
        if not bh.empty:
            bh = bh.sort_values(["Pending", "Enquiries"], ascending=False)
            tot = {"Handled by": "TOTAL", "Enquiries": len(x), "Pending": int(x["open"].sum()),
                   "Unsolved": int((x["status"] == "Unsolved").sum()), "In process": int((x["status"] == "In process").sum()),
                   "Solved": solved, "Solved %": rate,
                   "Oldest pending (days)": float(x["age"].max()) if x["age"].notna().any() else 0.0}
            bh = pd.concat([bh, pd.DataFrame([tot])], ignore_index=True)
        by_party = x.groupby("party_key").agg(Enquiries=("party", "size"), Pending=("open", "sum")).reset_index()
        by_party = by_party.rename(columns={"party_key": "Supplier"}).sort_values(["Pending", "Enquiries"], ascending=False)
        mm = x[x["month"] != "(NO DATE)"].groupby("month").agg(total=("party", "size"), open=("open", "sum"))
        mm = mm.reindex(sorted(mm.index, key=month_sort_key))
        open_tbl = opened.sort_values("age", ascending=False, na_position="last")
        cols = lambda t: pd.DataFrame({  # noqa: E731 - one shape for both enquiry tables
            "Date": t["date"], "Supplier": t["party"], "Enquiry": t["about"], "Topic": t["topic"],
            "Status": t["status"], "Handled by": t["handler"], "Concerned person": t["person"],
            "Days pending": t["age"], "Contact": t["contact"], "Notes": t["notes"]})
        sections["enquiries"] = {
            "kpis": [
                kpi("Enquiries", len(x), "", id="enquiries", hint=f"{x['party_key'].nunique()} suppliers"),
                kpi("Pending enquiries", int(x["open"].sum()), "", id="open", tone="alert",
                    hint="Not solved yet: unsolved, in process or no status"),
                kpi("Unsolved enquiries", int((x["status"] == "Unsolved").sum()), "", id="unsolved", tone="alert"),
                kpi("Enquiries in process", int((x["status"] == "In process").sum()), "", id="in_process"),
                kpi("Solved enquiries", solved, "", id="solved", tone="good"),
                kpi("Solved rate", rate, "", "pct", id="solved_rate"),
            ],
            "summary": {"open": int(x["open"].sum()), "total": int(len(x)),
                        "oldest": None if oldest.empty or pd.isna(oldest.iloc[0]["age"]) else {
                            "party": oldest.iloc[0]["party"], "days": int(oldest.iloc[0]["age"]),
                            "about": oldest.iloc[0]["about"]}},
            "tables": {
                "open": table(cols(open_tbl), {"Date": "date", "Days pending": "int"}, key_col="Days pending", sort=False),
                "all": table(cols(x.sort_values("date", ascending=False, na_position="last")),
                             {"Date": "date", "Days pending": "int"}, sort=False),
                "handlers": table(bh, {"Solved %": "pct", "Oldest pending (days)": "int"}, key_col="Pending", sort=False,
                                  rates={"Solved %": RATE_APPROVAL}),
                "suppliers": table(by_party.head(200), key_col="Pending", sort=False),
            },
            "charts": {
                "status": [{"label": s, "value": float((x["status"] == s).sum())} for s in STATUS_ORDER
                           if (x["status"] == s).any()],
                "topics": [{"label": k, "value": float(v)} for k, v in x["topic"].value_counts().items()],
                "open_by_handler": [{"label": k, "value": float(v)} for k, v in
                                    opened["handler"].value_counts().items()],
                "monthly": {"categories": list(mm.index), "series": [
                    {"name": "Enquiries", "values": [float(v) for v in mm["total"]]},
                    {"name": "Still pending", "values": [float(v) for v in mm["open"]]}]},
            },
        }
    else:
        notices.append(notice("The enquiry log tab (Sheet1 / 'Vendor Enquiry Sheet') was not found or is empty.", "info"))

    # ---------------------------------------------------------------- pending PO by city
    c = p.get("city_po")
    if c is not None and not c.empty:
        options["city"] = sorted(c["city"].unique())
        options["po_status"] = ["Waiting for PO", "PO issued"]
        y = c
        if f.get("city"):
            y = y[y["city"].isin(f["city"])]
        if f.get("po_status"):
            y = y[y["status"].isin(f["po_status"])]
        rows = []
        for city, gg in y.groupby("city"):
            rows.append({"City": city, "Suppliers listed": len(gg), "Waiting for PO": int((gg["status"] == "Waiting for PO").sum()),
                         "PO issued": int((gg["status"] == "PO issued").sum()),
                         "Issued %": 100 * (gg["status"] == "PO issued").mean(),
                         "Oldest pending (days)": float(gg["age"].max()) if gg["age"].notna().any() else 0.0})
        ct = pd.DataFrame(rows)
        if not ct.empty:
            ct = ct.sort_values("Waiting for PO", ascending=False)
            ct = pd.concat([ct, pd.DataFrame([{
                "City": "TOTAL", "Suppliers listed": int(ct["Suppliers listed"].sum()), "Waiting for PO": int(ct["Waiting for PO"].sum()),
                "PO issued": int(ct["PO issued"].sum()),
                "Issued %": 100 * ct["PO issued"].sum() / max(1, ct["Suppliers listed"].sum()),
                "Oldest pending (days)": float(ct["Oldest pending (days)"].max())}])], ignore_index=True)
        lst = y.sort_values(["status", "age"], ascending=[False, False], na_position="last")
        pending = int((y["status"] == "Waiting for PO").sum())
        sections["city_po"] = {
            "kpis": [
                kpi("Suppliers listed", len(y), "", id="listed"),
                kpi("Waiting for PO", pending, "", id="po_pending", tone="alert"),
                kpi("PO issued", int((y["status"] == "PO issued").sum()), "", id="po_done", tone="good"),
                kpi("Cities", y["city"].nunique(), "", id="cities"),
            ],
            "summary": {"pending": pending},
            "tables": {
                "cities": table(ct, {"Issued %": "pct", "Oldest pending (days)": "int"}, key_col="Waiting for PO", sort=False,
                                rates={"Issued %": RATE_APPROVAL}),
                "list": table(pd.DataFrame({"City": lst["city"], "Supplier": lst["supplier"],
                                            "Order date": lst["date"], "As written": lst["date_text"],
                                            "PO status": lst["status"], "Days pending": lst["age"]}),
                              {"Order date": "date", "Days pending": "int"}, sort=False),
            },
            "charts": {
                "pending_by_city": [{"label": k, "value": float(v)} for k, v in
                                    y[y["status"] == "Waiting for PO"]["city"].value_counts().items()],
                "by_city": {"categories": list(ct[ct["City"] != "TOTAL"]["City"]) if not ct.empty else [], "series": [
                    {"name": "PO issued", "values": [float(v) for v in ct[ct["City"] != "TOTAL"]["PO issued"]] if not ct.empty else []},
                    {"name": "Waiting for PO", "values": [float(v) for v in ct[ct["City"] != "TOTAL"]["Waiting for PO"]] if not ct.empty else []}]},
            },
        }

    # ---------------------------------------------------------------- terms approval
    t = p.get("terms")
    if t is not None and not t.empty:
        options["approval"] = [s for s in ("Approved", "Pending", "Not filled", "Rejected") if (t["status"] == s).any()]
        z = t[t["status"].isin(f["approval"])] if f.get("approval") else t
        sections["terms"] = {
            "kpis": [
                kpi("Suppliers", len(z), "", id="terms_suppliers"),
                kpi("Approved", int((z["status"] == "Approved").sum()), "", id="approved", tone="good"),
                kpi("Approval pending", int(z["status"].isin(["Pending", "Not filled"]).sum()), "", id="awaiting",
                    tone="alert"),
                kpi("Terms not filled", int(z["terms_missing"].sum()), "", id="terms_missing", tone="alert",
                    hint="Payment days or discount blank"),
            ],
            "tables": {"terms": table(pd.DataFrame({
                "Date": z["date"], "Supplier": z["supplier"], "Code": z["code"], "Payment days": z["days"],
                "Discount": z["discount"], "Other terms": z["other"], "Confirmed by": z["confirmed_by"],
                "Confirmed on": z["confirmed_on"], "Approval": z["status"], "Approved by": z["approved_by"],
                "Entered by": z["entry_by"]}).sort_values("Date", ascending=False, na_position="last"),
                {"Date": "date", "Payment days": "text", "Code": "text"}, sort=False)},
            "charts": {"status": [{"label": k, "value": float(v)} for k, v in z["status"].value_counts().items()]},
        }

    # ---------------------------------------------------------------- inactive suppliers / purchase issues
    ina = p.get("inactive")
    if ina is not None and not ina.empty:
        party_c = next((c for c in ina.columns if "PARTY" in norm_key(c)), ina.columns[0])
        qty_c = next((c for c in ina.columns if "QTY" in norm_key(c)), None)
        tb = pd.DataFrame({"Supplier": clean_text(ina[party_c])})
        if qty_c:
            tb["Qty bought earlier"] = num(ina[qty_c])
            tb = tb.sort_values("Qty bought earlier", ascending=False)
        tb = tb[tb["Supplier"] != ""]
        sections["inactive"] = {
            "kpis": [kpi("Inactive suppliers", len(tb), "", id="inactive"),
                     *([kpi("Pieces bought from them before", float(tb["Qty bought earlier"].sum()), "pcs", id="inactive_qty")]
                       if qty_c else [])],
            "tables": {"inactive": table(tb, {"Qty bought earlier": "int"}, key_col="Qty bought earlier" if qty_c else None,
                                         sort=False)},
        }
    iss = p.get("issues")
    if iss is not None and not iss.empty:
        sections["issues"] = {"kpis": [kpi("Purchase issues", len(iss), "", id="issues", tone="alert")],
                              "tables": {"issues": table(iss.astype(str), sort=False)}}

    return {"options": options, "notices": notices, "sections": sections, "views": list(sections.keys())}
