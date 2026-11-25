"""Data store: reads the sheets through a source, caches the grids for LIVE_TTL seconds, parses them once per change.

- Only one request per sheet tab is in flight at a time (others wait for it), so a burst of users costs Google
  one read per minute, not one per user.
- If Google fails and an older copy exists, the older copy is served and the dataset is marked stale.
- Parsed datasets are cached by the version (hash) of the grids they came from.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from .config import SHEET_REGISTRY, Settings
from .core import parse_dates, today_ist
from .dashboards import orders as ords
from .dashboards import enquiries as enqs
from .dashboards import payments as pays
from .sources.google import SheetAccessError

KINDS = ["orders", "payments"]
REFRESH_AHEAD = 0.5          # a cached read older than half its life is re-read in the background
OLD_TAB_TTL = 6 * 3600      # month tabs older than last month are re-read every 6 hours, not every minute


# The PO log has ~12,000 rows (and keeps growing). The dashboard reads only the rows of the chosen time window:
# column A (the order date, one cheap read) tells which rows are in the window, then only those rows are read.
PO_WINDOWS = {"30d": ("Last 30 days", 30), "60d": ("Last 60 days", 60), "90d": ("Last 90 days", 90),
              "fy": ("This financial year", None)}
DEFAULT_PO_WINDOW = "60d"
PO_LAST_COL = "V"            # A..T is the form; two spare columns


def po_window_start(window: str, today=None) -> pd.Timestamp:
    label, days = PO_WINDOWS.get(window, PO_WINDOWS[DEFAULT_PO_WINDOW])
    today = pd.Timestamp(today) if today is not None else today_ist()
    return pays.FY_START if days is None else max(today.normalize() - pd.Timedelta(days=days), pays.FY_START)


def _now() -> float:
    return time.time()


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else None


def _digest(obj) -> str:
    return hashlib.sha1(json.dumps(obj, default=str, separators=(",", ":")).encode()).hexdigest()[:12]


@dataclass
class Entry:
    value: object
    fetched_at: float
    expires_at: float
    version: str = ""
    error: str | None = None


@dataclass
class Dataset:
    kind: str
    data: object | None
    fetched_at: float | None
    version: str
    error: str | None = None
    stale: bool = False
    tabs: list = field(default_factory=list)


class TTLCache:
    def __init__(self):
        self._data: dict = {}
        self._locks: dict = {}
        self._guard = threading.Lock()

    def _lock(self, key):
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def get(self, key, ttl: float, loader, versioned=False) -> Entry:
        e = self._data.get(key)
        if e is not None and e.expires_at > _now():
            if _now() - e.fetched_at > REFRESH_AHEAD * ttl:      # getting old: re-read in the background, serve this now
                self._reload_async(key, ttl, loader, versioned)
            return e
        with self._lock(key):
            return self._reload(key, ttl, loader, versioned)

    def _reload(self, key, ttl, loader, versioned) -> Entry:
        """Call with the key's lock held. Keeps the last good copy when Google fails."""
        e = self._data.get(key)
        if e is not None and e.expires_at > _now() and _now() - e.fetched_at <= REFRESH_AHEAD * ttl:
            return e                                              # someone else just did it
        try:
            value = loader()
        except Exception as ex:
            if e is not None:              # serve the last good copy, retry soon
                stale = Entry(e.value, e.fetched_at, _now() + min(ttl, 20), e.version, str(ex))
                self._data[key] = stale
                return stale
            raise
        t = _now()
        fresh = Entry(value, t, t + ttl, _digest(value) if versioned else "")
        self._data[key] = fresh
        return fresh

    def _reload_async(self, key, ttl, loader, versioned):
        lock = self._lock(key)
        if not lock.acquire(blocking=False):                      # already being re-read
            return

        def run():
            try:
                self._reload(key, ttl, loader, versioned)
            except Exception:
                pass
            finally:
                lock.release()
        threading.Thread(target=run, daemon=True).start()

    def clear_live(self, keep):
        """Drops cached entries except those `keep(key)` says to keep (old month tabs are not worth re-reading)."""
        with self._guard:
            for k in [k for k in self._data if not keep(k)]:
                del self._data[k]

    def clear(self):
        with self._guard:
            self._data.clear()


class DataStore:
    def __init__(self, source, settings: Settings):
        self.source = source
        self.settings = settings
        self.raw = TTLCache()
        self._parsed: dict = {}
        self._parsed_lock = threading.Lock()
        self._last_refresh = 0.0
        self._pool = ThreadPoolExecutor(max_workers=8)    # grid fetches (never wait on anything)
        self._outer = ThreadPoolExecutor(max_workers=5)   # datasets (wait on grid fetches)

    # -- low level ---------------------------------------------------------------------------------------------
    def tabs(self, sheet_id) -> list[tuple[str, int]]:
        return self.raw.get(("tabs", sheet_id), self.settings.tab_ttl,
                            lambda: self.source.list_tabs(sheet_id)).value

    def grid(self, sheet_id, tab, formatted=False, ttl=None) -> Entry:
        return self.raw.get(("grid", sheet_id, tab, formatted), ttl or self.settings.live_ttl,
                            lambda: self.source.get_values(sheet_id, tab, formatted), versioned=True)

    def part(self, sheet_id, tab, a1, ttl=None) -> Entry:
        """One A1 range of a tab (cached like a grid)."""
        return self.raw.get(("part", sheet_id, tab, a1), ttl or self.settings.live_ttl,
                            lambda: self.source.get_range(sheet_id, tab, a1), versioned=True)

    def formulas(self, sheet_id, tab, col_letter) -> Entry:
        def load():
            try:
                return self.source.get_formulas(sheet_id, tab, col_letter)
            except Exception:
                return []           # images are optional; the dashboard works without them
        return self.raw.get(("formulas", sheet_id, tab, col_letter), self.settings.live_ttl, load, versioned=True)

    def refresh(self) -> bool:
        """Drops cached grids so the next read goes to Google. Rate-limited by REFRESH_COOLDOWN_SECONDS."""
        if _now() - self._last_refresh < self.settings.refresh_cooldown:
            return False
        self._last_refresh = _now()
        orders_id = SHEET_REGISTRY["orders"]["id"]
        self.raw.clear_live(lambda k: k[0] == "grid" and k[1] == orders_id and not ords.is_recent_tab(k[2]))
        return True

    # -- tab choice --------------------------------------------------------------------------------------------
    def source_tabs(self, kind) -> list:
        cfg = SHEET_REGISTRY[kind]
        meta = self.tabs(cfg["id"])
        if not meta:
            raise SheetAccessError("No tabs found on the sheet.")
        if kind == "orders":
            tabs = [t for t, _ in meta if ords.is_order_tab(t)]
            if not tabs:
                raise SheetAccessError("No CREDIT / CASH / MUMBAI SALE tabs found on the order sheet.")
            return tabs
        if kind == "enquiries":
            names = {t.strip().lower(): t for t, _ in meta}
            found = [names[w.strip().lower()] for w, _label in enqs.TABS if w.strip().lower() in names]
            if not found or enqs.TABS[0][0].strip().lower() not in {f.strip().lower() for f in found}:
                raise SheetAccessError("The enquiry sheet has no 'daily enquiry update' tab.")
            return found
        if kind == "payments":
            want = cfg["tab"].strip().lower()
            names = [t for t, _ in meta]
            return [next((t for t in names if t.strip().lower() == want), names[0])]
        raise KeyError(kind)

    def _entries(self, kind) -> tuple[list, list]:
        """Fetches every grid a dataset needs (in parallel). Returns (tabs, entries)."""
        sid = SHEET_REGISTRY[kind]["id"]
        tabs = self.source_tabs(kind)
        old_ttl = max(self.settings.live_ttl, OLD_TAB_TTL)
        entries = list(self._pool.map(
            lambda t: self.grid(sid, t, False, None if ords.is_recent_tab(t) else old_ttl), tabs))
        return tabs, entries

    def _parse(self, kind, tabs, entries):
        if kind == "orders":
            return ords.parse_orders([(t, e.value) for t, e in zip(tabs, entries)])
        if kind == "enquiries":
            label = {w.strip().lower(): l for w, l in enqs.TABS}
            return enqs.parse_enquiries([(t, label[t.strip().lower()], e.value) for t, e in zip(tabs, entries)])
        if kind == "payments":
            return pays.parse_payments(entries[0].value, tab=tabs[0])
        raise KeyError(kind)

    def payments_dataset(self, window: str = DEFAULT_PO_WINDOW) -> Dataset:
        """The PO log, but only the rows of `window` (see PO_WINDOWS). Rows are in time order, so the first row of the
        window is found from column A alone; the rest of the log is never downloaded."""
        window = window if window in PO_WINDOWS else DEFAULT_PO_WINDOW
        sid = SHEET_REGISTRY["payments"]["id"]
        extra, runs, old_open = [], [], 0
        try:
            tab = self.source_tabs("payments")[0]
            dates = self.part(sid, tab, "A:A")
            head = self.part(sid, tab, f"A1:{PO_LAST_COL}1")
            col = [r[0] if r else "" for r in dates.value]
            last = max((i for i, v in enumerate(col) if str(v).strip()), default=0) + 1      # last row with a date
            when = parse_dates(pd.Series(col[1:last]))
            start = po_window_start(window)
            hit = when.index[when >= start]
            if len(hit):
                first_row = max(2, int(hit[0]) + 2 - 25)         # row number of the first order in the window,
            else:                                                 # a little earlier in case rows are not in order
                first_row = last + 1
            body = self.part(sid, tab, f"A{first_row}:{PO_LAST_COL}{last}") if first_row <= last else None
            # Open POs older than the window: read the status column alone (cheap), then fetch just those rows.
            fy_hit = when.index[when >= pays.FY_START]
            fy_first = max(2, int(fy_hit[0]) + 2) if len(fy_hit) else first_row
            if fy_first < first_row:
                status_col = pays.status_column(head.value[0] if head.value else [])
                if status_col:
                    st = self.part(sid, tab, f"{status_col}{fy_first}:{status_col}{first_row - 1}")
                    extra.append(st)
                    opens = [fy_first + i for i in range(first_row - fy_first)
                             if str(col[fy_first + i - 1] if fy_first + i - 1 < len(col) else "").strip()
                             and not pays.is_closed_status(st.value[i][0] if i < len(st.value) and st.value[i] else "")]
                    old_open = len(opens)
                    for a, b in pays.row_runs(opens):
                        e = self.part(sid, tab, f"A{a}:{PO_LAST_COL}{b}")
                        extra.append(e)
                        runs.append(e)
        except SheetAccessError as e:
            return Dataset("payments", None, None, "", error=str(e))
        except Exception as e:
            return Dataset("payments", None, None, "", error=f"{type(e).__name__}: {e}")
        entries = [dates, head] + extra + ([body] if body is not None else [])
        grid = [list(head.value[0]) if head.value else []]
        for e in runs:                                  # older open POs first, then the window (keeps sheet order)
            grid += [list(r) for r in e.value]
        grid += [list(r) for r in body.value] if body is not None else []
        version = _digest([e.version for e in entries] + [window, str(today_ist().date())])
        stale_err = next((e.error for e in entries if e.error), None)
        fetched = min(e.fetched_at for e in entries)
        key = ("payments", window)
        with self._parsed_lock:
            cached = self._parsed.get(key)
        if cached and cached[0] == version:
            data = cached[1]
        else:
            try:
                data = pays.parse_payments(grid, tab=tab)
            except SheetAccessError as e:
                return Dataset("payments", None, fetched, version, error=str(e), tabs=[tab])
            data["window"] = {"key": window, "label": PO_WINDOWS[window][0], "start": start.strftime("%d %b %Y"),
                              "rows": max(0, last - first_row + 1) if body is not None else 0, "log_rows": last - 1,
                              "older_open": old_open}
            with self._parsed_lock:
                self._parsed[key] = (version, data)
        return Dataset("payments", data, fetched, version, error=stale_err, stale=bool(stale_err), tabs=[tab])

    def dataset(self, kind) -> Dataset:
        if kind == "payments":
            return self.payments_dataset(DEFAULT_PO_WINDOW)
        try:
            tabs, entries = self._entries(kind)
        except SheetAccessError as e:
            return Dataset(kind, None, None, "", error=str(e))
        except Exception as e:
            return Dataset(kind, None, None, "", error=f"{type(e).__name__}: {e}")
        version = _digest([e.version for e in entries] + [str(today_ist().date())])
        # "Synced" time = when the live tabs (this and last month) were read. Older month tabs are re-read only
        # every 6 hours on purpose, so they must not make the dashboard look out of date.
        live = [e.fetched_at for t, e in zip(tabs, entries) if kind != "orders" or ords.is_recent_tab(t)]
        fetched = min(live) if live else max(e.fetched_at for e in entries)
        stale_err = next((e.error for e in entries if e.error), None)
        with self._parsed_lock:
            hit = self._parsed.get(kind)
        if hit and hit[0] == version:
            data = hit[1]
        else:
            try:
                data = self._parse(kind, tabs, entries)
            except SheetAccessError as e:
                return Dataset(kind, None, fetched, version, error=str(e), tabs=tabs)
            with self._parsed_lock:
                self._parsed[kind] = (version, data)
        return Dataset(kind, data, fetched, version, error=stale_err, stale=bool(stale_err), tabs=tabs)

    def keep_warm(self, every: float = 20.0):
        """Local server: read the sheets now and keep them fresh in the background, so no page waits on Google."""
        def loop():
            while True:
                try:
                    self.datasets(KINDS)
                except Exception:
                    pass
                try:
                    self.dataset("enquiries")     # optional sheet: a missing share never affects the other pages
                except Exception:
                    pass
                time.sleep(every)
        threading.Thread(target=loop, daemon=True, name="keep-warm").start()

    def datasets(self, kinds) -> dict:
        kinds = list(kinds)
        return dict(zip(kinds, self._outer.map(self.dataset, kinds)))

    def status(self) -> dict:
        """Per-source sync state for the header (does not fetch anything new beyond the normal cache)."""
        out = {}
        for kind, ds in self.datasets(KINDS).items():
            out[kind] = {"name": SHEET_REGISTRY[kind]["name"], "ok": ds.data is not None and not ds.stale,
                         "error": ds.error, "stale": ds.stale, "synced_at": _iso(ds.fetched_at),
                         "version": ds.version, "tabs": [t for t in ds.tabs if t]}
        return out


def meta(ds: Dataset) -> dict:
    return {"source": ds.kind, "synced_at": _iso(ds.fetched_at), "version": ds.version, "stale": ds.stale,
            "error": ds.error}
