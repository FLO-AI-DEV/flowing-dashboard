import pandas as pd

from app.dashboards import enquiries as e
from app.sources.demo import DemoSheetSource, DEMO_ENQUIRIES_ID

TODAY = pd.Timestamp("2026-11-21")


def _data():
    src = DemoSheetSource(today=TODAY.date())
    grids = [(t, label, src.get_values(DEMO_ENQUIRIES_ID, t)) for t, label in e.TABS]
    return e.parse_enquiries(grids, today=TODAY)


def test_all_three_tabs_are_read_and_status_spellings_fold():
    d = _data()
    assert not d["issues"]
    df = d["enquiries"]
    assert set(df["source"]) == {"Calls", "Logistics group", "Billing group"}
    assert set(df["status_word"]) <= set(e.STATUS_ORDER)
    assert df["solved"].eq(df["status_word"].eq("Solved")).all()


def test_about_is_only_tidied_not_reinterpreted():
    assert e.tidy_about("Parcel  track ") == "Parcel track"
    assert e.tidy_about("PARCEL TRACK") == "Parcel track"
    assert e.tidy_about("") == "(not written)"


def test_home_and_cause_agree():
    d = _data()
    h = e.home_dashboard(d, TODAY)
    assert h["total_open"] == int((~d["enquiries"]["solved"]).sum())
    assert sum(c["open"] for c in h["causes"]) == h["total_open"]
    first = h["causes"][0]
    c = e.cause_dashboard(d, first["key"], TODAY)
    assert c["count"] == first["open"]
    assert e.cause_dashboard(d, "all", TODAY, period="older")["count"] <= h["total_open"]


def test_enquiry_nudge_lists_open_items_of_one_group():
    from app import nudges
    d = _data()
    box = nudges.TestOutbox()
    key = e.home_dashboard(d, TODAY)["causes"][0]["key"]
    p = nudges.preview(box, d, "enquiry", "older", 0, key)
    assert p["to"] == ["Kavita"]
    assert p["count"] == len(e.open_rows(d, key, "older")[0])
    if p["count"]:
        assert "mark each one SOLVED" in p["message"]
        nudges.send(box, d, "enquiry", "older", 0, False, key)
        assert box.rows and "enquiry" in box.rows[0][5]


def test_team_columns_are_read_and_category_wins_over_typed_text():
    head = ["DATE & TIME ", "CLIENT NAME ", "Number ", "ENQUIRY ABOUT ", "REMARK ", "SOLVE/ PENDING", "FOLLOW UP ",
            "Client reply ", "category", ". ASSIGNED ", "BILL NO", " SOLVED DATE"]
    grid = [head,
            ["12/10/2026 10:37:49", "A", "1", "Parcel  track ", "need lr", "Solved ", "", "", "Parcel tracking / LR / GR", "Anjali", "3504/2627", "13/10/2026"],
            ["13/11/2026 11:00:00", "B", "2", "need lr", "", "Pending ", "", "", "Parcel tracking / LR / GR", "", "", ""],
            ["14/11/2026 11:00:00", "C", "3", "gr check", "", "", "", "", "", "", "", ""]]
    d = e.parse_enquiries([("ENQ CALLS", "Calls", grid)], today=TODAY)
    df = d["enquiries"]
    assert not d["issues"]
    assert list(df["assigned"]) == ["Anjali", "", ""] and list(df["bill_no"])[0] == "3504/2627"
    assert df["solved_on_dt"].iloc[0] == pd.Timestamp("2026-10-13")
    assert list(df["group_label"]) == ["Parcel tracking / LR / GR", "Parcel tracking / LR / GR", "Gr check"]
    h = e.home_dashboard(d, TODAY)
    assert {c["label"]: c["open"] for c in h["causes"]} == {"Parcel tracking / LR / GR": 1, "Gr check": 1}
