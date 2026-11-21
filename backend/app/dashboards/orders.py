"""Order Status (2026-2027) -> "PO Master" tab: one row per PO line.

Columns are found by their header text (the sheet's own spellings are accepted: "vender name", "Recived Amt",
"Pending Order Velue"), so moving columns around never breaks the dashboard.

Delivery status of a line ("timing"):
  On Time               received in full on or before the delivery date
  Delayed               received in full after the delivery date
  Overdue (Pending)     pieces still pending and the delivery date has passed
  Open (Within Deadline) pieces still pending, delivery date not reached yet
  No Date               pieces pending but no delivery date in the sheet
  Nil Order             no quantity / amount on the line yet
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..core import (MONTH_NAME_BY_NUM, clean_delay_days, clean_text, fmt, month_label, month_sort_key, norm_key, num, parse_dates, safe_div_pct)
from ..core import today_ist
from ..tables import RATE_APPROVAL, kpi, notice, table
from . import extra as ex

COLS = {
    "po_date": ["PO / ORDER DATE", "PO DATE", "ORDER DATE", "PO ORDER DATE"],
    "po": ["PO. NO.", "PO NO", "PO NUMBER"],
    "delivery_date": ["DELIVERY DATE"],
    "received_date": ["ACTUAL RECEIVED DATE", "RECEIVED DATE", "RECIVED DATE"],
    "delay_sheet": ["DELAY BY DAY", "DELAY BY DAYS", "DELAY"],
    "vendor": ["VENDER NAME", "VENDOR NAME", "VENDER", "VENDOR", "PARTY NAME", "SUPPLIER"],
    "city": ["CITY"],
    "item": ["ITEM DESCRIPTION", "ITEM"],
    "category": ["CATEGORY"],
    "design": ["DESIGN NO", "DESIGN NO.", "DESIGN"],
    "supplier_design": ["SUPPILER D.NO.", "SUPPLIER D.NO.", "SUPPLIER DESIGN NO"],
    "order_qty": ["ORDER QTY"],
    "po_rate": ["PO RATE"],
    "order_amt": ["ORDER AMT", "ORDER AMOUNT", "ORDER VALUE"],
    "recv_qty": ["RECIVED QTY", "RECEIVED QTY", "RCVD QTY"],
    "recv_amt": ["RECIVED AMT", "RECEIVED AMT", "RCVD AMT"],
    "pending_qty": ["PENDING QTY"],
    "pending_amt": ["PENDING ORDER VELUE", "PENDING ORDER VALUE", "PENDING VALUE", "PENDING AMT"],
    "department": ["DEPARTMENT"],
    "fabric": ["FABRIC"],
    "order_month": ["ORDER MONTH"],
    "delivery_month": ["DELIVERY MONTH"],
    "remark": ["REMARK", "REMARKS"],
}
NEEDED = ["vendor", "order_amt"]
TIMINGS = ["On Time", "Delayed", "Overdue (Pending)", "Open (Within Deadline)", "No Date", "Nil Order"]


def find_header(grid, must=("PO", "PENDING"), scan=20) -> int | None:
    for i, row in enumerate(grid[:scan]):
        keys = [norm_key(c) for c in row]
        if all(any(m in k for k in keys) for m in must):
            return i
    return None


def map_columns(header) -> dict[str, int]:
    keys = [norm_key(h) for h in header]
    out = {}
    for field, names in COLS.items():
        wanted = [norm_key(n) for n in names]
        hit = next((keys.index(w) for w in wanted if w in keys), None)
        if hit is None:  # "starts with" fallback for longer names only
            hit = next((i for w in wanted if len(w) >= 6 for i, k in enumerate(keys) if k.startswith(w)), None)
        if hit is not None:
            out[field] = hit
    return out


def text_month(s) -> str | None:
    """'Apr2026' / 'April 2026' / 'Apr-26' -> 'April-26'."""
    y, m = month_sort_key(s)
    if m == 99 or y >= 9998:
        return None
    return f"{MONTH_NAME_BY_NUM[m]}-{y % 100:02d}"


def parse_orders(grid, today: pd.Timestamp):
    """grid (unformatted values) -> (DataFrame, error)."""
    if not grid:
        return None, "The PO Master tab is empty."
    h = find_header(grid)
    if h is None:
        return None, "Could not find the header row (a row with 'Po. No.' and 'Pending ...') in the PO Master tab."
    cmap = map_columns(grid[h])
    missing = [c for c in NEEDED if c not in cmap]
    if missing:
        return None, f"PO Master is missing columns: {', '.join(missing)}."
    width = max(len(r) for r in grid)
    rows = [list(r) + [""] * (width - len(r)) for r in grid[h + 1:]]
    raw = pd.DataFrame(rows) if rows else pd.DataFrame(columns=range(width))

    def col(field):
        return raw[cmap[field]] if field in cmap else pd.Series([""] * len(raw), index=raw.index)

    d = pd.DataFrame(index=raw.index)
    for f in ("po", "vendor", "city", "item", "category", "design", "supplier_design", "department", "fabric", "remark"):
        d[f] = clean_text(col(f))
    for f in ("order_qty", "po_rate", "order_amt", "recv_qty", "recv_amt"):
        d[f] = num(col(f))
    d["pending_qty"] = num(col("pending_qty")) if "pending_qty" in cmap else (d["order_qty"] - d["recv_qty"]).clip(lower=0)
    d["pending"] = num(col("pending_amt")) if "pending_amt" in cmap else (d["order_amt"] - d["recv_amt"]).clip(lower=0)
    d["delay_sheet"] = clean_delay_days(col("delay_sheet"))
    for f in ("po_date", "delivery_date", "received_date"):
        d[f] = parse_dates(col(f))

    # drop empty lines (no PO number and no vendor)
    d = d[(d["po"] != "") | (d["vendor"] != "")].copy()
    for f in ("vendor", "category", "department", "city"):
        d[f] = d[f].replace("", "(BLANK)").str.upper()

    # month = PO date; fall back to the sheet's ORDER MONTH text
    m = month_label(d["po_date"])
    if "order_month" in cmap:
        alt = clean_text(col("order_month")).loc[d.index].map(text_month)
        m = m.where(m != "(NO DATE)", alt.fillna("(NO DATE)"))
    d["month"] = m
    dm = month_label(d["delivery_date"])
    if "delivery_month" in cmap:
        alt = clean_text(col("delivery_month")).loc[d.index].map(text_month)
        dm = dm.where(dm != "(NO DATE)", alt.fillna("(NO DATE)"))
    d["delivery_month"] = dm

    # delivery status
    nil = (d["order_qty"] <= 0) & (d["order_amt"] <= 0)
    pending = (d["pending_qty"] > 0) | ((d["pending_qty"] == 0) & (d["pending"] > 0) & (d["order_qty"] <= 0))
    has_due = d["delivery_date"].notna()
    late_rcvd = d["received_date"].notna() & has_due & (d["received_date"] > d["delivery_date"])
    late_rcvd = late_rcvd | (d["received_date"].isna() & (d["delay_sheet"] > 0))
    timing = np.select(
        [nil, pending & has_due & (d["delivery_date"] < today), pending & has_due, pending, late_rcvd],
        ["Nil Order", "Overdue (Pending)", "Open (Within Deadline)", "No Date", "Delayed"],
        default="On Time")
    d["timing"] = timing
    d["overdue_days"] = np.where(d["timing"] == "Overdue (Pending)", (today - d["delivery_date"]).dt.days, 0)
    d["delay_days"] = np.where(d["timing"] == "Delayed",
                               np.where(d["received_date"].notna() & has_due,
                                        (d["received_date"] - d["delivery_date"]).dt.days, d["delay_sheet"]), 0)
    # due / delivery window (for the Window filter)
    left = (d["delivery_date"] - today).dt.days
    d["window"] = np.select(
        [d["timing"] == "Overdue (Pending)", d["timing"] == "Open (Within Deadline)", d["timing"] == "No Date",
         d["timing"].isin(["On Time", "Delayed"])],
        [ex.overdue_band(d["overdue_days"]), ex.due_band(left), "No delivery date", "Fully received"], default="")
    d["amount_band"] = ex.amount_band(d["order_amt"])
    d["overdue_amt"] = np.where(d["timing"] == "Overdue (Pending)", d["pending"], 0.0)
    d["overdue_qty"] = np.where(d["timing"] == "Overdue (Pending)", d["pending_qty"], 0.0)
    return d.reset_index(drop=True), None


# --------------------------------------------------------------------------------------------- shared numbers
def stats(g: pd.DataFrame) -> dict:
    done = g["timing"].isin(["On Time", "Delayed"])
    on_time = int((g["timing"] == "On Time").sum())
    delayed = g[g["timing"] == "Delayed"]
    return {
        "Lines": int(len(g)),
        "POs": int(g.loc[g["po"] != "", "po"].nunique()),
        "Ordered": float(g["order_amt"].sum()),
        "Received": float(g["recv_amt"].sum()),
        "Pending": float(g["pending"].sum()),
        "Order Pcs": float(g["order_qty"].sum()),
        "Received Pcs": float(g["recv_qty"].sum()),
        "Pending Pcs": float(g["pending_qty"].sum()),
        "Overdue": float(g["overdue_amt"].sum()),
        "Overdue Pcs": float(g["overdue_qty"].sum()),
        "Overdue Lines": int((g["timing"] == "Overdue (Pending)").sum()),
        "RCVD %": safe_div_pct(g["recv_amt"].sum(), g["order_amt"].sum()),
        "On-Time %": safe_div_pct(on_time, int(done.sum())),
        "Avg Delay (days)": float(delayed["delay_days"].mean()) if len(delayed) else 0.0,
        "Vendors": int(g.loc[g["vendor"] != "(BLANK)", "vendor"].nunique()),
    }


def group_table(x: pd.DataFrame, by: str, label: str, cols: list[str]) -> pd.DataFrame:
    rows = [{label: k, **stats(g)} for k, g in x.groupby(by, sort=False)]
    if not rows:
        return pd.DataFrame(columns=[label] + cols)
    df = pd.DataFrame(rows)
    df = df[df[["Ordered", "Pending", "Lines"]].abs().sum(axis=1) > 0]
    df = pd.concat([df, pd.DataFrame([{label: "TOTAL", **stats(x)}])], ignore_index=True)
    return df[[label] + cols]


def month_axis(d: pd.DataFrame, col="month") -> list[str]:
    present = [m for m in d[col].unique() if m and m != "(NO DATE)"]
    out = sorted(set(present) | set(), key=month_sort_key)
    if (d[col] == "(NO DATE)").any():
        out.append("(NO DATE)")
    return out


def options(d: pd.DataFrame) -> dict:
    def vals(c):
        return sorted(v for v in d[c].unique() if v and v != "(BLANK)")
    return {"month": month_axis(d), "vendor": vals("vendor"), "department": vals("department"),
            "category": vals("category"), "city": vals("city"), "timing": [t for t in TIMINGS if (d["timing"] == t).any()],
            "window": [w for w in ex.ORDER_WINDOWS if (d["window"] == w).any()],
            "supplier_type": ex.SUPPLIER_TYPES if ex.is_msme(d["vendor"]).any() else [],
            "amount": [a for a in ex.AMOUNTS if (d["amount_band"] == a).any()], "period": ex.PERIODS}


SEARCH_COLS = ["po", "vendor", "design", "supplier_design", "item", "category", "department", "city", "fabric", "remark"]


def apply_filters(d: pd.DataFrame, f: dict) -> pd.DataFrame:
    x = d
    for key, col in (("month", "month"), ("vendor", "vendor"), ("department", "department"),
                     ("category", "category"), ("city", "city"), ("timing", "timing"), ("window", "window"),
                     ("amount", "amount_band")):
        if f.get(key):
            x = x[x[col].isin(f[key])]
    rng = ex.period_range(f, today_ist())
    if rng:
        x = x[ex.in_period(x["po_date"], rng)]
    if f.get("supplier_type"):
        x = x[ex.supplier_type(x["vendor"], f["supplier_type"])]
    if f.get("q"):
        x = x[ex.search(x, SEARCH_COLS, f["q"])]
    return x


MONEY = {"Ordered": "inr", "Received": "inr", "Pending": "inr", "Overdue": "inr", "RCVD %": "pct",
         "On-Time %": "pct", "Avg Delay (days)": "dec1"}


def overdue_table(x: pd.DataFrame, limit=300):
    od = x[x["timing"] == "Overdue (Pending)"].sort_values(["overdue_days", "pending"], ascending=[False, False])
    t = pd.DataFrame({
        "PO No.": od["po"], "Vendor": od["vendor"], "Design": np.where(od["design"] != "", od["design"], od["item"]),
        "Category": od["category"], "Delivery Date": od["delivery_date"], "Days Overdue": od["overdue_days"].astype(int),
        "Pending Pcs": od["pending_qty"], "Pending": od["pending"]}).head(limit)
    return len(od), t


# --------------------------------------------------------------------------------------------- Orders page
def orders_dashboard(d: pd.DataFrame, f: dict) -> dict:
    x = apply_filters(d, f)
    opts = options(d)
    if x.empty:
        return {"empty": True, "options": opts, "notices": [notice("No PO lines match these filters.", "info")],
                "kpis": [], "summary": {}}
    s = stats(x)
    n_over, od_tbl = overdue_table(x)
    oldest = x[x["timing"] == "Overdue (Pending)"].sort_values("overdue_days", ascending=False).head(1)

    kpis = [
        kpi("Ordered", s["Ordered"], "", "inr", id="ordered", hint=f"{fmt(s['POs'])} POs · {fmt(s['Vendors'])} vendors"),
        kpi("Received", s["Received"], "", "inr", id="received", tone="good", hint=f"{s['RCVD %']:.1f}% of ordered"),
        kpi("Pending", s["Pending"], "", "inr", id="pending", tone="alert", hint="Still to come in"),
        kpi("Overdue", s["Overdue"], "", "inr", id="overdue", tone="alert", hint=f"{fmt(s['Overdue Lines'])} lines past delivery date"),
        kpi("Overdue POs", int(x.loc[(x["timing"] == "Overdue (Pending)") & (x["po"] != ""), "po"].nunique()), "POs",
            id="overdue_pos", tone="alert", hint=f"{fmt(s['Overdue Lines'])} lines"),
        kpi("Order qty", s["Order Pcs"], "pcs", id="order_qty"),
        kpi("Received qty", s["Received Pcs"], "pcs", id="received_qty", tone="good"),
        kpi("Pending qty", s["Pending Pcs"], "pcs", id="pending_qty", tone="alert"),
        kpi("On-time delivery", s["On-Time %"], "", "pct", id="ontime",
            hint=f"Avg delay when late: {s['Avg Delay (days)']:.1f} days"),
    ]

    axis = [m for m in month_axis(d) if (not f.get("month") or m in f["month"])]
    mm = x.groupby("month")[["order_amt", "recv_amt", "pending"]].sum().reindex(axis, fill_value=0)
    month_tbl = group_table(x, "month", "Month", ["POs", "Lines", "Ordered", "Received", "Pending", "Pending Pcs",
                                                  "Overdue Lines", "RCVD %"])
    if not month_tbl.empty:
        order = {m: i for i, m in enumerate(axis + ["TOTAL"])}
        month_tbl = month_tbl.sort_values("Month", key=lambda c: c.map(lambda v: order.get(v, 999)))

    dm_axis = [m for m in month_axis(x, "delivery_month")]
    dmm = x[x["pending"] > 0].groupby("delivery_month")["pending"].sum().reindex(dm_axis, fill_value=0)
    dmm = dmm[dmm > 0]

    vend = group_table(x, "vendor", "Vendor", ["Lines", "Ordered", "Received", "Pending", "Overdue", "Overdue Lines",
                                               "RCVD %", "On-Time %"])
    vb = vend[vend["Vendor"] != "TOTAL"].sort_values("Pending") if not vend.empty else vend
    cat = group_table(x, "category", "Category", ["Lines", "Ordered", "Received", "Pending", "Pending Pcs", "RCVD %"])
    dep = group_table(x, "department", "Department", ["Lines", "Ordered", "Received", "Pending", "Pending Pcs", "RCVD %"])
    city = group_table(x, "city", "City", ["Lines", "Ordered", "Received", "Pending", "Overdue", "RCVD %"])
    cb = cat[cat["Category"] != "TOTAL"].sort_values("Ordered", ascending=False) if not cat.empty else cat
    tm = x["timing"].value_counts()

    # one row per PO: worst status of its lines
    rank = {"Overdue (Pending)": 0, "Open (Within Deadline)": 1, "No Date": 2, "Delayed": 3, "On Time": 4, "Nil Order": 5}
    px = x[x["po"] != ""]
    if not px.empty:
        gp = px.groupby("po", sort=False)
        pos = pd.DataFrame({
            "PO No.": list(gp.groups.keys()),
            "Vendor": gp["vendor"].first().values, "PO Date": gp["po_date"].min().values,
            "Delivery Date": gp["delivery_date"].max().values, "Lines": gp.size().values,
            "Ordered": gp["order_amt"].sum().values, "Received": gp["recv_amt"].sum().values,
            "Pending": gp["pending"].sum().values, "Pending Pcs": gp["pending_qty"].sum().values,
            "Days Overdue": gp["overdue_days"].max().values,
            "Status": gp["timing"].agg(lambda s: min(s, key=lambda v: rank.get(v, 9))).values})
        pos = pos.sort_values(["Days Overdue", "Pending"], ascending=[False, False])
    else:
        pos = pd.DataFrame()

    return {
        "options": opts,
        "notices": [],
        "kpis": kpis,
        "summary": {"overdue_lines": s["Overdue Lines"], "pending_pcs": s["Pending Pcs"], "pending": s["Pending"],
                    "overdue": s["Overdue"], "vendors": s["Vendors"],
                    "oldest": None if oldest.empty else {"po": oldest.iloc[0]["po"], "vendor": oldest.iloc[0]["vendor"],
                                                         "days": int(oldest.iloc[0]["overdue_days"])}},
        "tables": {
            "monthly": table(month_tbl, MONEY, key_col="Pending", sort=False, rates={"RCVD %": RATE_APPROVAL}),
            "vendors": table(vend, MONEY, key_col="Pending", rates={"RCVD %": RATE_APPROVAL, "On-Time %": RATE_APPROVAL}),
            "categories": table(cat, MONEY, key_col="Pending", rates={"RCVD %": RATE_APPROVAL}),
            "departments": table(dep, MONEY, key_col="Pending", rates={"RCVD %": RATE_APPROVAL}),
            "cities": table(city, MONEY, key_col="Pending", rates={"RCVD %": RATE_APPROVAL}),
            "overdue": table(od_tbl, {"Pending": "inr", "Delivery Date": "date"}, key_col="Days Overdue"),
            "pos": table(pos, {"Ordered": "inr", "Received": "inr", "Pending": "inr", "PO Date": "date",
                               "Delivery Date": "date"}, key_col="Pending", sort=False),
        },
        "overdue_total": int(n_over),
        "charts": {
            "monthly": {"categories": list(mm.index), "series": [
                {"name": "Ordered", "values": [float(v) for v in mm["order_amt"]]},
                {"name": "Received", "values": [float(v) for v in mm["recv_amt"]]},
                {"name": "Pending", "values": [float(v) for v in mm["pending"]]}]},
            "receivable": {"categories": list(dmm.index), "series": [
                {"name": "Pending", "values": [float(v) for v in dmm.values]}]},
            "vendors": {"categories": list(vb["Vendor"]) if not vb.empty else [], "series": [
                {"name": "Received", "values": [float(v) for v in vb["Received"]] if not vb.empty else []},
                {"name": "Pending", "values": [float(v) for v in vb["Pending"]] if not vb.empty else []}]},
            "categories": {"categories": list(cb["Category"]) if not cb.empty else [], "series": [
                {"name": "Ordered", "values": [float(v) for v in cb["Ordered"]] if not cb.empty else []},
                {"name": "Received", "values": [float(v) for v in cb["Received"]] if not cb.empty else []},
                {"name": "Pending", "values": [float(v) for v in cb["Pending"]] if not cb.empty else []}]},
            "timing": [{"label": t, "value": float(tm.get(t, 0))} for t in TIMINGS if tm.get(t, 0)],
        },
    }


# --------------------------------------------------------------------------------------------- Vendors page
def vendors_dashboard(d: pd.DataFrame, f: dict) -> dict:
    x = apply_filters(d, f)
    opts = options(d)
    if x.empty:
        return {"empty": True, "options": opts, "notices": [notice("No PO lines match these filters.", "info")],
                "kpis": [], "summary": {}}
    vend = group_table(x, "vendor", "Vendor", ["Lines", "POs", "Ordered", "Received", "Pending", "Pending Pcs",
                                               "Overdue", "Overdue Lines", "RCVD %", "On-Time %", "Avg Delay (days)"])
    city = x.groupby("vendor")["city"].agg(lambda s: next((c for c in s if c and c != "(BLANK)"), ""))
    vend.insert(1, "City", vend["Vendor"].map(city).fillna(""))
    body = vend[vend["Vendor"] != "TOTAL"]
    late = body[body["Overdue Lines"] > 0]
    rated = []
    for v, g in x.groupby("vendor"):
        done = int(g["timing"].isin(["On Time", "Delayed"]).sum())
        if done >= 3:
            rated.append((v, safe_div_pct(int((g["timing"] == "On Time").sum()), done), done))
    rated.sort(key=lambda r: (-r[1], -r[2]))
    s = stats(x)
    kpis = [
        kpi("Vendors", len(body), "", id="vendors"),
        kpi("Vendors running late", len(late), "", id="late_vendors", tone="alert", hint="With PO lines past delivery date"),
        kpi("Pending with vendors", s["Pending"], "", "inr", id="pending", tone="alert"),
        kpi("Overdue", s["Overdue"], "", "inr", id="overdue", tone="alert"),
        kpi("On-time delivery", s["On-Time %"], "", "pct", id="ontime"),
        kpi("Avg delay when late", s["Avg Delay (days)"], "days", "dec1", id="avg_delay"),
    ]
    vb = body.sort_values("Pending")
    return {
        "options": opts,
        "notices": [] if rated else [notice("On-time % needs 'Actual Received Date' (or 'Delay By Day') filled in; "
                                            "it appears as receipts are entered.", "info")],
        "kpis": kpis,
        "summary": {"late_vendors": int(len(late)), "vendors": int(len(body)),
                    "most_overdue": None if late.empty else {"name": late.sort_values("Overdue").iloc[-1]["Vendor"],
                                                              "value": float(late["Overdue"].max())},
                    "most_pending": None if body.empty else {"name": body.sort_values("Pending").iloc[-1]["Vendor"],
                                                              "value": float(body["Pending"].max())},
                    "most_reliable": None if not rated else {"name": rated[0][0], "value": rated[0][1]}},
        "tables": {"scorecard": table(vend, MONEY, key_col="Pending",
                                      rates={"RCVD %": RATE_APPROVAL, "On-Time %": RATE_APPROVAL})},
        "charts": {
            "pending": {"categories": list(vb["Vendor"]), "series": [
                {"name": "Received", "values": [float(v) for v in vb["Received"]]},
                {"name": "Pending", "values": [float(v) for v in vb["Pending"]]}]},
            "overdue": [{"label": r["Vendor"], "value": float(r["Overdue"])} for _, r in late.iterrows()],
            "ontime": [{"label": v, "value": p} for v, p, _ in rated],
        },
    }
