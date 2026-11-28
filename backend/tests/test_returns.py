"""Sales returns on rows laid out like the real Quality Check Sheet (row 1 empty, headings on row 2, "CR No." twice)."""
import pandas as pd

from app.dashboards import returns as rt

HEAD = ["DATE", "BILL NO./DATE", "BILL DATE", "Days", "Client Name", "Barcode", "Color", "QTY. PCS", "QC Pass", "QC FAIL",
        "CR No.", "CR No.", "Calling Remark", "Return To Client", "Return\nApproved By", "Amount", "image"]
TODAY = "2026-11-20"


def row(date, bill, bill_date, client, barcode, qty, ok, bad, cr, why="", calling="", returned="", amount=""):
    return [date, bill, bill_date, "", client, barcode, "", str(qty), str(ok), str(bad), cr, why, calling, returned, "", str(amount)]


def parse(*rows):
    return rt.parse_returns([[], HEAD, *rows], today=TODAY)


def test_columns_dates_and_qc_split():
    d = parse(
        row("14/02/2025", "FW-13141/12/11/24", "12/11/24", "ALPHA W.S.", "165149-S1", 1, "", 1, "6715/24-25", "TOP DAMAGE"),
        row("06/09/25", "15516/21/12/24", "21/12/24", "BETA W.S.", "15516", 18, 13, 5, "6722/24-25", "TOP ME DAAG HAI"),
        row("17/3/2026 00:00", "FW-1/2627", "05-03-2026", "GAMMA W.S.", "X1", 2, "", 1, "6773/24-25", "TOP FAT RHA HAI"),
    )["lines"]
    assert len(d) == 3
    assert d["date"].dt.strftime("%Y-%m-%d").tolist() == ["2025-02-14", "2025-09-06", "2026-03-17"]
    assert d["pass_n"].tolist() == [0, 13, 0] and d["fail_n"].tolist() == [1, 5, 1]
    assert d["unmarked_n"].tolist() == [0, 0, 1]                      # 2 pieces, only 1 marked fail
    assert d["reason_text"].iloc[0] == "TOP DAMAGE" and d["bill_age"].iloc[0] == 94 and bool(d["over_policy"].iloc[0])


def test_pending_calls_merge_per_cr_and_age_boxes():
    d = parse(
        row("10/11/2026", "FW-1/2627", "01/11/2026", "ALPHA W.S.", "B1", 3, 3, "", "FWSR-1/2627", "PCS SAHI H"),
        row("10/11/2026", "FW-1/2627", "01/11/2026", "ALPHA W.S.", "B2", 2, 2, "", "FWSR-1/2627", "PCS SAHI H"),
        row("19/11/2026", "FW-2/2627", "01/11/2026", "BETA W.S.", "B3", 1, 1, "", "FWSR-2/2627", "PCS SAHI H", calling="called, not picking"),
        row("04/11/2026", "FW-3/2627", "01/10/2026", "GAMMA W.S.", "B4", 4, 4, "", "FWSR-3/2627", "PCS SAHI H"),
        row("19/11/2026", "FW-4/2627", "01/11/2026", "DELTA W.S.", "B5", 1, "", 1, "FWSR-4/2627", "TOP CHHIKA HAI"),
    )
    out = rt.returns_dashboard(d, today=TODAY)
    k = {x["id"]: x for x in out["kpis"]}
    assert k["pcs"]["value"] == 11 and k["pass"]["value"] == 10 and k["fail"]["value"] == 1
    assert k["pending"]["value"] == 2                                  # ALPHA (2 barcodes merged) + GAMMA; BETA already called
    boxes = {b["key"]: b for b in out["boxes"]}
    assert boxes["8-15"]["count"] == 1 and boxes["8-15"]["pcs"] == 5 and boxes["16+"]["count"] == 1
    only = rt.returns_dashboard(d, today=TODAY, box="8-15")
    assert [r[0] for r in only["pending"]["rows"]] == ["ALPHA W.S."]
    assert out["reasons"] == [{"reason": "Torn / hole / line", "pcs": 1}]


def test_reason_groups_use_the_teams_words():
    assert rt.reason_group("TOP ME DHAG HAI") == "Stain / mark / colour"
    assert rt.reason_group("PANT CHHIKA HAI") == "Torn / hole / line"
    assert rt.reason_group("TOP KE BUTTON HAT RHE HAI") == "Work / button / stitching"
    assert rt.reason_group("") == "(no reason written)"


def test_missing_heading_row_is_reported_not_crashed():
    out = rt.parse_returns([["nothing", "here"]], today=TODAY)
    assert out["lines"].empty and "no heading row" in out["issues"][0]["text"]


