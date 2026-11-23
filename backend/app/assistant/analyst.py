"""Gemini analyst: answers what the rules can't — calculations, loosely worded questions, follow-ups in context.

How it stays cheap and accurate:
  * The rules (engine.py) answer first; Gemini is only called for calculations or when the rules give up.
  * It uses a small model (GEMINI_MODEL, default gemini-flash-lite-latest) with short outputs.
  * It gets a compact text snapshot of the dashboard ("facts"): headline figures and the top rows of each table,
    filtered by the names / months in the question, plus the last few turns of this chat.
  * It never does arithmetic itself: it calls the calculate tool (calc.py), and the exact result is used.

Privacy: with GEMINI_MODE=analyst (the default) the facts sent with a question contain dashboard figures. Set
GEMINI_MODE=labels to send only the question and label names (the older, stricter mode).
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass

import requests

from ..core import today_ist
from . import fmt
from .calc import CalcError, calculate
from .engine import Snapshot, Vocabulary, is_dashboard_question, is_unrelated_request, kpi_list, parse, table_list
from .memory import MAX_TURNS
from .pages import PAGES

log = logging.getLogger(__name__)

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-flash-lite-latest"
FACT_PAGES = ["orders", "dues", "vendors", "order-to-vendors"]
MAX_FACTS = 8000          # characters of facts per question (keeps each call small)
MAX_ROUNDS = 4            # model <-> calculator round trips

# Questions that need arithmetic or reasoning go straight to the analyst when it is on.
CALC = re.compile(
    r"(%|\bpercent|\bpercentage|\bratio\b|\bshare of\b|\bdifference\b|\bdiff\b|\bminus\b|\bplus\b|\badd\b|"
    r"\bsubtract|\bsum of\b|\btotal of\b|\baverage\b|\bavg\b|\bmean\b|\bper (vendor|po|line|day|month|piece|pc)\b|"
    r"\bhow much more\b|\bhow much less\b|\bkitna zyada\b|\bkitna kam\b|\bkitne guna\b|\btimes\b|\bgrowth\b|"
    r"\bincrease\b|\bdecrease\b|\bcalculate\b|\bcalc\b|\bhisab\b|\bjod\b|\bghata\b|\bbaki kitna bachega\b|"
    r"\bwhy\b|\bkyun\b|\bkyon\b|\bexplain\b|\bsummar|\binsight|\bsuggest|\badvice\b|\bshould\b)", re.I)

SYSTEM = """You are Flo-Wing Assistant inside Flo-Wing's operations dashboard (a women's ethnic wear wholesaler in Jaipur).
Answer questions about Flo-Wing dashboard data and features. Users can ask in natural English, Hindi or Hinglish,
including short phrases and typos. Use chat history to resolve references, and ground figures in FACTS.
- A follow-up can name just a date, a filter, or a formatting change. Keep the previous subject, measure, unit, and
  filters unless the user changes them. For example, after factory visits on 12 November, “yesterday” asks for the
  same lookup on the previous calendar day, and “in one word” asks for the same result in a shorter format.
- Resolve relative dates from the current date in IST supplied in FACTS. Use records or aggregates only at the
  requested date granularity. If the needed data is unavailable, say what is missing and name the relevant page.
- If the dashboard subject or date is unclear, ask one specific clarification. For unrelated requests, ask what
  the user wants to look up in the dashboard and give one relevant example.
- For dashboard arithmetic (sum, difference, %, average, ratio, per-unit) call the calculate tool with the relevant
  dashboard figures. Never compute in your head.
- Money: rupees in Indian style (₹12.34 L, ₹1.23 Cr, ₹45,600). Quantities in pcs. Bold the key figure with its unit.
- Be brief: 1-3 sentences, or a short bullet list for a breakdown. No preamble, no tables.
- Reply in the user's language and style. Use the resolved scope and measure in FACTS to select matching rows or filters.
- Report zero matches only when the available results cover the requested scope. Never invent figures or records.
- Pages include Orders (PO lines), Vendors (scorecard), Supplier dues (payables), and Order to vendors (factory visits)."""

TOOLS = [{"functionDeclarations": [{
    "name": "calculate",
    "description": "Exact arithmetic. Use plain numbers (rupees as full numbers, or with L / Cr), + - * / % ** ( ), "
                   "round(x, n), abs, min, max, sum. Example: round(2558000000/3960000000*100, 1)",
    "parameters": {"type": "OBJECT", "properties": {"expression": {"type": "STRING"}}, "required": ["expression"]},
}]}]


def wants_analysis(question: str) -> bool:
    return bool(CALC.search(question or ""))


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


def build_facts(assistant, question: str, today_month: str | None, context: dict | None = None,
                *, follow_up_only: bool = False) -> tuple[str, str | None, dict] | None:
    """Build current dashboard facts and the resolved context to carry into the next turn."""
    if is_unrelated_request(question):
        return None
    snap = Snapshot(assistant.fetch)
    vocab = Vocabulary(snap)
    q = parse(question, vocab, today_month)
    if not is_dashboard_question(q, context, vocab):
        return None
    changes_scope = bool(q.entities or q.months)
    has_measure = bool(q.metric_toks)
    assistant._inherit(q, context, vocab)
    if follow_up_only and not (changes_scope and q.inherited):
        return None

    measure = (context or {}).get("metric") if q.inherited and not has_measure else None
    measure = measure or " ".join(dict.fromkeys(t for t in q.toks if t in q.metric_toks))
    pages = list(dict.fromkeys([p for p in q.pages if p in FACT_PAGES] + FACT_PAGES))
    out = [f"The current date in IST is {today_ist():%Y-%m-%d}.",
           f"Months in the data: {', '.join(vocab.months) or 'none'}. Current month: {today_month or '-'}."]
    named = [e.display for e in q.entities if e.type != "month"]
    if named or q.months:
        out.append(f"Resolved scope: {', '.join(named + q.months)}.")
    if q.inherited and measure:
        out.append(f"Measure for this follow-up: {measure}.")
    size = sum(len(line) for line in out)
    for page in pages:
        f = assistant._filters(page, q)
        try:
            data = snap.get(page, f or {})
        except Exception as e:  # noqa: BLE001 - a sheet that can't be read is reported, not fatal
            out.append(f"## {PAGES[page].label}: not available ({e})")
            continue
        head = f"## {PAGES[page].label} page" + (f" (filtered: {json.dumps(f, ensure_ascii=False)})" if f else "")
        if f is None:
            head += " (unfiltered; this page cannot apply the requested scope)"
        lines = [head]
        for k in kpi_list(data):
            hint = f" ({k['hint']})" if k.get("hint") else ""
            lines.append(f"- {k['label']}: {_num(k.get('value'), k.get('format'), k.get('unit') or '')}{hint}")
        for name, t in table_list(data):
            if not t.get("columns") or name in ("rows",):
                continue
            limit = 8 if name in ("pos", "overdue", "bills") else 15
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
    resolved = assistant._ctx(q, None, "analysis")
    resolved.update(page=first, metric=measure or None)
    return "\n".join(out), first, resolved


@dataclass
class AnalysisAnswer:
    text: str
    calculation: list[dict]

    @property
    def result(self) -> dict | None:
        return fmt.reported_result(self.text)


class GeminiAnalyst:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, timeout: float = 25.0, session=None):
        self.api_key, self.model, self.timeout = api_key, model, timeout
        self.session = session or requests.Session()

    @classmethod
    def from_env(cls) -> "GeminiAnalyst | None":
        key = os.getenv("GEMINI_API_KEY", "").strip()
        on = os.getenv("ASSISTANT_GEMINI", "on").strip().lower() not in ("off", "0", "false", "no")
        mode = os.getenv("GEMINI_MODE", "analyst").strip().lower()
        if not key or not on or mode != "analyst":
            return None
        return cls(key, os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_MODEL)

    def _post(self, body: dict) -> dict | None:
        try:
            r = self.session.post(API.format(model=self.model), json=body, timeout=self.timeout,
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

    def answer(self, question: str, facts: str, history: list[tuple[str, str]]) -> AnalysisAnswer | None:
        contents = []
        for q, a in history[-MAX_TURNS:]:
            contents.append({"role": "user", "parts": [{"text": q}]})
            contents.append({"role": "model", "parts": [{"text": a[:600]}]})
        contents.append({"role": "user", "parts": [{"text": f"FACTS:\n{facts}\n\nQUESTION: {question}"}]})
        body = {"systemInstruction": {"parts": [{"text": SYSTEM}]}, "contents": contents, "tools": TOOLS,
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 400}}
        calculation = []
        for _ in range(MAX_ROUNDS):
            content = self._post(body)
            if not content:
                return None
            parts = content.get("parts") or []
            calls = [p["functionCall"] for p in parts if isinstance(p, dict) and "functionCall" in p]
            if not calls:
                text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
                return AnalysisAnswer(text, calculation) if text else None
            body["contents"].append({"role": "model", "parts": parts})
            replies = []
            for call in calls:
                expr = str((call.get("args") or {}).get("expression", ""))
                try:
                    result = {"result": calculate(expr)}
                    calculation.append({"expression": expr, **result})
                except CalcError as e:
                    result = {"error": str(e)}
                replies.append({"functionResponse": {"name": call.get("name", "calculate"), "response": result}})
            body["contents"].append({"role": "user", "parts": replies})
        return None
