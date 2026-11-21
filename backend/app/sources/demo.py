"""Built-in demo data shaped like the four Flo-Wing sheets (all names and figures are invented).

Used when no Google key is configured, so the dashboard can be tried without access to the real sheets.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from ..config import SHEET_REGISTRY

EPOCH = date(1899, 12, 30)


def serial(d: date) -> int:
    return (d - EPOCH).days


VENDORS = [("SHREE RAM TEXTILES (JAIPUR)", "Jaipur"), ("MAHAVIR CREATIONS (KOLKATA) MSME", "Kolkata"),
           ("RIDDHI FASHION (SURAT)", "Surat"), ("NEELKANTH APPAREL (JAIPUR)", "Jaipur"),
           ("SAI KRIPA GARMENTS (DELHI)", "Delhi"), ("ANAYA PRINTS (JAIPUR) MSME", "Jaipur"),
           ("GANGA EXPORTS (KOLKATA)", "Kolkata"), ("VRINDA CLOTHING (AHMEDABAD)", "Ahmedabad"),
           ("KESAR ETHNIC (JAIPUR)", "Jaipur"), ("MOHINI DESIGNS (SURAT)", "Surat")]
CATS = ["SKD", "CO-ORD SET", "KURTA", "KURTA PANT", "DRESS"]
DEPTS = ["CLASSIC", "PREMIUM", "BASIC"]
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _po_master(today: date):
    rnd = random.Random(7)
    head = ["", "Po / Order Date", "Po. No.", "Delivery Date", "Actual Received Date", "Delay By Day", "vender name ",
            "City", "Item Description", "Category", "Suppiler D.No.", "design no", "Order Qty", "Po Rate",
            "Purchase Rate / \nActual Rate", "RATE VERIATION ", "Order Amt", "Recived Qty", "Recived Amt",
            "Pending Qty", "Pending Order Velue", "Available Pcs", "Department", "Fabric", "Pattern", "",
            "ORDER MONTH", "DELIVERY MONTH", "REMARK"]
    rows = [head]
    start = date(2026, 4, 1)
    n = 0
    for po in range(1, 181):
        od = start + timedelta(days=rnd.randint(0, (today - start).days - 3))
        v, city = rnd.choice(VENDORS)
        due = od + timedelta(days=rnd.choice([15, 21, 30, 45]))
        for _ in range(rnd.randint(1, 4)):
            n += 1
            qty = rnd.choice([10, 20, 30, 40, 60, 100])
            rate = rnd.choice([895, 1095, 1295, 1695, 2185, 2495, 3395])
            age = (today - due).days
            if age > 0 and rnd.random() < 0.72:
                rq, rd = qty, due + timedelta(days=rnd.choice([-5, -2, 0, 0, 3, 7, 12, 20]))
                rd = min(rd, today)
            elif rnd.random() < 0.25:
                rq, rd = qty // 2, None
            else:
                rq, rd = 0, None
            delay = max(0, (rd - due).days) if rd else 0
            rows.append([n, serial(od), f"FWPO-{po:05d}/2627", serial(due), serial(rd) if rd else "", delay, v, city,
                         f"{rnd.choice(CATS)} STITCHED", rnd.choice(CATS), f"D-{rnd.randint(100, 999)}",
                         f"FW{rnd.randint(100, 599)}-{rnd.randint(100000, 999999)}", qty, rate, "", "", qty * rate, rq,
                         rq * rate, qty - rq, (qty - rq) * rate, "", rnd.choice(DEPTS), "", "", n,
                         f"{MON[od.month - 1]}{od.year}", f"{MON[due.month - 1]}{due.year}", ""])
    return rows


def _dues_tab(today: date, title_day: date, rnd: random.Random):
    rows = [[f"TOTAL DUES UPTO {title_day:%d-%m-%Y} FLO WING -(FIFO)"],
            ["Date", "Ref. No.", "Party's Name", "Opening", "PENDING", "Dis.", "NET PAYABLE", "DUE DAYS", "DISCOUNT", "DUES ON"]]
    for v, _ in VENDORS[:8]:
        sub = 0
        for _ in range(rnd.randint(1, 4)):
            bd = title_day - timedelta(days=rnd.randint(10, 80))
            amt = rnd.choice([18500, 32400, 46576, 56700, 81497, 1_20_000, 2_45_000])
            due = bd + timedelta(days=rnd.choice([15, 30, 45, 60]))
            rows.append([f"{bd:%d-%b-%Y}", f"{rnd.randint(100, 1999)}/FWP/{rnd.randint(100, 999)}-2627", v,
                         f"{amt:.2f} Cr", amt, "", amt, "", "", f"{due:%d-%b-%Y}", rnd.choice(["", "", "okay"])])
            sub += amt
        rows.append(["", "", "", "", "", "", sub])
        rows.append([])
    return rows


def _terms():
    rows = [["Parties", "Agency", "Days", "Discount (%)", "Agency Discount ", "checked", "REMARKS"]]
    agencies = ["MM AGENCY", "Shri Krishna", "", "Mohit Begani"]
    for i, (v, _) in enumerate(VENDORS):
        rows.append([v, agencies[i % 4], [15, 30, 45, 60][i % 4], [0, 2, 3, 5][i % 4], [0, 2, 3][i % 3], "yes"])
    return rows


def _otv(today: date):
    rnd = random.Random(11)
    rows = [["ORDER TO VENDORS 2026-27"],
            ["S.No", "Order Date", "Vendor Name", "Design No", "Fabric", "Qty", "Rate", "Amount", "Expected Date", "Status"]]
    for i in range(1, 61):
        od = today - timedelta(days=rnd.randint(1, 90))
        v, _ = rnd.choice(VENDORS)
        qty, rate = rnd.choice([20, 40, 60, 100]), rnd.choice([995, 1295, 1695, 2185])
        status = rnd.choice(["PENDING", "PENDING", "IN PRODUCTION", "DISPATCHED", "RECEIVED"])
        rows.append([i, serial(od), v, f"FW{rnd.randint(100, 599)}", rnd.choice(["COTTON", "RAYON", "CHANDERI", "MUSLIN"]),
                     qty, rate, qty * rate, serial(od + timedelta(days=30)), status])
    return rows


def _enquiry_tabs(today: date) -> dict:
    """Supplier's Enquiry Sheet: enquiry log, city-wise pending POs, terms approval, inactive suppliers."""
    rnd = random.Random(11)
    parties = ["SHREE RAM TEXTILES", "KESAR ETHNIC", "MAHAVIR CREATIONS", "NAVKAR FASHION", "RIDDHI SIDDHI PRINTS",
               "ANAND TEXTILE MILLS", "PADMAVATI FABRICS", "GANGOTRI CREATIONS", "SAKSHI TEXTILE", "VRINDA DESIGNS"]
    about = ["2 pieces missing from last parcel", "GR received, 3 pieces defective", "Bill rate mismatch, debit note",
             "PO pending for new design order", "Shoot photos not received", "LR copy needed for parcel",
             "Dupatta to be sent separately", "Size set short by 4 pcs", "Payment ledger confirmation", ""]
    handlers = ["nidhi", "kanchan", "gungun", "shaily"]
    log = [["Vendor Enquiry Sheet"], ["S. NO", "DATE", "PARTY NAME", "ENQUIRY ABOUT", "CONCERNED PERSON", "Follow Up",
                                      "REMARKS", "STATUS", "FOLLOW 1", "FOLLOW UP 2", "FOLLOW UP"]]
    for i in range(60):
        d = today - timedelta(days=rnd.randint(1, 150))
        age = (today - d).days
        st = rnd.choices(["SOLVED", "UNSOLVED", "In Process", ""], [5 if age > 30 else 2, 2, 2, 1])[0]
        log.append([str(i + 1), d.strftime("%d/%m/%Y"), rnd.choice(parties), rnd.choice(about),
                    rnd.choice(["Rakesh ji", "Mehul bhai", "Sunil", ""]), rnd.choice(handlers),
                    f"98{rnd.randint(10000000, 99999999)}" if rnd.random() < .5 else "", st,
                    rnd.choice(["called, will send by Monday", "reminder sent", ""]), "", ""])
    cities = ["KOLKATA", "MUMBAI", "SURAT", "AHMEDABAD", "JAIPUR"]
    head = []
    for c in cities:
        head += ["", f"{c} PO", "ORDER DATE", "STATUS"]
    city = [head[1:], [""] * len(head)]
    for r in range(8):
        row = []
        for c in cities:
            if rnd.random() < .75:
                d = today - timedelta(days=rnd.randint(3, 80))
                txt = rnd.choice([d.strftime("%d/%m/%Y") + " order", f"{d.day} {d.strftime('%B').lower()} order",
                                  d.strftime("%d-%m-%Y")])
                row += [str(r + 1), rnd.choice(parties).title(), txt, rnd.choice(["DONE", "", ""])]
            else:
                row += ["", "", "", ""]
        city.append(row[1:])
    terms = [["Date", "Supplier Details", "", "", "Payment Terms", "", "", "", "", "Approval ", "", "", "Software "],
             ["", "Supplier", "Supplier Code", "Contact Person ", "Payment Days", "Discount ", "Other Special Terms ",
              "Confirmed by ", "Confirmed on", "Approval Status", "Approved By", "Date/Time", "Entry by", "Entry Date ",
              "Entry Checked"]]
    for i, ptn in enumerate(parties[:8]):
        d = today - timedelta(days=rnd.randint(2, 90))
        st = "Approved" if i < 5 else ("PENDING" if i < 7 else "")
        terms.append([d.strftime("%d/%m/%Y"), f"{ptn} (MSME) {rnd.choice(cities)}", str(610 + i), "",
                      rnd.choice(["30", "45", "15"]) if i != 7 else "", rnd.choice(["5%", "12%", "3+3%"]) if i != 6 else "",
                      "", rnd.choice(["GUNGUN", "SHAILY"]), d.strftime("%d %B %Y"), st, "SHAILY" if st == "Approved" else "",
                      "", "Amit" if i < 6 else "", d.strftime("%d/%m/%Y") if i < 6 else "", ""])
    inactive = [["INACTIVE SUPPLIERS IN 2025-2026"], ["Party", "Qty"]] + \
        [[f"{n} TEX ({c.title()})", str(rnd.randint(20, 900))] for n, c in
         zip(["OM", "JAI MATA DI", "SHUBH", "RANG", "KALA", "LAXMI"], cities + ["SURAT"])]
    return {"Terms Approval": terms, "Sheet1": log, "Supplier's Enquiry Sheet ": city, "Inactive25-26": inactive,
            "purchase issues ": [["Date", "Supplier", "Issue", "Design no.", "Bill No."]]}


class DemoSheetSource:
    name = "demo"

    def __init__(self):
        today = date.today()
        rnd = random.Random(3)
        cycles = [today.replace(day=5) if today.day >= 5 else today - timedelta(days=10)]
        cycles += [cycles[0] - timedelta(days=15 * k) for k in range(1, 4)]
        due_tabs = {}
        for c in cycles:
            suf = "th" if 10 <= c.day % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(c.day % 10, "th")
            due_tabs[f"{c.day}{suf} {MON[c.month - 1]}"] = _dues_tab(today, c, rnd)
        self.sheets = {
            SHEET_REGISTRY["order_status"]["id"]: {"DASHBOARD": [["Order dashboard"]], "PO Entry Form": [["Form"]],
                                                    "PO Master ": _po_master(today)},
            SHEET_REGISTRY["dues"]["id"]: {**due_tabs, "Updated Sheet ": _terms()},
            SHEET_REGISTRY["order_to_vendors"]["id"]: {"Order to vendors": _otv(today)},
            SHEET_REGISTRY["supplier_enquiry"]["id"]: _enquiry_tabs(today),
        }

    def list_tabs(self, sheet_id: str):
        return [(t, i) for i, t in enumerate(self.sheets.get(sheet_id, {}))]

    def get_values(self, sheet_id: str, tab: str, formatted: bool = False):
        return self.sheets[sheet_id][tab]

    def get_formulas(self, sheet_id, tab, col_letter):
        return []
