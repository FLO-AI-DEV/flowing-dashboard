"""Find tables in messy sheets by their headings, never by fixed cell positions.

Real sheets move: someone inserts a column, adds a title row on top, merges two heading cells, or pastes a second
block under the first. Code that says "delay is column AH" then silently reads the wrong numbers. This module looks
for the headings instead:

    COLS = [
        Col("party",   "PARTY NAME", "CLIENT", "CUSTOMER"),
        Col("qty",     "QTY", "PCS", "QUANTITY"),
        Col("date",    "ORDER DATE", "DATE"),
        Col("remarks", "REMARKS", required=False),
    ]
    df, layout = read_table(grid, COLS, tab="ORDERS")

* The heading row is found anywhere in the first `scan` rows (title rows, blank rows and notes above it are fine).
* A heading may be split over two rows ("PCS" under a merged "PRODUCTION" cell): both rows are tried together.
* Each heading can have several spellings; matching ignores case, spaces and punctuation ("Order Dt." = "ORDERDT").
* Exact matches win over "starts with", which wins over "contains", so "QTY" doesn't grab "QTY RECEIVED".
* A heading that was typed over or left blank can be found by position: `Col(..., after="ledger")` means "the column
  right after LEDGER", `before="order_type"` "the column right before ORDER TYPE". The guess is only kept when the
  column's data looks right (`expect="date"`, `expect=("BILL", "PO")`, or `expect="text"`).
* A required heading that is missing raises `SheetLayoutError` naming the tab and the headings it did see, so a
  changed sheet shows up as a clear "Delayed / layout changed" message instead of wrong figures.
* Blank rows, TOTAL rows and repeated heading rows (a second pasted block) are dropped from the data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from .core import norm_key


class SheetLayoutError(ValueError):
    """The tab no longer has a heading the dashboard needs."""

    def __init__(self, tab: str, missing: list[str], seen: list[str]):
        self.tab, self.missing, self.seen = tab, missing, seen
        super().__init__(
            f"Tab '{tab}': could not find column(s) {', '.join(missing)}. "
            f"Headings found: {', '.join(seen[:25]) or '(none)'}")


@dataclass(frozen=True)
class Col:
    """One column the dashboard needs: a field name, every heading spelling seen in the sheet, and optionally where it
    sits relative to another column (used only when no heading matches)."""
    field: str
    names: tuple[str, ...]
    required: bool = True
    after: str | None = None
    before: str | None = None
    expect: object = None

    def __init__(self, field: str, *names: str, required: bool = True, after: str | None = None,
                 before: str | None = None, expect=None):
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "names", tuple(names))
        object.__setattr__(self, "required", required)
        object.__setattr__(self, "after", after)
        object.__setattr__(self, "before", before)
        object.__setattr__(self, "expect", expect)

    @property
    def keys(self) -> list[str]:
        return [k for k in (norm_key(n) for n in self.names) if k]


@dataclass
class Layout:
    """Where the table was found — kept so /api/status can show it and tests can assert it."""
    tab: str
    header_row: int                      # 0-based row index of the (last) heading row
    columns: dict[str, int]              # field -> 0-based column index
    headings: dict[str, str]             # field -> the heading text actually matched
    missing: list[str] = field(default_factory=list)   # optional fields not found
    inferred: list[str] = field(default_factory=list)  # fields found by position, not by heading


# match strength: exact > starts with > contains
_EXACT, _PREFIX, _CONTAINS = 3, 2, 1


def _cell(row, i) -> str:
    return "" if i >= len(row) or row[i] is None else str(row[i])


def _ffill(row, width) -> list[str]:
    """Merged cells arrive as one value then blanks; carry the value right so 'PRODUCTION' covers its children."""
    out, last = [], ""
    for i in range(width):
        v = _cell(row, i).strip()
        last = v or last
        out.append(last)
    return out


def _labels(grid, r, width) -> list[list[str]]:
    """Candidate heading keys per column for heading row r: the cell alone, and parent + cell (two-row headings)."""
    row = grid[r]
    parent = _ffill(grid[r - 1], width) if r > 0 else [""] * width
    out = []
    for i in range(width):
        own = norm_key(_cell(row, i))
        cands = [own] if own else []
        par = norm_key(parent[i])
        if par and par != own:
            cands.append(par + own)
            if not own:                  # heading only in the merged parent cell
                cands.append(par)
        out.append(cands)
    return out


def _strength(key: str, label: str) -> int:
    if label == key:
        return _EXACT
    if label.startswith(key):
        return _PREFIX
    if len(key) >= 4 and key in label:
        return _CONTAINS
    return 0


def _match_row(grid, r, cols: list[Col], width):
    """Assign columns to fields for heading row r. Returns (score, {field: idx}, {field: heading})."""
    labels = _labels(grid, r, width)
    cands = []                           # (strength, alias order, field order, col idx, field)
    for fi, c in enumerate(cols):
        for ai, key in enumerate(c.keys):
            for ci, labs in enumerate(labels):
                s = max((_strength(key, lab) for lab in labs), default=0)
                if s:
                    cands.append((-s, ai, fi, ci, c.field))
    cands.sort()
    used_f, used_c, mapping = set(), set(), {}
    score = 0
    for neg_s, _ai, _fi, ci, f in cands:
        if f in used_f or ci in used_c:
            continue
        used_f.add(f)
        used_c.add(ci)
        mapping[f] = ci
        score += -neg_s
    parent = _ffill(grid[r - 1], width) if r > 0 else [""] * width
    headings = {f: (_cell(grid[r], i).strip() or parent[i]) for f, i in mapping.items()}
    return score, mapping, headings


_DATE_RE = re.compile(r"^\s*\d{1,2}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{2,4}")


def _looks(values: list[str], expect) -> bool:
    """Do most non-blank cells of a column look like what the field should hold?"""
    vals = [v.strip() for v in values if str(v).strip()]
    if not vals:
        return True                     # an empty column can't contradict the guess
    if expect == "date":
        ok = sum(bool(_DATE_RE.match(v)) or v.replace(".", "", 1).isdigit() and 20000 < float(v) < 80000 for v in vals)
    elif expect == "text":
        ok = sum(not _DATE_RE.match(v) and not v.replace(".", "", 1).isdigit() for v in vals)
    elif isinstance(expect, (tuple, list)):
        words = {norm_key(w) for w in expect}
        ok = sum(any(w in norm_key(v) for w in words) for v in vals)
    else:
        return True
    return ok >= 0.6 * len(vals)


def _infer(grid, r, cols: list[Col], mapping: dict, headings: dict, width: int) -> list[str]:
    """Fill fields that have no matching heading from their neighbours' positions. Returns the fields filled."""
    filled = []
    known = {k for c in cols for k in c.keys}
    sample = grid[r + 1:r + 41]
    for _ in range(2):                  # a second pass lets one inferred column anchor another
        for c in cols:
            if c.field in mapping:
                continue
            idx = None
            if c.after and c.after in mapping:
                idx = mapping[c.after] + 1
            elif c.before and c.before in mapping:
                idx = mapping[c.before] - 1
            if idx is None or idx < 0 or idx >= width or idx in mapping.values():
                continue
            head = norm_key(_cell(grid[r], idx))
            if head and any(_strength(k, head) for k in known):
                continue                # that column belongs to some other heading
            if not _looks([_cell(row, idx) for row in sample], c.expect):
                continue
            mapping[c.field] = idx
            headings[c.field] = _cell(grid[r], idx).strip()
            filled.append(c.field)
    return filled


def locate(grid, cols: list[Col], tab: str = "", scan: int = 30) -> Layout:
    """Find the heading row and the column of every field. Raises SheetLayoutError if a required field is missing."""
    if not grid:
        raise SheetLayoutError(tab, [c.field for c in cols if c.required], [])
    width = max(len(r) for r in grid[:scan + 1])
    required = {c.field for c in cols if c.required}
    best = None
    for r in range(min(scan, len(grid))):
        score, mapping, headings = _match_row(grid, r, cols, width)
        found_req = len(required & mapping.keys())
        key = (found_req, len(mapping), score)
        if best is None or key > best[0]:            # ties keep the earliest row
            best = (key, r, mapping, headings)
    _, r, mapping, headings = best
    inferred = _infer(grid, r, cols, mapping, headings, width)
    missing_req = sorted(required - mapping.keys(), key=[c.field for c in cols].index)
    if missing_req:
        seen = [h for h in (_cell(grid[r], i).strip() for i in range(width)) if h]
        raise SheetLayoutError(tab, missing_req, seen)
    missing = [c.field for c in cols if c.field not in mapping]
    return Layout(tab=tab, header_row=r, columns=mapping, headings=headings, missing=missing, inferred=inferred)


def _is_total(v: str) -> bool:
    k = norm_key(v)
    return k.startswith("TOTAL") or k.startswith("GRANDTOTAL") or k == "SUBTOTAL"


def read_table(grid, cols: list[Col], tab: str = "", scan: int = 30, key_fields: list[str] | None = None):
    """Grid -> (DataFrame with one column per field, Layout).

    Optional fields that were not found come back as empty strings, so callers never KeyError.
    A row is kept when at least one of `key_fields` (default: every required field) is non-blank, and it is not a
    TOTAL row or a repeated heading row.
    """
    lay = locate(grid, cols, tab=tab, scan=scan)
    rows = grid[lay.header_row + 1:]
    fields = [c.field for c in cols]
    data = {f: [(_cell(row, lay.columns[f]) if f in lay.columns else "") for row in rows] for f in fields}
    df = pd.DataFrame(data, columns=fields)
    if df.empty:
        return df, lay

    text = df.astype(str).apply(lambda s: s.str.strip())
    keys = key_fields or [c.field for c in cols if c.required] or fields
    has_key = (text[keys] != "").any(axis=1)
    is_total = text.apply(lambda s: s.map(_is_total)).any(axis=1)
    heading_keys = {f: norm_key(h) for f, h in lay.headings.items() if f not in lay.inferred}
    hits = pd.Series(0, index=df.index)
    for f, hk in heading_keys.items():
        if hk:
            hits += (text[f].map(norm_key) == hk).astype(int)
    is_repeat = hits >= min(2, len(heading_keys))   # a pasted second heading row, not a cell that says "DATE"
    keep = has_key & ~is_total & ~is_repeat
    return df[keep].reset_index(drop=True), lay
