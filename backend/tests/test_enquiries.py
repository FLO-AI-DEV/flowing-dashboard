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
    assert list(df["group_label"]) == ["Parcel tracking / LR / GR"] * 2 + ["Not categorised yet"]     # only the sheet's own categories; nothing guessed
    assert list(df["auto_category"]) == [False, False, False]
    h = e.home_dashboard(d, TODAY)
    assert {c["label"]: c["open"] for c in h["causes"]} == {"Parcel tracking / LR / GR": 1, "Not categorised yet": 1}
    assert h["auto_categorised"] == 1


def test_auto_category_examples_from_the_real_sheet():
    c = e.CATEGORIES
    for text, want in [("Parcel  track ", 0), ("need lr", 0), ("GR CHECK", 0), ("PARCEL NOT DELIVER ", 1), ("article damage", 2),
                       ("1 PCS SHORT RECEIVE", 3), ("RATE DIFF", 4), ("need invoice", 5), ("asking cn", 5), ("Refund", 6),
                       ("stock check", 7), ("gst no update", 8), ("anjali di", 9)]:
        assert e.auto_category(text) == c[want], text
    assert e.auto_category("") == "" and e.auto_category("", "need lr") == c[0]


def test_suggest_column_keeps_team_choices_and_fills_gaps():
    head = ["DATE & TIME", "CLIENT NAME", "Number", "ENQUIRY ABOUT", "REMARK", "SOLVE/ PENDING", "FOLLOW UP", "Client reply", "category"]
    grid = [head,
            ["12/10/2026 10:00:00", "A", "1", "parcel track", "", "Solved", "", "", "Other"],
            ["12/10/2026 10:05:00", "B", "2", "Refund", "", "Pending", "", "", ""],
            [], 
            ["12/10/2026 10:07:00", "C", "3", "", "", "", "", "", ""]]
    r = e.suggest_column(grid, "t")
    assert r["column"] == "I" and r["first_row"] == 2
    assert r["values"] == ["Other", "Payment / ledger / refund"]    # own choice kept, gap filled, trailing blanks dropped



def test_tile_lists_match_the_tile_numbers():
    d = _data()
    h = e.home_dashboard(d, TODAY)
    n = {k["id"]: k["value"] for k in h["kpis"]}
    assert e.cause_dashboard(d, "v-today", TODAY)["count"] == n["today"]
    assert e.cause_dashboard(d, "all", TODAY)["count"] == n["open"]
    assert e.cause_dashboard(d, "v-old", TODAY)["count"] == n["old"]
    assert e.cause_dashboard(d, "v-notpicked", TODAY)["count"] == n["notpicked"]
