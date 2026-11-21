"""Profile every Flo-Wing sheet, the same way we checked the order sheet, before building its dashboard page.

    python scripts/profile_sheets.py secrets/your-key.json            # all sheets
    python scripts/profile_sheets.py secrets/your-key.json "Parcel"   # only sheets whose name contains "Parcel"

For each tab it finds the heading row and prints, per column: the heading, how much of it is filled in, what kind
of values it holds (dates / numbers / text), and the values a status-like column uses (DONE, PENDING ...).
It also prints how many rows were added per month, so we can see which tabs are still in use.
Everything is also written to profile.txt next to this script's folder; upload that file to Claude.

Read-only: it never changes anything in the sheets. It prints no phone numbers.
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from datetime import date, datetime
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

sys.path.insert(0, __file__.rsplit("scripts", 1)[0])
from scripts.check_access import API, SCOPES, SHEETS, reason  # noqa: E402

DONE_ALREADY = {"NEW ORDERSHEET-2026-27", "New po sheet"}   # already on the dashboard (Orders, Payments)
MAX_TABS = 12              # per sheet; monthly copies of the same layout beyond this are only listed
STATUS_MAX_DISTINCT = 12   # a column with this many different values or fewer is treated as a status column
DATE_RX = re.compile(r"^\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})")
PHONE_RX = re.compile(r"\d{10}")

out_lines: list[str] = []
_last = [0.0]


def get(session, url, **kw):
    """Google allows 60 reads a minute per key (the running dashboard uses some too), so go slowly and wait out 429s."""
    for attempt in range(6):
        wait = 1.5 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        r = session.get(url, **kw)
        if r.status_code != 429:
            return r
        print("    (Google's per-minute read limit reached, waiting 30s...)", flush=True)
        time.sleep(30)
    return r


def say(s: str = ""):
    print(s)
    out_lines.append(s)


def norm(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()


def to_date(v: str, month_first: bool = False):
    m = DATE_RX.match(v)
    if not m:
        return None
    d, mth, y = (int(x) for x in m.groups())
    if month_first:
        d, mth = mth, d
    y = y + 2000 if y < 100 else y
    try:
        return date(y, mth, d)
    except ValueError:
        return None


def kind(values: list[str]) -> str:
    if not values:
        return "empty"
    sample = values[:300]
    if sum(bool(to_date(v) or to_date(v, True)) for v in sample) >= 0.6 * len(sample):
        return "date"
    if sum(bool(re.fullmatch(r"[-₹,.\d\s]+", v)) for v in sample) >= 0.8 * len(sample):
        return "phone" if sum(bool(PHONE_RX.search(v)) for v in sample) >= 0.5 * len(sample) else "number"
    return "text"


def header_row(grid: list[list[str]]) -> int:
    """The row in the first 30 with the most short text cells (headings), ignoring rows that look like data."""
    best, best_score = 0, -1
    for r, row in enumerate(grid[:30]):
        cells = [norm(c) for c in row if norm(c)]
        score = sum(1 for c in cells if not (to_date(c) or to_date(c, True)) and not re.fullmatch(r"[-₹,.\d\s]+", c) and len(c) <= 40)
        if score > best_score:
            best, best_score = r, score
    return best


def profile_tab(name: str, grid: list[list]):
    grid = [[norm(c) for c in row] for row in grid]
    if not grid:
        say(f"    (empty)")
        return
    h = header_row(grid)
    heads = grid[h]
    body = [r for r in grid[h + 1:] if any(r)]
    width = max([len(heads)] + [len(r) for r in body[:500]])
    say(f"    headings in row {h + 1} · {len(body)} filled rows · {width} columns")
    date_cols = []
    for c in range(width):
        head = heads[c] if c < len(heads) else ""
        vals = [r[c] for r in body if c < len(r) and r[c]]
        if not head and not vals:
            continue
        fill = round(100 * len(vals) / len(body)) if body else 0
        k = kind(vals)
        line = f"      {c + 1:>2}. {head[:38] or '(no heading)':<38} {fill:>3}% filled · {k}"
        if k == "date":
            parts = [DATE_RX.match(v) for v in vals]
            firsts = [int(m.group(1)) for m in parts if m]
            seconds = [int(m.group(2)) for m in parts if m]
            month_first = max(seconds, default=0) > 12 >= max(firsts, default=0)   # typed as month/day/year
            ds = [d for d in (to_date(v, month_first) for v in vals) if d]
            if month_first:
                line += " (month/day order)"
            if ds:
                line += f" · {min(ds):%d %b %Y} → {max(ds):%d %b %Y}"
                date_cols.append((c, head, ds))
        elif k == "text" and vals:
            cnt = Counter(v.upper() for v in vals)
            if len(cnt) <= STATUS_MAX_DISTINCT and len(vals) >= 3 * len(cnt):   # repeated values only, not names
                line += " · values: " + ", ".join(f"{v[:20]} {n}" for v, n in cnt.most_common(STATUS_MAX_DISTINCT))
            else:
                line += f" · {len(cnt)} different values"
        say(line)
    if date_cols:          # rows per month from the best-filled date column
        c, head, ds = max(date_cols, key=lambda x: len(x[2]))
        months = Counter(d.strftime("%Y-%m") for d in ds if d.year >= 2025)
        recent = sorted(months.items())[-6:]
        if recent:
            say(f"    rows per month ({head or 'date column'}): " +
                ", ".join(f"{datetime.strptime(m, '%Y-%m'):%b %y} {n}" for m, n in recent))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        info = json.load(f)
    only = sys.argv[2].lower() if len(sys.argv) > 2 else ""
    session = AuthorizedSession(Credentials.from_service_account_info(info, scopes=SCOPES))
    say(f"Key: {info['client_email']}   ({datetime.now():%d %b %Y %H:%M})\n")

    for dept, sheets in SHEETS.items():
        for name, sid in sheets.items():
            if name in DONE_ALREADY or (only and only not in name.lower()):
                continue
            say(f"=== {dept} · {name}")
            r = get(session, f"{API}/{sid}", params={"fields": "sheets.properties(title,gridProperties)"}, timeout=60)
            if r.status_code != 200:
                say(f"  ✗ cannot read: {reason(r)}\n")
                continue
            props = [s["properties"] for s in r.json().get("sheets", [])]
            say(f"  {len(props)} tabs: " + ", ".join(p["title"] for p in props))
            for p in props[:MAX_TABS]:
                tab = p["title"]
                gp = p.get("gridProperties", {})
                say(f"  --- tab '{tab}' (grid {gp.get('rowCount')} × {gp.get('columnCount')})")
                a1 = "'" + tab.replace("'", "''") + "'"
                t0 = time.time()
                try:
                    v = get(session, f"{API}/{sid}/values/{quote(a1, safe='')}", timeout=120)
                except Exception as e:
                    say(f"    ✗ could not read ({type(e).__name__}) after {time.time() - t0:.0f}s")
                    continue
                if v.status_code != 200:
                    say(f"    ✗ {reason(v)}")
                    continue
                profile_tab(tab, v.json().get("values", []))
                say(f"    [{time.time() - t0:.0f}s]")
            if len(props) > MAX_TABS:
                say(f"  (+{len(props) - MAX_TABS} more tabs not profiled)")
            say()

    path = __file__.rsplit("scripts", 1)[0] + "profile.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out_lines))
    print(f"\nSaved to {path} — upload that file to Claude.")


if __name__ == "__main__":
    main()
