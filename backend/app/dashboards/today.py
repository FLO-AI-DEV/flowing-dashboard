"""Today page: what happened today and in the last 7 days, and what is due today and in the next 7 days, across the
four sheets. Every number is counted from the same parsed data the other pages use.

Each section has an "area" so the "View as" filter can show only what a team works on (see overview.ROLES).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..core import fmt, inr_short, norm_key
from ..tables import kpi, notice, table
from .generic import _col, grid_frame, typed
from .overview import ROLES


def _day(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce").dt.normalize()


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{fmt(n)} {one if n == 1 else (many or one + 's')}"


def today_dashboard(sources: dict, now: pd.Timestamp, role: str = "") -> dict:
    t = pd.Timestamp(now).tz_localize(None).normalize() if pd.Timestamp(now).tzinfo else pd.Timestamp(now).normalize()
    week_ago, week_ahead = t - pd.Timedelta(days=6), t + pd.Timedelta(days=7)
    sections, lede = [], []

    # ---------------------------------------------------------------- orders (Order Status → PO Master)
    d, _ = sources.get("order_status", (None, None))
    if d is not None and not d.empty:
        po_day, rc_day, due_day = _day(d["po_date"]), _day(d["received_date"]), _day(d["delivery_date"])
        pending = d["timing"].isin(["Overdue (Pending)", "Open (Within Deadline)", "No Date"])
        raised_today = d[po_day == t]
        raised_week = d[(po_day >= week_ago) & (po_day <= t)]
        rcvd_today = d[rc_day == t]
        rcvd_week = d[(rc_day >= week_ago) & (rc_day <= t)]
        due_today = d[pending & (due_day == t)]
        due_week = d[pending & (due_day >= t) & (due_day <= week_ahead)]
        newly_late = d[pending & (due_day >= week_ago) & (due_day < t)]
        sections.append({
            "id": "orders", "area": "orders", "title": "Orders and deliveries", "sub": "Order Status sheet → PO Master",
            "link": "/orders",
            "kpis": [
                kpi("POs raised today", raised_today["po"].replace("", np.nan).nunique(), "",
                    hint=f"{inr_short(raised_today['order_amt'].sum())} ordered", id="raised_today"),
                kpi("POs raised in last 7 days", raised_week["po"].replace("", np.nan).nunique(), "",
                    hint=f"{inr_short(raised_week['order_amt'].sum())} ordered", id="raised_week"),
                kpi("Received today", float(rcvd_today["recv_qty"].sum()), "pcs",
                    hint=f"{_plural(len(rcvd_today), 'line')} · {inr_short(rcvd_today['recv_amt'].sum())}", id="rcvd_today"),
                kpi("Received in last 7 days", float(rcvd_week["recv_qty"].sum()), "pcs",
                    hint=f"{_plural(len(rcvd_week), 'line')} · {inr_short(rcvd_week['recv_amt'].sum())}", id="rcvd_week"),
                kpi("Deliveries due today", len(due_today), "", tone="alert" if len(due_today) else None,
                    hint=f"{fmt(due_today['pending_qty'].sum())} pcs · {inr_short(due_today['pending'].sum())}",
                    id="due_today"),
                kpi("Due within 7 days", len(due_week), "",
                    hint=f"{fmt(due_week['pending_qty'].sum())} pcs · {inr_short(due_week['pending'].sum())}", id="due_week"),
                kpi("Became overdue this week", len(newly_late), "", tone="alert" if len(newly_late) else None,
                    hint="Delivery date passed in the last 7 days, still pending", id="newly_late"),
                kpi("Overdue now", int((d["timing"] == "Overdue (Pending)").sum()), "", id="overdue_now",
                    tone="alert" if (d["timing"] == "Overdue (Pending)").any() else None,
                    hint=f"{inr_short(d['overdue_amt'].sum())} past delivery date"),
            ],
            "tables": [
                {"title": "Deliveries due today and in the next 7 days", "sub": "Still pending · earliest first",
                 "table": table(pd.DataFrame({
                     "Delivery Date": due_week["delivery_date"], "PO No.": due_week["po"], "Vendor": due_week["vendor"],
                     "Design": np.where(due_week["design"] != "", due_week["design"], due_week["item"]),
                     "Pending Pcs": due_week["pending_qty"], "Pending": due_week["pending"]}).sort_values("Delivery Date"),
                     {"Delivery Date": "date", "Pending": "inr"}, sort=False)},
                {"title": "Became overdue in the last 7 days", "sub": "Follow these up now",
                 "table": table(pd.DataFrame({
                     "Delivery Date": newly_late["delivery_date"], "PO No.": newly_late["po"], "Vendor": newly_late["vendor"],
                     "Pending Pcs": newly_late["pending_qty"], "Pending": newly_late["pending"]}).sort_values("Delivery Date"),
                     {"Delivery Date": "date", "Pending": "inr"}, sort=False)},
                {"title": "Goods received in the last 7 days", "sub": "Newest first",
                 "table": table(pd.DataFrame({
                     "Received Date": rcvd_week["received_date"], "PO No.": rcvd_week["po"], "Vendor": rcvd_week["vendor"],
                     "Received Pcs": rcvd_week["recv_qty"], "Received": rcvd_week["recv_amt"],
                     "Status": rcvd_week["timing"]}).sort_values("Received Date", ascending=False),
                     {"Received Date": "date", "Received": "inr", "Status": "text"}, sort=False)},
                {"title": "POs raised in the last 7 days", "sub": "One row per PO",
                 "table": table(raised_week.groupby(["po", "vendor"], as_index=False)
                                .agg(**{"PO Date": ("po_date", "max"), "Lines": ("po", "size"), "Order Pcs": ("order_qty", "sum"),
                                        "Ordered": ("order_amt", "sum")})
                                .rename(columns={"po": "PO No.", "vendor": "Vendor"})
                                .sort_values("PO Date", ascending=False)
                                [["PO Date", "PO No.", "Vendor", "Lines", "Order Pcs", "Ordered"]],
                                {"PO Date": "date", "Ordered": "inr"}, sort=False)},
            ],
        })
        lede.append(_plural(raised_today["po"].replace("", np.nan).nunique(), "PO") + " raised today")
        lede.append(_plural(len(due_week), "delivery", "deliveries") + " due in the next 7 days")

    # ---------------------------------------------------------------- dues
    p, _ = sources.get("dues", (None, None))
    if p is not None and not p["d"].empty:
        b = p["d"].copy()
        terms = p.get("terms")
        b["key"] = b["party"].map(norm_key)
        if terms is not None and len(terms):
            b = b.merge(terms, on="key", how="left")
        b["Agency"] = b.get("Agency", pd.Series("", index=b.index)).fillna("").astype(str).str.upper()
        due = _day(b["due_on"])
        today_b = b[due == t]
        week_b = b[(due >= t) & (due <= week_ahead)]
        over_b = b[due < t]
        notes = []
        if b["bill_date"].notna().any() and (t - b["bill_date"].max()).days > 120:
            notes.append(notice(f"The newest bill on the dues list is dated {b['bill_date'].max():%d %b %Y}: pick the "
                                "current dues tab on the Supplier dues page if this list is old.", "warning"))
        sections.append({
            "id": "dues", "area": "dues", "title": "Payments", "sub": "DUES PAYMENT SUPPLIERS sheet", "link": "/dues",
            "notices": notes,
            "kpis": [
                kpi("Due today", float(today_b["net"].sum()), "", "inr", tone="alert" if len(today_b) else None,
                    hint=_plural(len(today_b), "bill"), id="pay_today"),
                kpi("Due in next 7 days", float(week_b["net"].sum()), "", "inr", hint=_plural(len(week_b), "bill"),
                    id="pay_week"),
                kpi("Overdue now", float(over_b["net"].sum()), "", "inr", tone="alert" if len(over_b) else None,
                    hint=f"{_plural(len(over_b), 'bill')} · {_plural(over_b['party'].nunique(), 'supplier')}",
                    id="pay_overdue"),
            ],
            "tables": [
                {"title": "Bills due today and in the next 7 days", "sub": "Earliest first",
                 "table": table(pd.DataFrame({
                     "Due On": week_b["due_on"], "Supplier": week_b["party"], "Bill No.": week_b["ref"],
                     "Bill Date": week_b["bill_date"], "Net Payable": week_b["net"], "Agency": week_b["Agency"]})
                     .sort_values("Due On"), {"Due On": "date", "Bill Date": "date", "Net Payable": "inr",
                                              "Bill No.": "text"}, sort=False)},
            ],
        })
        lede.append(f"{inr_short(week_b['net'].sum())} of bills due in the next 7 days")

    # ---------------------------------------------------------------- enquiries
    e, _ = sources.get("supplier_enquiry", (None, None))
    if e:
        q, c = e.get("enquiries"), e.get("city_po")
        kpis, tables = [], []
        if q is not None and not q.empty:
            qd = _day(q["date"])
            logged_today, logged_week = q[qd == t], q[(qd >= week_ago) & (qd <= t)]
            open_ = q[q["open"]]
            kpis += [
                kpi("Enquiries logged today", len(logged_today), "", id="enq_today"),
                kpi("Logged in last 7 days", len(logged_week), "",
                    hint=f"{_plural(int(logged_week['open'].sum()), 'still pending', 'still pending')}", id="enq_week"),
                kpi("Pending enquiries", len(open_), "", tone="alert" if len(open_) else None, id="enq_open"),
                kpi("Pending over 30 days", int((open_["age"] > 30).sum()), "", id="enq_old",
                    tone="alert" if (open_["age"] > 30).any() else None),
            ]
            tables.append({"title": "Enquiries logged in the last 7 days", "sub": "Newest first",
                           "table": table(pd.DataFrame({
                               "Date": logged_week["date"], "Supplier": logged_week["party"], "Enquiry": logged_week["about"],
                               "Status": logged_week["status"], "Handled by": logged_week["handler"]})
                               .sort_values("Date", ascending=False), {"Date": "date"}, sort=False)})
            tables.append({"title": "Waiting longest", "sub": "Pending enquiries, oldest first",
                           "table": table(pd.DataFrame({
                               "Date": open_["date"], "Supplier": open_["party"], "Enquiry": open_["about"],
                               "Handled by": open_["handler"], "Days pending": open_["age"]})
                               .sort_values("Days pending", ascending=False).head(10),
                               {"Date": "date", "Days pending": "int"}, sort=False)})
            lede.append(_plural(len(logged_today), "enquiry", "enquiries") + " logged today")
        if c is not None and not c.empty:
            wait = c[c["status"] == "Waiting for PO"]
            kpis.append(kpi("Suppliers waiting for PO", len(wait), "", id="wait_po",
                            hint=f"{_plural(wait['city'].nunique(), 'city', 'cities')}"))
        if kpis:
            sections.append({"id": "enquiries", "area": "enquiries", "title": "Supplier enquiries",
                             "sub": "Supplier's Enquiry Sheet", "link": "/enquiries", "kpis": kpis, "tables": tables})

    # ---------------------------------------------------------------- order to vendors (only if it has a date column)
    g, _ = sources.get("order_to_vendors", (None, None))
    if g:
        df, _h = grid_frame(g)
        if not df.empty:
            tt, fmts = typed(df)
            date = next((x for x in [_col(tt.columns, "Order Date", "PO Date", "Date")] if x and fmts.get(x) == "date"), None)
            amount = next((x for x in [_col(tt.columns, "Order Amt", "Order Amount", "Amount", "Amt", "Value", "Total")]
                           if x and fmts.get(x) in ("int", "dec")), None)
            if date:
                od = _day(tt[date])
                td, wk = tt[od == t], tt[(od >= week_ago) & (od <= t)]
                ks = [kpi("Vendor orders today", len(td), "", id="otv_today"),
                      kpi("Vendor orders in last 7 days", len(wk), "", id="otv_week")]
                if amount:
                    ks.append(kpi("Value in last 7 days", float(wk[amount].sum()), "", "inr", id="otv_value"))
                sections.append({"id": "otv", "area": "otv", "title": "Order to vendors", "sub": "Order to vendors sheet",
                                 "link": "/order-to-vendors", "kpis": ks,
                                 "tables": [{"title": "Vendor orders in the last 7 days", "sub": "Newest first",
                                             "table": table(wk.sort_values(date, ascending=False), fmts, sort=False)}]})

    keep = ROLES.get(role)
    if keep is not None:
        sections = [s for s in sections if s["area"] in keep]
    return {"date": f"{t:%A, %d %B %Y}", "as_of": f"{pd.Timestamp(now):%d %b %Y, %I:%M %p}",
            "lede": lede, "sections": sections, "role": role if role in ROLES else "Management",
            "options": {"role": list(ROLES)},
            "windows": {"last7": f"{week_ago:%d %b} – {t:%d %b}", "next7": f"{t:%d %b} – {week_ahead:%d %b}"}}
