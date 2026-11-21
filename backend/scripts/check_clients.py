"""Check the numbers on the Clients page against the raw sheet. Run from the backend folder:

    python scripts/check_clients.py secrets/your-key.json

Prints (read-only):
  1. the biggest "ORDER (NO. OF SETS)" entries exactly as typed, to see whether 9,054 sets for one client is real;
  2. how often the same client is typed in different ways (same W.S. code, or same first word);
  3. how many clients ordered only once.
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import SHEET_REGISTRY  # noqa: E402
from app.dashboards import orders as ords  # noqa: E402
from app.sources.google import GoogleSheetSource, SheetAccessError  # noqa: E402

WS = re.compile(r"W\s*\.?\s*S\s*\.?\s*-?\s*0*(\d{1,4})\b", re.I)


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        src = GoogleSheetSource(json.load(f))
    sid = SHEET_REGISTRY["orders"]["id"]
    grids = []
    for t in [t for t, _ in src.list_tabs(sid) if ords.is_order_tab(t)]:
        try:
            grids.append((t, src.get_values(sid, t)))
        except SheetAccessError as e:
            print(f"  could not read {t}: {e}")
    d = ords.parse_orders(grids)["orders"]
    print(f"{len(d):,} orders read from {len(grids)} tabs\n")

    print("1. SETS — biggest entries in ORDER (NO. OF SETS), exactly as typed")
    s = d["sets_n"]
    print(f"   typical order: {s.median():.0f} sets · 9 in 10 orders are {s.quantile(.9):.0f} sets or less · "
          f"{(s > 100).sum():,} orders above 100 · {(s <= 0).sum():,} orders with no number")
    for _, r in d.sort_values("sets_n", ascending=False).head(20).iterrows():
        print(f"   {r['sets_n']:>8,.0f}  typed: {str(r['sets'])[:30]!r:<32} {r['tab']:<17} {str(r['client'])[:40]}")
    print("   (ask the team: is this column sets, or pieces for some orders?)\n")

    print("2. CLIENT NAMES — the same client typed in different ways")
    names = d.groupby("client_key").size()
    print(f"   {len(names):,} different spellings of client names")
    code = d["client"].str.extract(WS)[0]
    with_code = d[code.notna()].assign(code=code[code.notna()].astype(int))
    print(f"   {len(with_code) / max(len(d), 1):.0%} of orders have a W.S. code in the name; "
          f"{with_code['code'].nunique():,} different W.S. codes")
    multi = with_code.groupby("code")["client_key"].nunique().sort_values(ascending=False)
    print(f"   {int((multi > 1).sum()):,} W.S. codes are typed under more than one name, for example:")
    for c in multi.head(5).index:
        print(f"     W.S.{c:03d}: " + " | ".join(with_code[with_code['code'] == c]['client_key'].value_counts().head(4).index))
    first = d["client_key"].str.extract(r"^([A-Z]{4,})")[0]
    top = d.groupby("client_key")["sets_n"].sum().sort_values(ascending=False).head(8).index
    print("   names sharing the first word with the biggest clients:")
    for k in top:
        w = re.match(r"^([A-Z]{4,})", k)
        if w:
            same = d.loc[first == w.group(1), "client_key"].value_counts()
            print(f"     {w.group(1):<12} {len(same)} spellings: " + " | ".join(same.head(4).index))
    print()

    led = d["ledger"].astype(str).str.strip()
    print(f"   LEDGER column filled on {(led != '').mean():.0%} of orders · {led[led != ''].str.upper().nunique():,} different ledgers")
    for t, g in d.groupby("tab", sort=False):
        print(f"     {t:<18} LEDGER filled {(g['ledger'].astype(str).str.strip() != '').mean():.0%}")
    print()

    print("3. ONE-TIME CLIENTS")
    once = (names == 1).sum()
    print(f"   {once:,} of {len(names):,} names have exactly one order ({once / max(len(names), 1):.0%})")


if __name__ == "__main__":
    main()
