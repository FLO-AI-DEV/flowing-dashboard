"""Show what the dashboard reads from the real sheets, using a service-account key. Run from the backend folder:

    python scripts/check_data.py secrets/your-key.json

It reads every order tab and the payment follow-up sheet exactly as the dashboard does, then prints, per tab, where
the headings were found, which columns had to be found by position, how many orders were read, and the numbers the
Today and Payments pages would show. Read-only. Nothing is sent anywhere.
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import SHEET_REGISTRY  # noqa: E402
from app.dashboards import orders as ords  # noqa: E402
from app.dashboards import payments as pays  # noqa: E402
from app.locate import SheetLayoutError  # noqa: E402
from app.sources.google import GoogleSheetSource, SheetAccessError  # noqa: E402


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        src = GoogleSheetSource(json.load(f))

    print("ORDER SHEET")
    sid = SHEET_REGISTRY["orders"]["id"]
    tabs = [t for t, _ in src.list_tabs(sid) if ords.is_order_tab(t)]
    grids, fills = [], []
    print(f"  {len(tabs)} order tabs found. Reading each (big tabs can take up to a minute)...", flush=True)
    for t in tabs:
        t0 = time.time()
        try:
            g = src.get_values(sid, t)
        except SheetAccessError as e:
            print(f"  ✗ {t:<22} could not read after {time.time() - t0:.0f}s: {e}", flush=True)
            continue
        took = f" [{time.time() - t0:.0f}s]"
        grids.append((t, g))
        try:
            df, lay = ords.read_order_tab(g, t)
            extra = f" · found by position: {', '.join(lay.inferred)}" if lay.inferred else ""
            missing = [m for m in lay.missing if m not in ("mona", "mona_time", "sr")]
            miss = f" · not on this tab: {', '.join(missing)}" if missing else ""
            print(f"  ✓ {t:<22} headings in row {lay.header_row + 1}, {len(df):>4} orders{extra}{miss}{took}", flush=True)
            if len(df):
                pct = lambda m: f"{100 * m.mean():.0f}%"
                up = lambda c: df[c].astype(str).str.upper()
                fills.append(f"    {t:<22} Mona replied {pct(up('mona').str.strip() != '') if 'CREDIT' in t.upper() else '  — '} · "
                             f"PO DONE {pct(up('po_status').str.contains('DONE'))} · "
                             f"bill DONE {pct(up('bill_status').str.contains('DONE'))} · "
                             f"bill date {pct(df['bill_time'].astype(str).str.strip() != '')}")
        except SheetLayoutError as e:
            print(f"  ✗ {t:<22} {e}{took}", flush=True)
    print("\n  How much of each step is filled in, per tab:")
    print("\n".join(fills))
    d = ords.parse_orders(grids)
    h = ords.home_dashboard(d, {})
    print("\n  Today page:", " · ".join(f"{k['label']} {k['value']}" for k in h["kpis"]))
    for p in h["pipeline"]:
        print(f"    {p['label']:<28} {p['count']:>4}" + (f"  ({p['late']} late)" if p["late"] else ""))
    print("  Needs action:")
    for a in h["actions"][:12]:
        print(f"    [{a['tone']:<4}] {a['who']:<14} {a['what']}")
    t = ords.team_dashboard(d, {})
    print("  Stage owners (real dates):")
    cols = [c["label"] for c in t["owners"]["columns"]]
    for r in t["owners"]["rows"]:
        print("    " + " · ".join(f"{c} {v}" for c, v in zip(cols, r)))

    print("\nPAYMENT FOLLOW-UP")
    cfg = SHEET_REGISTRY["payments"]
    t0 = time.time()
    try:
        grid = src.get_values(cfg["id"], cfg["tab"])
    except SheetAccessError as e:
        print(f"  ✗ could not read: {e}")
        return
    print(f"  read in {time.time() - t0:.0f}s", flush=True)
    p = pays.parse_payments(grid)
    o = p["orders"]
    print(f"  {len(o)} sale orders this year: " + ", ".join(f"{k} {v}" for k, v in o["state"].value_counts().items()))
    for n in p["issues"]:
        print("  note:", n["text"])
    ph = pays.payments_dashboard(p, {})
    print("  " + " · ".join(f"{k['label']} {k['value']:,.0f}" if isinstance(k["value"], float) else
                           f"{k['label']} {k['value']}" for k in ph["kpis"]))
    cols = [c["label"] for c in ph["members"]["columns"]]
    for r in ph["members"]["rows"]:
        print("    " + " · ".join(f"{c} {v}" for c, v in zip(cols, r)))
    print("\nAll read-only. If a tab shows ✗, its headings changed: paste this output to Claude.")


if __name__ == "__main__":
    main()
