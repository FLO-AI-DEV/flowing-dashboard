"""Any tab as a clean table, plus a summary for 'Order to vendors' (whose layout is detected by column names).

The header row is found automatically (the row with the most text labels near the top), so title rows above the
headers don't matter. Numbers stay numbers; dates arrive from Google as serial numbers and are shown as dd/mm/yyyy.
"""
from __future__ import annotations

import re

import pandas as pd

from ..core import clean_text, is_number_text, norm_key, num, parse_dates
from ..core import today_ist
from ..tables import kpi, notice, table
from . import extra as ex


def detect_header(grid, scan=20) -> int:
    best, score = 0, -1
    for i, row in enumerate(grid[:scan]):
        s = sum(1 for c in row if isinstance(c, str) and c.strip() and not is_number_text(c))
        if s > score:
            best, score = i, s
    return best


def grid_frame(grid) -> tuple[pd.DataFrame, int]:
    """grid -> DataFrame with unique header names (empty rows dropped), and the 0-based header row."""
    if not grid:
        return pd.DataFrame(), 0
    h = detect_header(grid)
    width = max(len(r) for r in grid)
    head, seen = [], {}
    for i in range(width):
        v = grid[h][i] if i < len(grid[h]) else ""
        name = re.sub(r"\s+", " ", str(v)).strip() or f"Column {i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 1
        head.append(name)
    rows = [list(r) + [""] * (width - len(r)) for r in grid[h + 1:]]
    rows = [r for r in rows if any(str(c).strip() for c in r)]
    df = pd.DataFrame(rows, columns=head) if rows else pd.DataFrame(columns=head)
    # drop columns that are completely empty and unnamed
    keep = [c for c in df.columns if not (c.startswith("Column ") and not df[c].astype(str).str.strip().any())]
    return df[keep], h


DATE_WORDS = ("DATE", "DT")


def typed(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Numbers -> float, date columns -> dates, the rest -> clean text. Returns (df, formats)."""
    out, fmts = pd.DataFrame(index=df.index), {}
    for c in df.columns:
        s = df[c]
        k = norm_key(c)
        nonblank = s[s.astype(str).str.strip() != ""]
        if any(w in k for w in DATE_WORDS) and len(nonblank):
            dts = parse_dates(s)
            if dts.notna().sum() >= 0.6 * len(nonblank):
                out[c] = dts
                fmts[c] = "date"
                continue
        numeric = nonblank.map(lambda v: isinstance(v, (int, float)) or is_number_text(v))
        if len(nonblank) and numeric.mean() >= 0.9:
            out[c] = num(s)
            fmts[c] = "dec" if (out[c] % 1 != 0).any() else "int"
        else:
            out[c] = clean_text(s)
            fmts[c] = "text"
    return out, fmts


def sheet_view(grid, q: str = "", limit: int = 2000) -> dict:
    df, h = grid_frame(grid)
    if df.empty:
        return {"header_row": h + 1, "total": 0, "shown": 0, "table": table(df)}
    t, fmts = typed(df)
    if q:
        needle = q.lower()
        mask = df.astype(str).apply(lambda col: col.str.lower().str.contains(needle, regex=False)).any(axis=1)
        t = t[mask]
    total = len(t)
    tb = table(t.head(limit), fmts, sort=False)
    return {"header_row": h + 1, "total": int(total), "shown": int(min(total, limit)), "table": tb}


def _col(cols, *names):
    keys = {norm_key(c): c for c in cols}
    for n in names:
        if norm_key(n) in keys:
            return keys[norm_key(n)]
    for n in names:
        for k, c in keys.items():
            if norm_key(n) in k:
                return c
    return None


def otv_dashboard(grid, f: dict) -> dict:
    df, h = grid_frame(grid)
    if df.empty:
        return {"empty": True, "notices": [notice("This tab has no rows.", "info")], "kpis": [], "options": {}}
    t, fmts = typed(df)
    vendor = _col(t.columns, "Vendor Name", "Vender Name", "Vendor", "Vender", "Party Name", "Party", "Supplier", "Fabricator")
    status = _col(t.columns, "Status", "Order Status", "Stage")
    amount = next((c for c in [_col(t.columns, "Order Amt", "Order Amount", "Amount", "Amt", "Value", "Total")]
                   if c and fmts.get(c) in ("int", "dec")), None)
    qty = next((c for c in [_col(t.columns, "Order Qty", "Qty", "Quantity", "Pcs")] if c and fmts.get(c) in ("int", "dec")), None)
    date = next((c for c in [_col(t.columns, "Order Date", "PO Date", "Date")] if c and fmts.get(c) == "date"), None)
    opts = {"period": ex.PERIODS if date else []}
    if vendor:
        opts["vendor"] = sorted(v for v in t[vendor].unique() if v)
        opts["supplier_type"] = ex.SUPPLIER_TYPES if ex.is_msme(t[vendor]).any() else []
    if status:
        opts["status"] = sorted(v for v in t[status].unique() if v)
    if amount:
        band = ex.amount_band(t[amount])
        opts["amount"] = [a for a in ex.AMOUNTS if (band == a).any()]
    x = t
    if f.get("vendor") and vendor:
        x = x[x[vendor].isin(f["vendor"])]
    if f.get("status") and status:
        x = x[x[status].isin(f["status"])]
    if f.get("supplier_type") and vendor:
        x = x[ex.supplier_type(x[vendor], f["supplier_type"])]
    if f.get("amount") and amount:
        x = x[ex.amount_band(x[amount]).isin(f["amount"])]
    rng = ex.period_range(f, today_ist()) if date else None
    if rng:
        x = x[ex.in_period(x[date], rng)]
    if f.get("q"):
        x = x[ex.search(x, [c for c in x.columns if fmts.get(c) in ("text", "date")], f["q"])]

    kpis = [kpi("Rows", len(x), "", id="rows")]
    if vendor:
        kpis.append(kpi("Vendors", x[vendor].replace("", pd.NA).nunique(), "", id="vendors"))
    if qty:
        kpis.append(kpi(f"Total {qty.lower()}", float(x[qty].sum()), "pcs", id="qty"))
    if amount:
        kpis.append(kpi(f"Total {amount.lower()}", float(x[amount].sum()), "", "inr", id="amount"))

    def share(col):
        val = x.groupby(col)[amount].sum() if amount else x.groupby(col).size()
        val = val.sort_values(ascending=False)
        return [{"label": (k or "(BLANK)"), "value": float(v)} for k, v in val.items()]

    return {
        "options": opts,
        "notices": [] if (vendor or status) else [notice(
            "No vendor or status column was recognised on this tab, so only the rows are shown.", "info")],
        "detected": {"vendor": vendor, "status": status, "amount": amount, "qty": qty, "date": date,
                     "header_row": h + 1},
        "kpis": kpis,
        "charts": {"by_status": share(status) if status else [], "by_vendor": share(vendor) if vendor else [],
                   "money": bool(amount)},
        "tables": {"rows": table(x.head(2000), fmts, sort=False)},
        "rows_total": int(len(x)),
    }
