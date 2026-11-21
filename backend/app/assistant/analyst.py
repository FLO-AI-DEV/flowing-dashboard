"""Gemini analyst: answers what the rules can't — calculations, loosely worded questions, follow-ups in context.

How it stays cheap, fast and accurate:
  * The rules (engine.py) and the glossary answer first; Gemini is only called for calculations, look-ups of
    particular rows, loosely worded questions or when the rules give up.
  * It uses a small model (GEMINI_MODEL, default gemini-flash-lite-latest) with short outputs.
  * It gets the headline figures of each page ("facts"), a description of every table and column, and tools:
      query_table   exact filters / totals / counts / top-N over every row (datatools.py)
      search_rows   find a name, PO number or words in every row of every tab
      calculate     exact arithmetic (calc.py); it never does sums in its head
  * Every figure in its answer is checked against what the tools and facts returned (grounding check). A figure
    that can't be found sends it back once to look it up; if it still can't, the answer says so.
  * One question has a time limit (ANALYST_DEADLINE, default 20 s); past that the rules' answer is used.

Privacy: with GEMINI_MODE=analyst (the default) the facts sent with a question contain dashboard figures. Set
GEMINI_MODE=labels to send only the question and label names (the older, stricter mode).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

import requests

from . import fmt
from .calc import CalcError, calculate
from .datatools import TABLES, DataTools, ToolError
from .glossary import glossary_text
from .engine import Snapshot, Vocabulary, kpi_list, parse, table_list
from .pages import PAGES

log = logging.getLogger(__name__)

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-flash-lite-latest"
FACT_PAGES = ["orders", "dues", "vendors", "order-to-vendors", "enquiries"]
MAX_FACTS = 4000          # characters of page figures per question (details come from the tools)
MAX_ROUNDS = 6            # model <-> tool round trips
DEADLINE = float(os.getenv("ANALYST_DEADLINE", "20"))   # seconds for one question, all rounds included

# Questions that need arithmetic or reasoning go straight to the analyst when it is on.
CALC = re.compile(
    r"(%|\bpercent|\bpercentage|\bratio\b|\bshare of\b|\bdifference\b|\bdiff\b|\bminus\b|\bplus\b|\badd\b|"
    r"\bsubtract|\bsum of\b|\btotal of\b|\baverage\b|\bavg\b|\bmean\b|\bper (vendor|po|line|day|month|piece|pc)\b|"
    r"\bhow much more\b|\bhow much less\b|\bkitna zyada\b|\bkitna kam\b|\bkitne guna\b|\btimes\b|\bgrowth\b|"
    r"\bincrease\b|\bdecrease\b|\bcalculate\b|\bcalc\b|\bhisab\b|\bjod\b|\bghata\b|\bbaki kitna bachega\b|"
    r"\bwhy\b|\bkyun\b|\bkyon\b|\bexplain\b|\bsummar|\binsight|\bsuggest|\badvice\b|\bshould\b)", re.I)

SYSTEM = """You are Flo-Wing Assistant inside Flo-Wing's operations dashboard (a women's ethnic wear wholesaler in Jaipur).
Answer ONLY from FACTS, tool results (read live from the company's Google Sheets) and this chat. Never invent figures.
- FACTS has each page's headline figures. For anything more specific (a supplier, PO, design, enquiry, bill, city,
  date range, person, top-N, count of rows) call query_table or search_rows first. Use the TABLES list for exact
  table and column names. Names in the sheets are spelt many ways: filter with 'contains' on a short part of the name
  ("vendor contains kesar"). If a tool returns notes or close values, call it again with the right value.
- Don't know which table? search_rows with the name or words. Nothing in the tables? search_rows with scope "all".
- For ANY arithmetic (sum, difference, %, average, ratio, per-unit) call the calculate tool. Never compute in your head.
- Every number you write must come from FACTS, a tool result or calculate.
- Money: rupees in Indian style (₹12.34 L, ₹1.23 Cr, ₹45,600). Quantities in pcs. Bold the key figure.
- Be brief: 1-3 sentences, or a short bullet list for a breakdown. No preamble, no tables.
- Users write in English, Hindi or Hinglish, often with typos or no punctuation: work out what they mean and reply in the same style.
- If a question is ambiguous, state your assumption in a few words (or ask one short question if it truly can't be answered).
- If the data doesn't contain what is asked, say so in one line and name the page that would show it.
- Meaning of a word: use GLOSSARY.
- Pages: Orders (PO lines: ordered/received/pending/overdue), Vendors (scorecard), Supplier dues (payables), Order to vendors,
  Supplier enquiries (enquiry log with status solved/unsolved/in process and who handles it, pending POs by city,
  payment-terms approval, inactive suppliers)."""

TOOLS = [{"functionDeclarations": [
    {"name": "calculate",
     "description": "Exact arithmetic. Use plain numbers (rupees as full numbers, or with L / Cr), + - * / % ** ( ), "
                    "round(x, n), abs, min, max, sum. Example: round(2558000000/3960000000*100, 1)",
     "parameters": {"type": "OBJECT", "properties": {"expression": {"type": "STRING"}}, "required": ["expression"]}},
    {"name": "query_table",
     "description": "Exact rows, totals and counts from one table (every row of the sheet, live). "
                    "filters: e.g. ['vendor contains kesar', 'delivery_status = Overdue (Pending)', 'pending_amt > 0', "
                    "'month = July-26', 'po_date >= 2026-07-01', 'status in Unsolved,In process']. "
                    "metrics: e.g. ['sum pending_amt', 'count', 'avg overdue_days', 'max days_pending', 'nunique po']. "
                    "group_by: a column to break totals down by (sorted by the first metric). "
                    "No metrics and no group_by = the matching rows themselves (use columns, sort_by, limit).",
     "parameters": {"type": "OBJECT", "properties": {
         "table": {"type": "STRING", "enum": list(TABLES)},
         "filters": {"type": "ARRAY", "items": {"type": "STRING"}},
         "group_by": {"type": "STRING"},
         "metrics": {"type": "ARRAY", "items": {"type": "STRING"}},
         "sort_by": {"type": "STRING"},
         "descending": {"type": "BOOLEAN"},
         "limit": {"type": "INTEGER"},
         "columns": {"type": "ARRAY", "items": {"type": "STRING"}}},
         "required": ["table"]}},
    {"name": "search_rows",
     "description": "Find a name, PO number, design no., phone or words in every row of every table. "
                    "scope 'all' also reads every other tab of the four sheets.",
     "parameters": {"type": "OBJECT", "properties": {
         "text": {"type": "STRING"}, "scope": {"type": "STRING", "enum": ["data", "all"]}},
         "required": ["text"]}},
]}]


# Questions about particular rows / people / dates: the tools answer these exactly.
DETAIL = re.compile(
    r"\b(details?|kab|when|which date|date of|who|kaun|kiske|kisne|phone|contact|mobile|notes?|remarks?|"
    r"what happened|kya hua|update on|latest on|list (all|of)|sab dikhao|saare|all the|which (po|pos|design|bill|bills)|"
    r"bill no|design no|po no|fwpo|enquir\w* (of|for|about)|issue (of|with)|problem|complain\w*|"
    r"compare|vs|versus|between|trend|last \d+|this week|is week|top \d+|bottom \d+|topics?|oldest|newest|latest|"
    r"longest|recent|which enquir\w*|kaunsi|kaunse|konsi|konse)\b", re.I)


def wants_analysis(question: str) -> bool:
    return bool(CALC.search(question or "") or DETAIL.search(question or ""))


def _num(v, format_: str | None, unit: str = "") -> str:
    """Exact figures for the model (full rupees, so its calculations aren't thrown off by rounding)."""
    if isinstance(v, (int, float)) and format_ in ("inr", "inr_full"):
        return fmt.inr(v)
    return fmt.value(v, format_, unit)


def _cell(v, col) -> str:
    if v is None or v == "":
        return "-"
    label, unit = fmt.unit_of(col.get("label", ""))
    return _num(v, col.get("format"), unit) if isinstance(v, (int, float)) else str(v)


def build_facts(assistant, question: str, today_month: str | None) -> tuple[str, str | None]:
    """Compact text snapshot of the dashboard for one question. Returns (facts, most relevant page)."""
    snap = Snapshot(assistant.fetch)
    vocab = Vocabulary(snap)
    q = parse(question, vocab, today_month)
    pages = list(dict.fromkeys([p for p in q.pages if p in FACT_PAGES] + FACT_PAGES))
    out = [f"Months in the data: {', '.join(vocab.months) or 'none'}. Current month: {today_month or '-'}."]
    named = [e.display for e in q.entities if e.type != "month"]
    if named or q.months:
        out.append(f"Question mentions: {', '.join(named + q.months)}.")
    size = len(out[0])
    for page in pages:
        f = assistant._filters(page, q) or {}
        try:
            data = snap.get(page, f)
        except Exception as e:  # noqa: BLE001 - a sheet that can't be read is reported, not fatal
            out.append(f"## {PAGES[page].label}: not available ({e})")
            continue
        head = f"## {PAGES[page].label} page" + (f" (filtered: {json.dumps(f, ensure_ascii=False)})" if f else "")
        lines = [head]
        for k in kpi_list(data):
            hint = f" ({k['hint']})" if k.get("hint") else ""
            lines.append(f"- {k['label']}: {_num(k.get('value'), k.get('format'), k.get('unit') or '')}{hint}")
        for name, t in table_list(data):
            if not t.get("columns") or name in ("rows",):
                continue
            limit = 5 if name in ("pos", "overdue", "bills", "open", "all", "list", "terms") else 8
            cols = t["columns"]
            lines.append(f"Table {name}: " + " | ".join(c["label"] for c in cols))
            body = [r for r, m in zip(t["rows"], t["meta"]) if not m.get("kind")][:limit]
            total = [r for r, m in zip(t["rows"], t["meta"]) if m.get("kind") == "total"]
            for r in body + total:
                lines.append("  " + " | ".join(_cell(v, c) for v, c in zip(r, cols)))
            if len(t["rows"]) > limit + len(total):
                lines.append(f"  ... {len(t['rows']) - limit - len(total)} more rows (sorted as shown)")
        block = "\n".join(lines)
        if size + len(block) > MAX_FACTS:
            block = block[: max(0, MAX_FACTS - size)] + "\n  ... (cut to save tokens)"
        out.append(block)
        size += len(block)
        if size >= MAX_FACTS:
            break
    first = next(iter(q.pages), None)
    return "\n".join(out), first


NUM = re.compile(r"(₹\s?)?(?<![\w.])(-?\d[\d,]*(?:\.\d+)?)\s*(cr\b|crore|l\b|lakh|lac\b|k\b|%)?", re.I)
SCALE = {"cr": 1e7, "crore": 1e7, "l": 1e5, "lakh": 1e5, "lac": 1e5, "k": 1e3}


def _numbers(text: str, answer: bool = False) -> list[tuple[float, float, str]]:
    """(value, rounding tolerance, as written). Dates, codes and small counts are skipped in answers."""
    t = str(text)
    t = re.sub(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", " ", t)                     # 21/07/2026
    t = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", t)                                 # 2026-07-21
    t = re.sub(r"\b[A-Za-z]+[-/]?\d[\w/.-]*|\b\d+[A-Za-z][\w/.-]*", " ", t)       # FWPO-00166/2627, FW132-691783
    t = re.sub(r"\b\d{1,2}(st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*", " ", t, flags=re.I)
    t = re.sub(r"\b(19|20)\d{2}\b(?!\s*(%|cr|l\b|lakh|pcs))", " ", t)              # years
    out = []
    for m in NUM.finditer(t):
        raw = m.group(2).replace(",", "")
        try:
            v = float(raw)
        except ValueError:
            continue
        unit = (m.group(3) or "").lower().strip()
        scale = SCALE.get(unit, 1)
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        tol = 0.5 * 10 ** -decimals * scale + 1e-9
        val = v * scale
        if answer and not m.group(1) and not unit and abs(val) <= 12:
            continue                                   # "top 5", "3 suppliers": too small to check reliably
        out.append((val, tol, m.group(0).strip()))
    return out


def ungrounded(answer: str, sources: list[str]) -> list[str]:
    """Figures in the answer that appear nowhere in the facts / tool results (allowing for display rounding)."""
    pool = []
    for src in sources:
        pool.extend(v for v, _, _ in _numbers(src))
    missing = []
    for v, tol, raw in _numbers(answer, answer=True):
        if not any(abs(abs(v) - abs(p)) <= tol for p in pool):
            missing.append(raw)
    return missing


class GeminiAnalyst:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, timeout: float = 12.0, session=None,
                 tools: DataTools | None = None, deadline: float = DEADLINE):
        self.api_key, self.model, self.timeout = api_key, model, timeout
        self.session = session or requests.Session()
        self.tools = tools
        self.deadline = deadline

    @classmethod
    def from_env(cls, tools: DataTools | None = None) -> "GeminiAnalyst | None":
        key = os.getenv("GEMINI_API_KEY", "").strip()
        on = os.getenv("ASSISTANT_GEMINI", "on").strip().lower() not in ("off", "0", "false", "no")
        mode = os.getenv("GEMINI_MODE", "analyst").strip().lower()
        if not key or not on or mode != "analyst":
            return None
        return cls(key, os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_MODEL, tools=tools)

    def _post(self, body: dict, timeout: float) -> dict | None:
        try:
            r = self.session.post(API.format(model=self.model), json=body, timeout=timeout,
                                  headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"})
        except Exception as e:  # noqa: BLE001
            log.warning("Gemini call failed: %s", type(e).__name__)
            return None
        if r.status_code != 200:
            log.warning("Gemini returned %s", r.status_code)
            return None
        try:
            return r.json()["candidates"][0]["content"]
        except Exception:  # noqa: BLE001
            return None

    def _run_tool(self, call: dict) -> dict:
        name, args = call.get("name", ""), call.get("args") or {}
        try:
            if name == "calculate":
                return {"result": calculate(str(args.get("expression", "")))}
            if self.tools is None:
                return {"error": "data tools are not available"}
            if name == "query_table":
                return self.tools.query(args.get("table", ""), args.get("filters"), args.get("group_by"),
                                        args.get("metrics"), args.get("sort_by"), args.get("descending", True),
                                        args.get("limit", 20), args.get("columns"))
            if name == "search_rows":
                return self.tools.search(str(args.get("text", "")), str(args.get("scope", "data")))
            return {"error": f"unknown tool {name}"}
        except (CalcError, ToolError) as e:
            return {"error": str(e)}
        except Exception as e:  # noqa: BLE001 - a broken look-up is reported to the model, never crashes the chat
            log.warning("tool %s failed: %s", name, e)
            return {"error": f"{name} failed: {type(e).__name__}"}

    def instructions(self) -> str:
        parts = [SYSTEM]
        if self.tools is not None:
            try:
                parts.append("TABLES (for query_table / search_rows):\n" + self.tools.catalog())
            except Exception:  # noqa: BLE001
                pass
        parts.append("GLOSSARY:\n" + glossary_text())
        return "\n\n".join(parts)

    def answer(self, question: str, facts: str, history: list[tuple[str, str]]) -> str | None:
        started = time.monotonic()
        contents = []
        for q, a in history[-4:]:
            contents.append({"role": "user", "parts": [{"text": q}]})
            contents.append({"role": "model", "parts": [{"text": a[:600]}]})
        contents.append({"role": "user", "parts": [{"text": f"FACTS:\n{facts}\n\nQUESTION: {question}"}]})
        body = {"systemInstruction": {"parts": [{"text": self.instructions()}]}, "contents": contents, "tools": TOOLS,
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 400}}
        sources = [facts, question] + [a for _, a in history[-4:]]
        checked = False
        for _ in range(MAX_ROUNDS + 1):
            left = self.deadline - (time.monotonic() - started)
            if left < 2:
                log.warning("analyst ran out of time")
                return None
            content = self._post(body, min(self.timeout, left))
            if not content:
                return None
            parts = content.get("parts") or []
            calls = [p["functionCall"] for p in parts if isinstance(p, dict) and "functionCall" in p]
            if not calls:
                text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
                if not text:
                    return None
                missing = ungrounded(text, sources)
                if missing and not checked:
                    checked = True                  # one more try, telling it which figures weren't found
                    body["contents"].append({"role": "model", "parts": [{"text": text}]})
                    body["contents"].append({"role": "user", "parts": [{"text":
                        "CHECK: these figures are not in the facts or tool results: " + ", ".join(missing[:6]) +
                        ". Look them up with the tools (or calculate) and answer again with exact figures only."}]})
                    continue
                if missing:
                    log.warning("answer has unverified figures: %s", missing[:6])
                    text += "\n\n_Some figures here couldn't be checked against the sheet; please confirm on the page._"
                return text
            body["contents"].append({"role": "model", "parts": parts})
            replies = []
            for call in calls[:4]:
                result = self._run_tool(call)
                dumped = json.dumps(result, ensure_ascii=False, default=str)
                if len(dumped) > 6000:                     # keep each round small and fast
                    result = {"truncated": True, "partial": dumped[:6000]}
                    dumped = result["partial"]
                sources.append(dumped)
                replies.append({"functionResponse": {"name": call.get("name", ""), "response": result}})
            body["contents"].append({"role": "user", "parts": replies})
        return None
