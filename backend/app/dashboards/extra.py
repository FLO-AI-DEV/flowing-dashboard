"""Filters shared by every page: date period, search, due / delivery windows, supplier type, amount range.

All of them are read from the query string, the same way on every endpoint:

  period      Today, Yesterday, Last 7 days, This week, This month, Last month, Last 30 days, This quarter,
              This FY, Custom (with date_from / date_to as YYYY-MM-DD)
  q           words that must all appear in the row (PO no., design no., supplier, enquiry text, ...)
  window      due / delivery windows, e.g. "Overdue 31-60 days", "Due in next 7 days" (each page lists its own)
  supplier_type   MSME / Non-MSME (from '(MSME)' in the supplier name)
  amount      value range of the line / bill: Under ₹10K, ₹10K-1L, ₹1L-5L, ₹5L and above
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

PERIODS = ["Today", "Yesterday", "Last 7 days", "This week", "This month", "Last month", "Last 30 days",
           "This quarter", "This FY", "Custom"]
SUPPLIER_TYPES = ["MSME", "Non-MSME"]
AMOUNTS = ["Under ₹10K", "₹10K-1L", "₹1L-5L", "₹5L and above"]
AMOUNT_EDGES = [-np.inf, 10_000, 100_000, 500_000, np.inf]
OVERDUE = ["Overdue 1-30 days", "Overdue 31-60 days", "Overdue 61-90 days", "Overdue 90+ days"]
ORDER_WINDOWS = OVERDUE + ["Due in next 7 days", "Due in 8-30 days", "Due after 30 days", "No delivery date",
                           "Fully received"]
DUES_WINDOWS = OVERDUE + ["Due in next 7 days", "Due in 8-30 days", "Due after 30 days", "No due date"]
PENDING_WINDOWS = ["Pending 0-7 days", "Pending 8-30 days", "Pending 31-90 days", "Pending 90+ days", "Solved / done"]


def _day(text: str) -> pd.Timestamp | None:
    try:
        v = pd.Timestamp(str(text).strip()[:10])
        return None if pd.isna(v) else v.normalize()
    except (ValueError, TypeError):
        return None


def period_range(f: dict, today: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """(first day, last day) inclusive for the chosen period, or None for 'all dates'."""
    p = (f.get("period") or [""])[0] if isinstance(f.get("period"), list) else (f.get("period") or "")
    t = today.normalize()
    if p == "Today":
        return t, t
    if p == "Yesterday":
        return t - pd.Timedelta(days=1), t - pd.Timedelta(days=1)
    if p == "Last 7 days":
        return t - pd.Timedelta(days=6), t
    if p == "This week":                                   # Monday to today
        return t - pd.Timedelta(days=t.weekday()), t
    if p == "This month":
        return t.replace(day=1), t
    if p == "Last month":
        first = t.replace(day=1)
        last = first - pd.Timedelta(days=1)
        return last.replace(day=1), last
    if p == "Last 30 days":
        return t - pd.Timedelta(days=29), t
    if p == "This quarter":
        qm = 3 * ((t.month - 1) // 3) + 1
        return t.replace(month=qm, day=1), t
    if p == "This FY":
        y = t.year if t.month >= 4 else t.year - 1
        return pd.Timestamp(year=y, month=4, day=1), t
    if p == "Custom" or f.get("date_from") or f.get("date_to"):
        a = _day((f.get("date_from") or [""])[0] if isinstance(f.get("date_from"), list) else f.get("date_from") or "")
        b = _day((f.get("date_to") or [""])[0] if isinstance(f.get("date_to"), list) else f.get("date_to") or "")
        if a is None and b is None:
            return None
        a = a or pd.Timestamp("1900-01-01")
        b = b or t
        return (a, b) if a <= b else (b, a)
    return None


def describe_period(rng) -> str:
    if not rng:
        return ""
    a, b = rng
    return f"{a:%d %b %Y}" if a == b else f"{a:%d %b} – {b:%d %b %Y}"


def in_period(dates: pd.Series, rng) -> pd.Series:
    if not rng:
        return pd.Series(True, index=dates.index)
    d = pd.to_datetime(dates, errors="coerce").dt.normalize()
    return (d >= rng[0]) & (d <= rng[1])


def search(df: pd.DataFrame, cols: list[str], q) -> pd.Series:
    """Every word of q must appear somewhere in the given columns (case and spacing ignored)."""
    text = (q[0] if isinstance(q, list) and q else q) or ""
    words = [w for w in re.split(r"\s+", str(text).lower().strip()) if w]
    if not words or df.empty:
        return pd.Series(True, index=df.index)
    blob = pd.Series("", index=df.index)
    for c in cols:
        if c in df.columns:
            s = df[c]
            if pd.api.types.is_datetime64_any_dtype(s):
                s = s.dt.strftime("%d/%m/%Y")
            blob = blob + " " + s.fillna("").astype(str).str.lower()
    blob = blob.str.replace(r"\s+", " ", regex=True)
    mask = pd.Series(True, index=df.index)
    for w in words:
        mask &= blob.str.contains(w, regex=False)
    return mask


def is_msme(names: pd.Series) -> pd.Series:
    return names.fillna("").astype(str).str.upper().str.contains(r"\bMSME\b", regex=True)


def supplier_type(names: pd.Series, chosen: list[str]) -> pd.Series:
    if not chosen or set(chosen) >= set(SUPPLIER_TYPES):
        return pd.Series(True, index=names.index)
    m = is_msme(names)
    return m if "MSME" in chosen else ~m


def amount_band(values: pd.Series) -> pd.Series:
    return pd.cut(pd.to_numeric(values, errors="coerce").fillna(0), AMOUNT_EDGES, labels=AMOUNTS, right=False).astype(str)


def overdue_band(days: pd.Series) -> pd.Series:
    d = pd.to_numeric(days, errors="coerce").fillna(0)
    return pd.Series(np.select([d > 90, d > 60, d > 30, d > 0], OVERDUE[::-1], default=""), index=days.index)


def due_band(days_left: pd.Series) -> pd.Series:
    """days until the due date (0 = today) -> window label."""
    d = pd.to_numeric(days_left, errors="coerce")
    return pd.Series(np.select([d.isna(), d <= 7, d <= 30], ["", "Due in next 7 days", "Due in 8-30 days"],
                               default="Due after 30 days"), index=days_left.index)


def pending_band(days: pd.Series, done: pd.Series) -> pd.Series:
    d = pd.to_numeric(days, errors="coerce")
    return pd.Series(np.select([done.astype(bool), d > 90, d > 30, d > 7, d >= 0],
                               ["Solved / done", "Pending 90+ days", "Pending 31-90 days", "Pending 8-30 days",
                                "Pending 0-7 days"], default="Pending 0-7 days"), index=days.index)


def picked(f: dict, key: str) -> list[str]:
    v = f.get(key) or []
    return [v] if isinstance(v, str) else list(v)
