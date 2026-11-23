"""Management overview across the four Flo-Wing sheets. Every number reuses the page calculations, so they match."""
from __future__ import annotations

from ..core import fmt, inr_short
from ..tables import notice
from . import dues as dus
from . import enquiry as enq
from . import extra as ex
from . import generic as gen
from . import orders as ords


ROLES = {"Management": None,
         "Purchase team": {"overdue", "orders", "otv", "enquiries", "none"},
         "Accounts": {"dues", "none"}}


def overview_dashboard(sources: dict, months: list[str], today, f: dict | None = None, role: str = "") -> dict:
    out = _overview(sources, months, today, f or {})
    keep = ROLES.get(role)
    if keep is not None:          # "View as": only what that team works on
        out["alerts"] = [a for a in out["alerts"] if a.get("area") in keep]
        out["sections"] = {k: v for k, v in out["sections"].items() if k in keep}
    out["options"]["role"] = list(ROLES)
    out["role"] = role if role in ROLES else "Management"
    return out


def _overview(sources: dict, months: list[str], today, f: dict) -> dict:
    """sources: {"order_status": (df|None, err), "dues": (parsed|None, err), "order_to_vendors": (grid|None, err)}"""
    alerts, errors, sections = [], [], {}
    for key, label in (("order_status", "Order Status"), ("dues", "Supplier Dues"), ("order_to_vendors", "Order to Vendors"),
                       ("supplier_enquiry", "Supplier's Enquiry Sheet")):
        if key in sources and sources[key][1]:
            errors.append(notice(f"{label} could not be loaded: {sources[key][1]}", "error"))
    month_options: list[str] = []

    d, _ = sources["order_status"]
    if d is not None:
        month_options = ords.options(d)["month"]
        o = ords.orders_dashboard(d, {**f, "month": months})
        if not o.get("empty"):
            s = o["summary"]
            k = {x["id"]: x["value"] for x in o["kpis"]}
            if s["overdue_lines"]:
                old = s["oldest"]
                alerts.append({"kind": "error", "area": "overdue", "title": f"{fmt(s['overdue_lines'])} PO line{'s' if s['overdue_lines'] != 1 else ''} overdue",
                               "text": f"{inr_short(s['overdue'])} still pending past the delivery date."
                                       + (f" Oldest: PO {old['po']} ({old['vendor'].title()}), {old['days']} days late." if old else "")})
            else:
                alerts.append({"kind": "success", "area": "overdue", "title": "Nothing overdue",
                               "text": "No PO line with pending pieces is past its delivery date."})
            if s["pending"] > 0:
                vb = o["charts"]["vendors"]
                top = []
                if vb["categories"]:
                    i = max(range(len(vb["categories"])), key=lambda j: vb["series"][1]["values"][j])
                    top.append({"dimension": "Vendor", "name": vb["categories"][i], "value": vb["series"][1]["values"][i]})
                alerts.append({"kind": "warning", "area": "orders", "title": f"{fmt(s['pending_pcs'])} pcs pending",
                               "text": f"{inr_short(s['pending'])} still to come in, out of {inr_short(k['ordered'])} ordered "
                                       f"({(k['received'] / k['ordered'] * 100) if k['ordered'] else 0:.1f}% received).",
                               "top": top, "money": True})
            sections["orders"] = {"kpis": [x for x in o["kpis"] if x["id"] in ("ordered", "received", "pending", "overdue", "ontime")],
                                  "charts": {"monthly": o["charts"]["monthly"], "vendors": o["charts"]["vendors"],
                                             "timing": o["charts"]["timing"]},
                                  "tables": {"vendors": o["tables"]["vendors"], "overdue": o["tables"]["overdue"]},
                                  "overdue_total": o["overdue_total"]}

    p, _ = sources["dues"]
    if p is not None and not dus.is_stale(p, today):
        du = dus.dues_dashboard(p, f, today)
        if not du.get("empty"):
            s = du["summary"]
            alerts.append({"kind": "error" if s["overdue"] > 0 else "success", "area": "dues",
                           "title": f"{inr_short(s['overdue'])} dues overdue" if s["overdue"] > 0 else "No dues overdue",
                           "text": f"{inr_short(s['total'])} payable to {fmt(s['suppliers'])} suppliers across "
                                   f"{fmt(s['bills'])} bills; {inr_short(s['due7'])} falls due in the next 7 days."})
            sections["dues"] = {"kpis": du["kpis"], "title": du["title"], "notices": du["notices"],
                                "tables": {"suppliers": du["tables"]["suppliers"]}, "charts": {"ageing": du["charts"]["ageing"]}}

    g, _ = sources["order_to_vendors"]
    if g is not None:
        ov = gen.otv_dashboard(g, f)
        if not ov.get("empty"):
            rows = next((x["value"] for x in ov["kpis"] if x["id"] == "rows"), 0)
            st = ov["charts"]["by_status"]
            alerts.append({"kind": "info", "area": "otv", "title": f"{fmt(rows)} vendor orders",
                           "text": (" · ".join(f"{x['label'].title()}: {fmt(x['value']) if not ov['charts']['money'] else inr_short(x['value'])}"
                                               for x in st[:3]) or "Rows on the Order to vendors sheet.")})
            sections["otv"] = {"kpis": ov["kpis"], "charts": ov["charts"]}

    q, _ = sources.get("supplier_enquiry", (None, None))
    if q is not None:
        en = enq.enquiry_dashboard(q, f, today)
        sec = en["sections"]
        if "enquiries" in sec:
            s = sec["enquiries"]["summary"]
            old = s["oldest"]
            pend = sec.get("city_po", {}).get("summary", {}).get("pending", 0)
            alerts.append({"kind": "warning" if s["open"] else "success", "area": "enquiries",
                           "title": f"{fmt(s['open'])} supplier enquir{'ies' if s['open'] != 1 else 'y'} pending",
                           "text": f"{fmt(s['total'])} logged."
                                   + (f" Oldest pending: {old['party']}, {old['days']} days." if old else "")
                                   + (f" {fmt(pend)} suppliers still waiting for a PO." if pend else "")})
            sections["enquiries"] = {"kpis": [x for x in sec["enquiries"]["kpis"]
                                              if x["id"] in ("enquiries", "open", "unsolved", "solved_rate")],
                                     "charts": {"open_by_handler": sec["enquiries"]["charts"]["open_by_handler"]}}

    if not alerts and not errors:
        alerts.append({"kind": "info", "area": "none", "title": "No data", "text": "There is no data for the selected months."})
    return {"options": {"month": month_options, "period": ex.PERIODS,
                        "supplier_type": ex.SUPPLIER_TYPES, "amount": ex.AMOUNTS},
            "alerts": alerts, "errors": errors, "sections": sections}
