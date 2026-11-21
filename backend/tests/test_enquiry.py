"""Supplier's Enquiry Sheet parsers, on grids laid out like the real tabs (names here are made up)."""
import pandas as pd

from app.dashboards import enquiry as enq

TODAY = pd.Timestamp("2026-11-21")

LOG = [
    ["Vendor Enquiry Sheet"],
    ["S. NO", "DATE ", "PARTY NAME", "ENQUIRY ABOUT", "CONCERNED PERSON", "Follow Up ", "REMARKS ", "STATUS ",
     "FOLLOW 1", "FOLLOW UP 2 ", "FOLLOW UP"],
    ["1", "05/06/2025", "kopal", "dupatta magvana h ", "anjali", "nidhi", "", "SOLVED", "", "lr bhejege"],
    ["2", "07/11/2025", "rania ", "parcel nhi mil rha hai", "gr team", "nidhi", "", "UNSOLVED"],
    ["3", "08/01/2026", "savith creation", "GR issue", "nikita", "kanchan", "9051443037", "In Process", "rectify"],
    ["", "", "Attire"],                                    # party-only line: not an enquiry
    ["", "30/10/2026", "ADPL", "DUPATTA MISSING ", "", "gungun ", "", "In Process"],
    ["", "", "prabha ", "DUPATTA MISSING ", "", "gungun"],  # no date, no status
]

CITY = [
    ["", "", "KOLKATA (pending po)", "order date ", "status ", "", "PENDING PO MUMBAI ", "ORDER DATE ", "STATUS "],
    [],
    ["", "1", "acube ", "", "", "1", "new pearl ", "18 may order ", "DONE "],
    ["", "2", "sumukh", "29-6-2026", "DONE", "2", "leela veera ", "21/07/2026 order ", ""],
    ["", "3", "rania", "46300", "-"],
]

TERMS = [
    ["Date", "Supplier Details", "", "", "Payment Terms", "", "", "", "", "Approval ", "", "", "Software "],
    ["", "Supplier", "Supplier Code", "Contact Person ", "Payment Days", "Discount ", "Other Special Terms ",
     "Confirmed by ", "Confirmed on", "Approval Status", "Approved By", "Date/Time", "Entry by", "Entry Date ",
     "Entry Checked"],
    ["01/09/2026", "ALPHA (MSME) KOLKATA", "619", "", "30", "13 %", "", "GUNGUN", "31 August 2026", "Approved", "SHAILY "],
    ["30/10/2026", "BETA (AHMEDABAD)", "", "", "", "2+3%"],
    ["31/10/2026", "GAMMA", "640", "", "45", "3%", "", "GUNGUN", "31/10/2026", "PENDING "],
]


def test_enquiry_log():
    d = enq.parse_enquiries(LOG, TODAY)
    assert list(d["party"]) == ["kopal", "rania", "savith creation", "ADPL", "prabha"]
    assert list(d["status"]) == ["Solved", "Unsolved", "In process", "In process", "No status"]
    assert d.loc[2, "contact"] == "9051443037" and d.loc[2, "notes"] == "rectify"
    assert d.loc[3, "handler"] == "Gungun" and d.loc[3, "age"] == 22
    assert d.loc[1, "topic"] == "Missing / short pieces" and d.loc[2, "topic"] == "GR / return / defect"


def test_city_blocks():
    c = enq.parse_city_po(CITY, TODAY)
    assert set(c["city"]) == {"Kolkata", "Mumbai"}
    row = c.set_index("supplier")
    assert row.loc["new pearl", "status"] == "PO issued"
    assert row.loc["new pearl", "date"] == pd.Timestamp("2026-05-18")
    assert row.loc["leela veera", "date"] == pd.Timestamp("2026-07-21") and row.loc["leela veera", "status"] == "Waiting for PO"
    assert row.loc["rania", "date"] == pd.Timestamp("1899-12-30") + pd.Timedelta(days=46300)


def test_terms_and_dashboard():
    t = enq.parse_terms(TERMS)
    assert list(t["status"]) == ["Approved", "Not filled", "Pending"]
    assert t.loc[0, "date"] == pd.Timestamp("2026-09-01") and t.loc[1, "terms_missing"]
    out = enq.enquiry_dashboard(enq.parse_enquiry_sheet({"enquiries": LOG, "city_po": CITY, "terms": TERMS}, TODAY),
                                {"handler": ["Gungun"]}, TODAY)
    k = {x["id"]: x["value"] for x in out["sections"]["enquiries"]["kpis"]}
    assert k["enquiries"] == 2 and k["open"] == 2
    assert out["views"] == ["enquiries", "city_po", "terms"]


def test_missing_tabs_are_fine():
    out = enq.enquiry_dashboard(enq.parse_enquiry_sheet({}, TODAY), {}, TODAY)
    assert out["sections"] == {} and out["notices"]
