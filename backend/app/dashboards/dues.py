"""DUES PAYMENT SUPPLIERS: dated dues lists (one tab per payment cycle) + supplier terms ("Updated Sheet").

A dues tab looks like:
    TOTAL DUES UPTO 04-10-2020 FLO WING -(FIFO)            <- title row (optional)
    Date | Ref. No. | Party's Name | Opening | PENDING | Dis. | NET PAYABLE | DUE DAYS | DISCOUNT | DUES ON | (remark)
    one row per bill; rows without a party name are the sheet's own subtotals and are skipped.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..core import clean_text, fmt, norm_key, num, parse_dates
from ..tables import kpi, notice, table, with_total
from . import extra as ex

AGEING = ["Not due", "1-30 days", "31-60 days", "61-90 days", "90+ days"]


def _find(keys, *names):
    for n in names:
        k = norm_key(n)
        if k in keys:
            return keys.index(k)
    for n in names:
        k = norm_key(n)
        for i, h in enumerate(keys):
            if len(k) >= 5 and h.startswith(k):
                return i
    return None


def header_row(grid, scan=15):
    for i, row in enumerate(grid[:scan]):
        keys = [norm_key(c) for c in row]
        if any("PARTY" in k for k in keys) and any("NETPAYABLE" in k or k == "PAYABLE" for k in keys):
            return i
    return None


def is_stale(p, today, days: int = 120) -> bool:
    """True when a parsed dues list has no bill from the last `days` days (an old archive list, not current dues)."""
    if not p or "d" not in p:
        return True
    latest = p["d"]["bill_date"].max() if len(p["d"]) else pd.NaT
    return bool(pd.isna(latest) or (today - latest).days > days)


def parse_terms(grid) -> pd.DataFrame:
    """'Updated Sheet': first column = supplier, then Agency / Days / Discount (%) / Agency Discount."""
    if not grid:
        return pd.DataFrame(columns=["key", "Agency", "Credit Days", "Disc %"])
    keys = [norm_key(c) for c in grid[0]]
    i_ag, i_days, i_disc = _find(keys, "Agency"), _find(keys, "Days"), _find(keys, "Discount (%)", "Discount")
    out = []
    for r in grid[1:]:
        r = list(r) + [""] * (len(keys) + 2 - len(r))
        party = str(r[0]).strip()
        if party:
            out.append({"key": norm_key(party),
                        "Agency": str(r[i_ag]).strip() if i_ag is not None else "",
                        "Credit Days": str(r[i_days]).strip() if i_days is not None else "",
                        "Disc %": str(r[i_disc]).strip() if i_disc is not None else ""})
    return pd.DataFrame(out).drop_duplicates("key") if out else pd.DataFrame(columns=["key", "Agency", "Credit Days", "Disc %"])


def parse_dues(grid, terms_grid=None):
    if not grid:
        return None, "This dues tab is empty."
    h = header_row(grid)
    if h is None:
        return None, "This tab doesn't look like a dues list (no 'Party's Name' and 'Net Payable' header). Pick another tab."
    title = " ".join(str(c).strip() for c in grid[0] if str(c).strip()) if h > 0 else ""
    keys = [norm_key(c) for c in grid[h]]
    idx = {"date": _find(keys, "Date"), "ref": _find(keys, "Ref. No.", "Ref No"),
           "party": _find(keys, "Party's Name", "Party Name", "Party"), "pending": _find(keys, "Pending"),
           "net": _find(keys, "Net Payable"), "due_on": _find(keys, "Dues On", "Due On"),
           "due_days": _find(keys, "Due Days")}
    width = max(len(r) for r in grid)
    rows = [list(r) + [""] * (width - len(r)) for r in grid[h + 1:]]
    raw = pd.DataFrame(rows) if rows else pd.DataFrame(columns=range(width))

    def col(k):
        return raw[idx[k]] if idx[k] is not None else pd.Series([""] * len(raw), index=raw.index)

    d = pd.DataFrame({"bill_date": parse_dates(col("date")), "ref": clean_text(col("ref")),
                      "party": clean_text(col("party")).str.upper(), "net": num(col("net")),
                      "pending": num(col("pending")), "due_on": parse_dates(col("due_on"))})
    remark_i = (idx["due_on"] + 1) if idx["due_on"] is not None and idx["due_on"] + 1 < width else None
    d["remark"] = clean_text(raw[remark_i]) if remark_i is not None else ""
    d = d[d["party"] != ""].reset_index(drop=True)
    d.loc[d["net"] == 0, "net"] = d.loc[d["net"] == 0, "pending"]
    terms = parse_terms(terms_grid or [])
    return {"d": d, "title": title, "terms": terms}, None


def dues_dashboard(p: dict, f: dict, today: pd.Timestamp) -> dict:
    d = p["d"].copy()
    terms = p["terms"]
    d["key"] = d["party"].map(norm_key)
    if not terms.empty:
        d = d.merge(terms, on="key", how="left")
    for c in ("Agency", "Credit Days", "Disc %"):
        if c not in d.columns:
            d[c] = ""
        d[c] = d[c].fillna("").astype(str).str.strip()
    d["Agency"] = d["Agency"].str.upper().replace("", "(NO AGENCY)")
    over = np.where(d["due_on"].notna() & (d["due_on"] < today), (today - d["due_on"]).dt.days, 0)
    left = (d["due_on"] - today).dt.days.where(d["due_on"].notna() & (d["due_on"] >= today))
    d["window"] = np.where(over > 0, ex.overdue_band(pd.Series(over, index=d.index)),
                           np.where(d["due_on"].isna(), "No due date", ex.due_band(left)))
    d["amount_band"] = ex.amount_band(d["net"])
    opts = {"supplier": sorted(d["party"].unique()), "agency": sorted(d["Agency"].unique()),
            "window": [w for w in ex.DUES_WINDOWS if (d["window"] == w).any()],
            "supplier_type": ex.SUPPLIER_TYPES if ex.is_msme(d["party"]).any() else [],
            "amount": [a for a in ex.AMOUNTS if (d["amount_band"] == a).any()], "period": ex.PERIODS}
    x = d
    if f.get("supplier"):
        x = x[x["party"].isin(f["supplier"])]
    if f.get("agency"):
        x = x[x["Agency"].isin(f["agency"])]
    if f.get("window"):
        x = x[x["window"].isin(f["window"])]
    if f.get("amount"):
        x = x[x["amount_band"].isin(f["amount"])]
    if f.get("supplier_type"):
        x = x[ex.supplier_type(x["party"], f["supplier_type"])]
    rng = ex.period_range(f, today)
    if rng:
        x = x[ex.in_period(x["bill_date"], rng)]
    if f.get("q"):
        x = x[ex.search(x, ["party", "ref", "remark", "Agency"], f["q"])]

    notices = []
    if not d.empty and d["bill_date"].notna().any():
        latest = d["bill_date"].max()
        if (today - latest).days > 120:
            notices.append(notice(f"The newest bill on this tab is dated {latest:%d %b %Y}. If the team keeps the "
                                  "current dues on another tab, pick it in 'Dues list' above.", "warning"))
    if x.empty:
        return {"empty": True, "options": opts, "title": p["title"], "notices": notices +
                [notice("No bills match these filters.", "info")], "kpis": [], "summary": {}}

    x = x.copy()
    x["days_overdue"] = np.where(x["due_on"].notna() & (x["due_on"] < today), (today - x["due_on"]).dt.days, 0)
    x["due_in"] = np.where(x["due_on"].notna() & (x["due_on"] >= today), (x["due_on"] - today).dt.days, -1)
    x["age"] = pd.cut(x["days_overdue"], [-1, 0, 30, 60, 90, 10 ** 6], labels=AGEING).astype(str)

    total, overdue = float(x["net"].sum()), float(x.loc[x["days_overdue"] > 0, "net"].sum())
    due7 = float(x.loc[(x["due_in"] >= 0) & (x["due_in"] <= 7), "net"].sum())
    oldest = int(x["days_overdue"].max())

    g = x.groupby("party")
    sup = pd.DataFrame({
        "Bills": g.size(), "Net Payable": g["net"].sum(),
        "Overdue": x[x["days_overdue"] > 0].groupby("party")["net"].sum(),
        "Due in 7 days": x[(x["due_in"] >= 0) & (x["due_in"] <= 7)].groupby("party")["net"].sum(),
        "Oldest Overdue (days)": g["days_overdue"].max()}).fillna(0)
    first = g.first()
    sup["Credit Days"] = first["Credit Days"]
    sup["Disc %"] = first["Disc %"]
    sup["Agency"] = first["Agency"]
    sup.index.name = "Supplier"
    sup = with_total(sup.reset_index(), "Supplier")
    sup.loc[sup["Supplier"] == "TOTAL", "Oldest Overdue (days)"] = oldest

    bills = x.sort_values(["days_overdue", "net"], ascending=[False, False])
    bills_tbl = pd.DataFrame({"Bill Date": bills["bill_date"], "Ref. No.": bills["ref"], "Supplier": bills["party"],
                              "Net Payable": bills["net"], "Due On": bills["due_on"],
                              "Days Overdue": bills["days_overdue"].astype(int), "Remark": bills["remark"]})
    age = x.groupby("age")["net"].sum().reindex(AGEING, fill_value=0)
    ag = x.groupby("Agency")["net"].sum().sort_values(ascending=False)
    ga = x.groupby("Agency")
    agencies = pd.DataFrame({"Suppliers": ga["party"].nunique(), "Bills": ga.size(), "Net Payable": ga["net"].sum(),
                             "Overdue": x[x["days_overdue"] > 0].groupby("Agency")["net"].sum()}).fillna(0)
    agencies.index.name = "Agency"
    agencies = with_total(agencies.reset_index(), "Agency")
    money = {"Net Payable": "inr", "Overdue": "inr", "Due in 7 days": "inr", "Credit Days": "text", "Disc %": "text"}
    return {
        "options": opts,
        "title": p["title"],
        "notices": notices,
        "kpis": [
            kpi("Total net payable", total, "", "inr", id="total", hint=f"{fmt(len(x))} bills · {fmt(x['party'].nunique())} suppliers"),
            kpi("Overdue", overdue, "", "inr", id="overdue", tone="alert", hint="'Dues On' date has passed"),
            kpi("Due in next 7 days", due7, "", "inr", id="due7", hint="plan these payments"),
            kpi("Oldest overdue", oldest, "days", id="oldest", tone="alert"),
        ],
        "summary": {"total": total, "overdue": overdue, "due7": due7, "bills": int(len(x)),
                    "suppliers": int(x["party"].nunique()), "oldest": oldest},
        "tables": {
            "suppliers": table(sup, money, key_col="Net Payable"),
            "agencies": table(agencies, {"Net Payable": "inr", "Overdue": "inr"}, key_col="Net Payable"),
            "bills": table(bills_tbl, {"Net Payable": "inr", "Bill Date": "date", "Due On": "date"},
                           key_col="Days Overdue", sort=False),
        },
        "charts": {
            "ageing": [{"label": k, "value": float(v)} for k, v in age.items()],
            "suppliers": [{"label": k, "value": float(v)} for k, v in g["net"].sum().sort_values(ascending=False).items()],
            "agencies": [{"label": k, "value": float(v)} for k, v in ag.items()],
        },
    }
