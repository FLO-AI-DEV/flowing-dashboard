"""Exact look-ups over every row of the Flo-Wing sheets, for the chatbot.

The model never "remembers" figures. The backend already keeps the latest copy of every sheet in memory (re-read
every minute), so when a question needs data the model calls one of these tools and gets exact rows and totals:

  query   one table: filters, group by, sum / count / average / min / max, sort, top N, or matching rows
  search  free text ("kopal", "FWPO-00166", "dupatta missing") across every row of every table; scope="all"
          also searches every other tab of the four sheets (Sheet18, worksheet, ahemdabad working, ...)

Tables (friendly names and columns) are built from the same parsed data the pages use, so the chat and the
pages always agree.
"""
from __future__ import annotations

import difflib
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from ..config import SHEET_REGISTRY
from ..core import norm_key, today_ist
from ..dashboards.generic import detect_header, grid_frame, typed

MAX_ROWS = 50
RAW_TTL = 600            # other tabs (not used by any page) are re-read at most every 10 minutes
MAX_RAW_TABS = 40

# table -> (sheet kind, what one row is)
TABLES = {
    "po_lines": ("order_status", "one item/design on a purchase order (Order Status sheet, PO Master tab)"),
    "supplier_bills": ("dues", "one unpaid supplier bill on the chosen dues list (DUES PAYMENT SUPPLIERS sheet)"),
    "vendor_orders": ("order_to_vendors", "one order sent to a vendor (Order to vendors sheet)"),
    "enquiries": ("supplier_enquiry", "one supplier enquiry/complaint and its follow-up (Supplier's Enquiry Sheet, Sheet1)"),
    "po_by_city": ("supplier_enquiry", "one supplier in a city block waiting for / given a PO (Supplier's Enquiry Sheet tab)"),
    "terms_approval": ("supplier_enquiry", "payment terms agreed with one supplier (Terms Approval tab)"),
    "inactive_suppliers": ("supplier_enquiry", "one supplier not bought from in 2025-26 (Inactive25-26 tab)"),
    "purchase_issues": ("supplier_enquiry", "one purchase problem (purchase issues tab)"),
}
MONEY = {"order_amt", "recv_amt", "pending_amt", "overdue_amt", "po_rate", "net_payable", "pending"}

OPS = ("not contains", "contains", "starts with", ">=", "<=", "!=", "=", ">", "<", " in ")
FILTER = re.compile(r"^\s*(.+?)\s*(not contains|contains|starts with|>=|<=|!=|==|=|>|<|\bin\b|\bis\b)\s*(.*?)\s*$", re.I)
AGG = re.compile(r"^\s*(sum|count|avg|average|mean|min|max|nunique|unique|distinct)\s*(?:\(|of\s+|\s)?\s*([\w %.]*?)\)?\s*$", re.I)
STOP = {"the", "a", "an", "of", "for", "ka", "ki", "ke", "ko", "me", "mein", "hai", "h", "kya", "and", "in", "on",
        "se", "wala", "wali", "about", "show", "find", "details", "detail", "row", "rows", "batao", "please"}


def snake(name: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(name).strip().lower()).strip("_")
    return s or "column"


def _cell(v):
    if v is None:
        return None
    if isinstance(v, (pd.Timestamp, np.datetime64)):
        v = pd.Timestamp(v)
        return None if pd.isna(v) else v.strftime("%d/%m/%Y")
    if isinstance(v, (float, np.floating)):
        if not np.isfinite(v):
            return None
        return int(v) if float(v).is_integer() else round(float(v), 2)
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    s = str(v).strip()
    return s or None


def _records(df: pd.DataFrame, cols: list[str] | None = None, compact: bool = False) -> list[dict]:
    """Rows as dicts without blanks. compact=True also drops zeros and caps the fields (search results)."""
    cols = cols or list(df.columns)
    out = []
    for r in df[cols].itertuples(index=False):
        row = {c: _cell(v) for c, v in zip(cols, r)}
        row = {k: v for k, v in row.items() if v is not None and not (compact and v == 0)}
        if compact and len(row) > 14:
            row = dict(list(row.items())[:14])
        out.append(row)
    return out


def _to_number(text: str):
    t = str(text).strip().lower().replace(",", "").replace("₹", "").replace("rs", "").strip()
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*(cr|crore|l|lakh|lac|k|thousand|%)?", t)
    if not m:
        return None
    v = float(m.group(1))
    mult = {"cr": 1e7, "crore": 1e7, "l": 1e5, "lakh": 1e5, "lac": 1e5, "k": 1e3, "thousand": 1e3}.get(m.group(2) or "", 1)
    return v * mult


def _to_date(text: str):
    t = str(text).strip()
    for dayfirst in (False, True) if re.match(r"\d{4}-", t) else (True,):
        try:
            v = pd.to_datetime(t, dayfirst=dayfirst)
            if not pd.isna(v):
                return pd.Timestamp(v).normalize()
        except (ValueError, TypeError, OverflowError):
            continue
    return None


class ToolError(Exception):
    pass


class DataTools:
    """Built once per data version; every method is read-only."""

    def __init__(self, store):
        self.store = store
        self._lock = threading.Lock()
        self._cache: tuple[str, dict] | None = None
        self._pool = ThreadPoolExecutor(max_workers=6)

    # ------------------------------------------------------------------------------------------- tables
    def _datasets(self):
        return self.store.datasets(["order_status", "dues", "order_to_vendors", "supplier_enquiry"])

    def tables(self) -> dict[str, pd.DataFrame]:
        ds = self._datasets()
        version = "|".join(f"{k}:{d.version}" for k, d in ds.items())
        with self._lock:
            if self._cache and self._cache[0] == version:
                return self._cache[1]
        t = build_tables(ds)
        with self._lock:
            self._cache = (version, t)
        return t

    def version(self) -> str:
        return "|".join(f"{k}:{d.version}" for k, d in self._datasets().items())

    def catalog(self, max_values: int = 10) -> str:
        """Tables, columns and the values of short text columns, for the model's instructions."""
        lines = []
        for name, df in self.tables().items():
            lines.append(f"* {name} ({len(df)} rows): {TABLES[name][1]}")
            cols = []
            for c in df.columns:
                s = df[c]
                if pd.api.types.is_datetime64_any_dtype(s):
                    cols.append(f"{c} (date)")
                elif pd.api.types.is_numeric_dtype(s):
                    cols.append(f"{c} (₹)" if c in MONEY else f"{c} (number)")
                else:
                    vals = [v for v in s.dropna().astype(str).str.strip().unique() if v][: max_values + 1]
                    if 0 < len(vals) <= max_values and sum(len(v) for v in vals) < 260:
                        cols.append(f"{c} [{', '.join(vals)}]")
                    else:
                        cols.append(c)
            lines.append("  columns: " + "; ".join(cols))
        tabs = []
        for kind, cfg in SHEET_REGISTRY.items():
            try:
                tabs.append(f"{cfg['name']}: " + ", ".join(t.strip() for t in self.store.all_tabs(kind)))
            except Exception:  # noqa: BLE001 - a sheet that can't be read just isn't listed
                continue
        lines.append("Tabs of the sheets (search scope 'all' reads any of them): " + " | ".join(tabs))
        return "\n".join(lines)

    # -------------------------------------------------------------------------------------------- query
    def _column(self, df: pd.DataFrame, name: str) -> str:
        n = snake(name)
        if n in df.columns:
            return n
        alias = {"vendor": "supplier", "supplier": "vendor", "party": "supplier", "status": "delivery_status",
                 "pending": "pending_amt", "pending_value": "pending_amt", "handler": "handled_by",
                 "amount": "net_payable", "net": "net_payable", "date": "bill_date"}.get(n)
        if alias and alias in df.columns:
            return alias
        hit = difflib.get_close_matches(n, list(df.columns), n=1, cutoff=0.6)
        if hit:
            return hit[0]
        raise ToolError(f"No column '{name}'. Columns: {', '.join(df.columns)}")

    def _apply(self, df: pd.DataFrame, flt: str) -> tuple[pd.DataFrame, str | None]:
        m = FILTER.match(flt or "")
        if not m:
            raise ToolError(f"Can't read filter '{flt}'. Write it like: vendor contains kesar / pending_amt > 0 / "
                            f"month = July-26 / po_date >= 2026-07-01")
        col, op, val = self._column(df, m.group(1)), m.group(2).lower().strip(), m.group(3).strip().strip("'\"")
        op = {"==": "=", "is": "="}.get(op, op)
        s = df[col]
        note = None
        if pd.api.types.is_datetime64_any_dtype(s) and op in ("=", "!=", ">", ">=", "<", "<="):
            mm = re.fullmatch(r"([a-zA-Z]{3,9})[\s-]*(\d{2,4})?", val)
            if mm and op in ("=", "!="):            # "July 2026" / "Jul-26" -> whole month
                try:
                    mon = pd.Timestamp(f"1 {mm.group(1)[:3]} 2000").month
                except ValueError:
                    raise ToolError(f"Can't read date '{val}'")
                y = int(mm.group(2)) if mm.group(2) else today_ist().year
                y = y + 2000 if y < 100 else y
                mask = (s.dt.month == mon) & (s.dt.year == y)
                return df[mask if op == "=" else ~mask], None
            d = _to_date(val)
            if d is None:
                raise ToolError(f"Can't read date '{val}' (use 2026-07-01)")
            day = s.dt.normalize()
            mask = {"=": day == d, "!=": day != d, ">": day > d, ">=": day >= d, "<": day < d, "<=": day <= d}[op]
            return df[mask.fillna(False)], None
        if pd.api.types.is_numeric_dtype(s) and op in ("=", "!=", ">", ">=", "<", "<="):
            v = _to_number(val)
            if v is None:
                raise ToolError(f"'{val}' is not a number")
            mask = {"=": s == v, "!=": s != v, ">": s > v, ">=": s >= v, "<": s < v, "<=": s <= v}[op]
            return df[mask.fillna(False)], None
        text = s.astype(str).str.strip().str.lower().str.replace(r"\s+", " ", regex=True)
        v = re.sub(r"\s+", " ", val.lower())
        if op == "in":
            opts = [x.strip() for x in re.split(r"[,|/]", v) if x.strip()]
            return df[text.isin(opts)], None
        if op == "contains":
            return df[text.str.contains(v, regex=False)], None
        if op == "not contains":
            return df[~text.str.contains(v, regex=False)], None
        if op == "starts with":
            return df[text.str.startswith(v)], None
        if op in ("=", "!="):
            mask = text == v
            if op == "=" and not mask.any():           # forgiving: "kesar" finds "KESAR ETHNIC (JAIPUR)"
                mask = text.str.contains(v, regex=False)
                if mask.any():
                    note = f"no exact '{val}' in {col}; used contains"
                else:
                    near = difflib.get_close_matches(v, list(text.unique()), n=5, cutoff=0.5)
                    note = f"nothing matches {col} = '{val}'" + (f"; close values: {', '.join(near)}" if near else "")
            return df[mask if op == "=" else ~mask], note
        raise ToolError(f"Operator '{op}' doesn't work on text column {col}")

    def query(self, table: str, filters=None, group_by=None, metrics=None, sort_by: str | None = None,
              descending: bool = True, limit: int = 20, columns=None) -> dict:
        tabs = self.tables()
        name = snake(table or "")
        if name not in tabs:
            hit = difflib.get_close_matches(name, list(tabs), n=1, cutoff=0.5)
            if not hit:
                raise ToolError(f"No table '{table}'. Tables: {', '.join(tabs)}")
            name = hit[0]
        df = tabs[name]
        notes = []
        for f in filters or []:
            if str(f).strip():
                df, note = self._apply(df, str(f))
                if note:
                    notes.append(note)
        limit = max(1, min(int(limit or 20), MAX_ROWS))
        out = {"table": name, "rows_matched": int(len(df))}
        if notes:
            out["notes"] = notes
        aggs = []
        for m in metrics or []:
            mm = AGG.match(str(m))
            if not mm:
                raise ToolError(f"Can't read metric '{m}'. Use e.g. 'sum pending_amt', 'count', 'avg overdue_days'")
            op = {"average": "mean", "avg": "mean", "unique": "nunique", "distinct": "nunique"}.get(mm.group(1).lower(),
                                                                                                      mm.group(1).lower())
            col = self._column(df, mm.group(2)) if mm.group(2).strip() else None
            if op != "count" and col is None:
                raise ToolError(f"Metric '{m}' needs a column")
            if op in ("sum", "mean") and col and not pd.api.types.is_numeric_dtype(df[col]):
                raise ToolError(f"{col} is not a number column")
            aggs.append((op, col, f"{op}_{col}" if col else "count"))

        def agg_frame(g) -> dict:
            row = {}
            for op, col, label in aggs:
                if op == "count":
                    row[label] = int(len(g)) if col is None else int(g[col].notna().sum())
                elif op == "nunique":
                    row[label] = int(g[col].replace("", np.nan).nunique())
                else:
                    v = getattr(g[col], op)()
                    row[label] = _cell(v)
            return row

        groups = [self._column(df, g) for g in ([group_by] if isinstance(group_by, str) else (group_by or [])) if g]
        if groups:
            aggs = aggs or [("count", None, "count")]
            rows = []
            for key, g in df.groupby(groups, dropna=False, sort=False):
                key = key if isinstance(key, tuple) else (key,)
                rows.append({**{c: _cell(k) for c, k in zip(groups, key)}, **agg_frame(g)})
            sk = snake(sort_by) if sort_by else aggs[0][2]
            sk = sk if any(sk in r for r in rows) else aggs[0][2]
            filled = [r for r in rows if r.get(sk) is not None]
            empty = [r for r in rows if r.get(sk) is None]
            numeric = all(isinstance(r[sk], (int, float)) for r in filled)
            filled.sort(key=lambda r: r[sk] if numeric else str(r[sk]).lower(), reverse=descending)
            rows = filled + empty
            out["groups"] = len(rows)
            out["result"] = rows[:limit]
            out["overall"] = agg_frame(df)
            if len(rows) > limit:
                out["more"] = f"{len(rows) - limit} more groups not shown"
            return out
        if aggs:
            out["result"] = agg_frame(df)
            return out
        if sort_by:
            sc = self._column(df, sort_by)
            df = df.sort_values(sc, ascending=not descending, na_position="last")
        cols = [self._column(df, c) for c in (columns or [])] or None
        out["result"] = _records(df.head(limit), cols)
        if len(df) > limit:
            out["more"] = f"{len(df) - limit} more rows not shown"
        return out

    # ------------------------------------------------------------------------------------------- search
    def search(self, text: str, scope: str = "data", limit: int = 15) -> dict:
        words = [w for w in re.findall(r"[\w/.-]+", (text or "").lower()) if w not in STOP]
        if not words:
            raise ToolError("Give a name, PO number or words to search for")
        limit = max(1, min(int(limit or 15), 30))
        hits, partial = [], []
        for name, df in self.tables().items():
            blob = _blob(df)
            mask = np.ones(len(df), dtype=bool)
            for w in words:
                mask &= blob.str.contains(w, regex=False).to_numpy()
            for rec in _records(df[mask].head(limit), compact=True):
                hits.append({"table": name, "row": rec})
            if not mask.any() and len(words) > 1:
                anym = np.zeros(len(df), dtype=bool)
                for w in words:
                    if len(w) >= 4:
                        anym |= blob.str.contains(w, regex=False).to_numpy()
                for rec in _records(df[anym].head(3), compact=True):
                    partial.append({"table": name, "row": rec})
        if scope == "all" or not hits:
            for item in self._raw_search(words, limit, all_tabs=scope == "all"):
                hits.append(item)
        out = {"query": text, "matches": len(hits), "results": hits[:limit]}
        if len(hits) > limit:
            out["more"] = f"{len(hits) - limit} more matches; narrow the search or use query with filters"
        if not hits and partial:
            out["partial_matches"] = partial[:8]
        if not hits and not partial:
            out["note"] = "Nothing found. Check the spelling, or try a shorter part of the name."
        return out

    def _raw_tabs(self, all_tabs: bool) -> list[tuple[str, str, str]]:
        used = {"order_status": {"po master"}, "order_to_vendors": set(),
                "supplier_enquiry": {"sheet1", "supplier's enquiry sheet", "terms approval", "inactive25-26",
                                     "purchase issues"}}
        out = []
        for kind, cfg in SHEET_REGISTRY.items():
            if kind == "dues" and not all_tabs:
                continue
            try:
                tabs = self.store.all_tabs(kind)
            except Exception:  # noqa: BLE001
                continue
            for t in tabs:
                if t.strip().lower() in used.get(kind, set()):
                    continue
                if kind == "order_to_vendors" and not all_tabs:
                    continue
                out.append((kind, cfg["id"], t))
        return out[:MAX_RAW_TABS]

    def _raw_grid(self, sid, tab):
        return self.store.raw.get(("grid-search", sid, tab), RAW_TTL,
                                  lambda: self.store.source.get_values(sid, tab, True)).value

    def _raw_search(self, words, limit, all_tabs) -> list[dict]:
        tabs = self._raw_tabs(all_tabs)
        if not tabs:
            return []

        def one(item):
            kind, sid, tab = item
            try:
                grid = self._raw_grid(sid, tab)
            except Exception:  # noqa: BLE001 - one unreadable tab doesn't stop the search
                return []
            if not grid:
                return []
            h = detect_header(grid)
            head = [str(c).strip() for c in grid[h]] if h < len(grid) else []
            found = []
            for i, row in enumerate(grid):
                line = " ".join(str(c) for c in row).lower()
                if line.strip() and all(w in line for w in words):
                    cells = {}
                    for j, c in enumerate(row):
                        if str(c).strip():
                            key = head[j] if j < len(head) and head[j] and i > h else f"col {j + 1}"
                            cells[key] = str(c).strip()
                    found.append({"sheet": SHEET_REGISTRY[kind]["name"], "tab": tab.strip(), "sheet_row": i + 1,
                                  "row": cells})
                    if len(found) >= limit:
                        break
            return found

        out = []
        for part in self._pool.map(one, tabs):
            out.extend(part)
        return out


def _blob(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series([], dtype=str)
    parts = [df[c].map(lambda v: "" if v is None or (isinstance(v, float) and np.isnan(v)) else
                       (v.strftime("%d/%m/%Y") if isinstance(v, pd.Timestamp) else str(v))) for c in df.columns]
    s = parts[0]
    for p in parts[1:]:
        s = s + " | " + p
    return s.str.lower()


# ----------------------------------------------------------------------------------------------- building
def build_tables(ds: dict) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    today = today_ist()
    o = ds["order_status"].data
    if o is not None and not o.empty:
        out["po_lines"] = pd.DataFrame({
            "po": o["po"], "po_date": o["po_date"], "month": o["month"], "vendor": o["vendor"], "city": o["city"],
            "category": o["category"], "department": o["department"], "item": o["item"], "design": o["design"],
            "supplier_design": o["supplier_design"], "fabric": o["fabric"], "order_qty": o["order_qty"],
            "po_rate": o["po_rate"], "order_amt": o["order_amt"], "recv_qty": o["recv_qty"], "recv_amt": o["recv_amt"],
            "pending_qty": o["pending_qty"], "pending_amt": o["pending"], "delivery_date": o["delivery_date"],
            "received_date": o["received_date"], "delivery_status": o["timing"], "overdue_days": o["overdue_days"],
            "delay_days": o["delay_days"], "overdue_amt": o["overdue_amt"], "overdue_qty": o["overdue_qty"],
            "remark": o["remark"]}).reset_index(drop=True)
    p = ds["dues"].data
    if p is not None and not p["d"].empty:
        d = p["d"].copy()
        d["key"] = d["party"].map(norm_key)
        terms = p.get("terms")
        if terms is not None and len(terms):
            d = d.merge(terms, on="key", how="left")
        for c in ("Agency", "Credit Days", "Disc %"):
            if c not in d.columns:
                d[c] = ""
        overdue = np.where(d["due_on"].notna() & (d["due_on"] < today), (today - d["due_on"]).dt.days, 0)
        out["supplier_bills"] = pd.DataFrame({
            "supplier": d["party"], "bill_no": d["ref"], "bill_date": d["bill_date"], "due_on": d["due_on"],
            "net_payable": d["net"], "days_overdue": overdue,
            "due_status": np.select([d["due_on"].isna(), d["due_on"] < today, d["due_on"] <= today + pd.Timedelta(days=7)],
                                    ["No due date", "Overdue", "Due in next 7 days"], "Due later"),
            "agency": d["Agency"].fillna("").astype(str).str.strip(), "credit_days": d["Credit Days"].fillna("").astype(str),
            "discount": d["Disc %"].fillna("").astype(str), "remark": d["remark"]}).reset_index(drop=True)
    g = ds["order_to_vendors"].data
    if g:
        frame, _ = grid_frame(g)
        if not frame.empty:
            t, _ = typed(frame)
            cols, seen = [], {}
            for c in t.columns:
                n = snake(c)
                seen[n] = seen.get(n, 0) + 1
                cols.append(n if seen[n] == 1 else f"{n}_{seen[n]}")
            t.columns = cols
            out["vendor_orders"] = t.reset_index(drop=True)
    e = ds["supplier_enquiry"].data
    if e:
        q = e.get("enquiries")
        if q is not None and not q.empty:
            out["enquiries"] = pd.DataFrame({
                "date": q["date"], "month": q["month"], "supplier": q["party"], "enquiry": q["about"], "topic": q["topic"],
                "status": q["status"], "handled_by": q["handler"], "concerned_person": q["person"],
                "days_pending": q["age"], "contact": q["contact"], "notes": q["notes"]}).reset_index(drop=True)
        c = e.get("city_po")
        if c is not None and not c.empty:
            out["po_by_city"] = pd.DataFrame({
                "city": c["city"], "supplier": c["supplier"], "order_date": c["date"], "order_date_as_written": c["date_text"],
                "po_status": c["status"], "days_pending": c["age"]}).reset_index(drop=True)
        t = e.get("terms")
        if t is not None and not t.empty:
            out["terms_approval"] = pd.DataFrame({
                "date": t["date"], "supplier": t["supplier"], "supplier_code": t["code"], "payment_days": t["days"],
                "discount": t["discount"], "other_terms": t["other"], "confirmed_by": t["confirmed_by"],
                "confirmed_on": t["confirmed_on"], "approval": t["status"], "approved_by": t["approved_by"],
                "entered_in_software_by": t["entry_by"]}).reset_index(drop=True)
        i = e.get("inactive")
        if i is not None and not i.empty:
            pc = next((c for c in i.columns if "PARTY" in norm_key(c)), i.columns[0])
            qc = next((c for c in i.columns if "QTY" in norm_key(c)), None)
            frame = pd.DataFrame({"supplier": i[pc].astype(str).str.strip()})
            if qc:
                frame["qty_bought_earlier"] = pd.to_numeric(i[qc].astype(str).str.replace(",", ""), errors="coerce")
            out["inactive_suppliers"] = frame[frame["supplier"] != ""].reset_index(drop=True)
        s = e.get("issues")
        if s is not None and not s.empty:
            t2 = s.copy()
            t2.columns = [snake(c) for c in t2.columns]
            out["purchase_issues"] = t2.reset_index(drop=True)
    return out
