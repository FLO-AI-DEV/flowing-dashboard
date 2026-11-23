"""Rule-based question answering over the dashboard.

How a question is answered:
  1. Read the dashboard (every page, unfiltered) to learn its vocabulary: designer, client, vendor, fabricator and
     category names, months, PO numbers, and every KPI and table-column label.
  2. Pull months, names and the answer style ("in one word", "in detail") out of the question; the rest is matched
     against the labels.
  3. Build candidate answers (a KPI with the question's filters applied, a table cell for a named row, a ranking,
     a month-by-month list, a comparison), score them, and phrase the best one.

Nothing here writes anywhere, and all numbers come from the fetch callback, i.e. the dashboard's own endpoints.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Callable

from ..core import today_ist
from . import fmt
from .pages import (DIMENSION_PLURALS, DIMENSION_WORDS, FEATURES, HELP, HOME_PAGE, OPTION_TYPES, PAGES, PLURALS,
                    QUALITY, ROW_TYPES, TYPE_NAMES)
from .text import (BOTTOM, CONTEXT_WORDS, GENERIC_NAME_WORDS, HOWMANY, MARKERS, MONTH_ALIASES, STOP, TOP, TREND, WORDS,
                   is_day_expression, label_tokens, name_key, norm, parse_day, raw_tokens, similar, tokens)

Fetch = Callable[[str, dict], dict]

THRESHOLD = 1.0           # below this, the rules are not sure what was asked
SOFT = {"new", "yearly", "annual", "fy", "all", "sheet", "overall", "qty", "mtr", "day"}
SKIP_KEYS = {"meta", "options", "charts", "matrix", "heatmap", "lines", "top_repeat", "gauge", "schedule"}
SPECIAL_ROW = re.compile(r"^\(.*\)$|^(total|grand total)$", re.I)
MAX_QUESTION = 500


class DataUnavailable(Exception):
    pass


def _hint(h) -> str:
    h = str(h or "").strip()
    return "" if not h or re.match(r"^(sheet )?col(umn)?s? [A-Z]", h, re.I) else (h if h.endswith(".") else h + ".")


# ------------------------------------------------------------------------------------------------ data access
class Snapshot:
    """The dashboard as the assistant sees it during one question. Each page/filter combination is read once."""

    def __init__(self, fetch: Fetch):
        self._fetch = fetch
        self._cache: dict = {}

    def get(self, page: str, filters: dict | None = None) -> dict:
        filters = {k: list(v) for k, v in (filters or {}).items() if v}
        key = (page, tuple(sorted((k, tuple(v)) for k, v in filters.items())))
        if key not in self._cache:
            try:
                self._cache[key] = self._fetch(page, filters)
            except Exception as e:                       # HTTPException(503) when a sheet can't be read
                self._cache[key] = DataUnavailable(getattr(e, "detail", None) or str(e) or "unavailable")
        val = self._cache[key]
        if isinstance(val, DataUnavailable):
            raise val
        return val


def kpi_list(payload: dict) -> list[dict]:
    out = []

    def walk(o, group):
        if isinstance(o, dict):
            if isinstance(o.get("kpis"), list):
                out.extend({**k, "_group": group} for k in o["kpis"] if isinstance(k, dict) and k.get("label"))
            for k, v in o.items():
                if k not in SKIP_KEYS and k != "kpis" and not (isinstance(v, dict) and "rows" in v):
                    walk(v, k)
    walk(payload, "")
    return out


def table_list(payload: dict) -> list[tuple[str, dict]]:
    out = []

    def walk(o, name):
        if isinstance(o, dict):
            if isinstance(o.get("columns"), list) and isinstance(o.get("rows"), list):
                out.append((name, o))
                return
            for k, v in o.items():
                if k not in SKIP_KEYS:
                    walk(v, k)
    walk(payload, "")
    return out


def row_type(table: dict) -> str | None:
    cols = table.get("columns") or []
    return ROW_TYPES.get(norm(cols[0]["label"])) if cols else None


# ------------------------------------------------------------------------------------------------ vocabulary
@dataclass
class Entity:
    type: str
    display: str
    key: str
    raw: dict = field(default_factory=dict)       # page -> the exact option value on that page

    def ref(self):
        return {"type": self.type, "value": self.display}


class Vocabulary:
    def __init__(self, snap: Snapshot):
        self.entities: dict[tuple[str, str], Entity] = {}
        self.months: list[str] = []
        self.labels: set[str] = set()
        self.errors: dict[str, str] = {}
        for page in PAGES:
            try:
                data = snap.get(page)
            except DataUnavailable as e:
                self.errors[page] = str(e)
                continue
            for param, values in (data.get("options") or {}).items():
                etype = OPTION_TYPES.get(param)
                if not etype:
                    continue
                for v in values:
                    if etype == "month":
                        if v not in self.months and re.match(r"^[A-Za-z]+-\d{2}$", v):
                            self.months.append(v)
                        continue
                    self._add(etype, v, page)
            for name, t in table_list(data):
                if row_type(t) == "po":
                    for r in t["rows"]:
                        if r and r[0]:
                            self._add("po", str(r[0]), page)
            for k in kpi_list(data):
                self.labels.add(k["label"])
            for _, t in table_list(data):
                for c in t["columns"][1:]:
                    self.labels.add(c["label"])
        self.by_key: dict[str, list[Entity]] = {}
        self.by_first: dict[str, list[Entity]] = {}
        for e in self.entities.values():
            self.by_key.setdefault(e.key, []).append(e)
            first = e.key.split(" ")[0]
            if e.type != "po" and len(first) >= 4 and first not in GENERIC_NAME_WORDS:
                self.by_first.setdefault(first, []).append(e)
        self.common = set(STOP) | set(WORDS) | set(MONTH_ALIASES) | {
            w for lab in self.labels for w in raw_tokens(lab)} | {"page", "dashboard", "tab", "detail", "word"} | \
            set(DIMENSION_WORDS) | set(DIMENSION_PLURALS)

    def _add(self, etype, value, page):
        key = name_key(value)
        if not key:
            return
        e = self.entities.setdefault((etype, key), Entity(etype, value, key))
        e.raw.setdefault(page, value)
        if value.isupper() and not e.display.isupper():
            e.display = value

    def of_type(self, etype: str) -> list[Entity]:
        return [e for e in self.entities.values() if e.type == etype and not SPECIAL_ROW.match(e.display)]


# ------------------------------------------------------------------------------------------------ question
@dataclass
class Query:
    text: str
    toks: list[str] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    months: list[str] = field(default_factory=list)
    dims: list[str] = field(default_factory=list)
    n: int = 1
    style: str = "normal"                      # terse | normal | detail
    pages: list[str] = field(default_factory=list)   # pages named in the question
    intent: str = "value"
    inherited: bool = False

    @property
    def markers(self):
        return {t for t in self.toks if t in MARKERS}

    @property
    def metric_toks(self):
        return {t for t in self.toks if t not in MARKERS and (t not in DIMENSION_WORDS or t == "po")}

    def scope(self, skip_type: str | None = None) -> str:
        parts = []
        names = [e.display for e in self.entities if e.type not in ("month", skip_type)]
        if names:
            parts.append("for " + " and ".join(names))
        parts.append(f"in {fmt.months(self.months)}" if self.months else "")
        return " ".join(p for p in parts if p)


_TERSE = re.compile(r"\b(one word|1 word|single word|only (the )?(number|value|figure)|just (the )?(number|value|"
                    r"figure)|number only|sirf (number|ek word|value)|bas number|ek word|in short|short me|"
                    r"no explanation)\b")
_DETAIL = re.compile(r"\b(in detail|detailed|details|detail me|breakdown|break down|break-up|breakup|full|vistar|"
                     r"vistaar|elaborate|explain in detail|with details)\b")
_EXPLAIN = re.compile(r"\b(what is meant|what does .* mean|meaning of|what is the meaning|matlab|kya hota|define|"
                      r"definition|means what|how is .* calculated|how .* calculated)\b")
_WHERE = re.compile(r"\b(where|kahan|kaha|kidhar|which page|kis page|kaunse page|konse page)\b")
_LIST = re.compile(r"\b(list|names|name all|kaun kaun|kon kon|which are the|show all|all the)\b")
_COMPARE = re.compile(r"\b(vs|versus|compare|comparison|compared|difference|mukabla|between)\b")
_LOWER_RANK_WORDS = label_tokens("less lower fewer kam")
_LOWER_COMPARISON = re.compile(r"\b(?:(?:less|lower|fewer) than|how much less|kitna kam|se kam)\b")
_GREET = re.compile(r"^\s*(hi+|hello|hey|namaste|namaskar|hola|good (morning|afternoon|evening)|yo)\b[\s!.?]*$")
_THANKS = re.compile(r"^(?:(?:thanks|thank you)(?: a lot| so much| very much)?|thx|ty|dhanyavad|shukriya|"
                     r"great|nice|ok|okay|cool)[\s!.?]*$")
_HELP = re.compile(r"\b(what can you do|help(?: me)?|how (do|can) i use you|who are you|what do you do|kya kar sakte)\b")
_HOWTO = re.compile(r"\b(how (do|does|can|to|is)|kaise|where is the|can i|is there)\b")
_FOLLOW = re.compile(r"^\s*(and|what about|how about|aur|or|same for|also|uska|unka|iska|for)\b")
_PRONOUN = re.compile(r"\b(her|his|their|its|she|he|they|uska|uski|uske|unka|unki|unke|iska|inka|same)\b")
_PO_NO = re.compile(r"\b(?:fpo\s*/?\s*)?(\d{3,6})\b")
_PLURAL_DIMS = "|".join(DIMENSION_PLURALS)
_EACH = re.compile(rf"\b(?:of|for|by|across|among) (?:all |each |every |the |all the )?(?:{_PLURAL_DIMS})\b|"
                   rf"\b(?:each|every|har|sabhi|sab|all) (?:{_PLURAL_DIMS}|{'|'.join(DIMENSION_WORDS)})\b")
_QUALITY = re.compile(r"\b(best|worst|reliable|unreliable)\b")
_UNRELATED = re.compile(
    r"```|\b(?:ignore|forget|disregard|override) (?:\w+ ){0,3}(?:instructions|rules)\b|"
    r"\b(?:python|javascript|typescript|sql) (?:code|script|program|function|query)\b|"
    r"\b(?:code|script|program|function|query) in (?:python|javascript|typescript|sql|java)\b|"
    r"\b(?:write|generate|create|implement|debug|provide|give) (?:\w+ ){0,4}"
    r"(?:code|script|program|function|algorithm|poem|joke)\b|"
    r"\b(?:weather|joke|capital of|order of operations)\b")
_DASHBOARD_TERMS = label_tokens(
    "pending received ordered overdue payable payment vendor agency delivery on-time delay "
    "purchase orders outstanding ageing bills dashboard")
_DASHBOARD_PHRASES = re.compile(r"\b(?:credit days|supplier terms|days overdue)\b")
_FEATURE_TERMS = {word for triggers, _ in FEATURES for word in triggers}
_FOLLOW_UP_TERMS = label_tokens("inr qty rate difference ratio average")
_GENERIC_LABEL_TERMS = label_tokens("amount date day description detail name number remark row status time type")
_FACTORY_VISIT = re.compile(r"\b(?:factory[- ]visit(?:s|ed)?|visited (?:the |a |their )?factor(?:y|ies)|"
                            r"factor(?:y|ies) (?:was |were )visited)\b")
_DATE_FOLLOW_PREFIX = re.compile(r"^(?:(?:and|aur|और|also) )?(?:(?:what about|how about|same(?: list)? for) )?"
                                 r"(?:(?:for|on|date) )?")
_DATE_FOLLOW_SUFFIX = re.compile(r" (?:ke liye|ka|ki|ko|के लिए)$")
_REPEAT = re.compile(r"(?:same(?: again)?|again|(?:repeat|say|show) (?:it|that)(?: again)?)(?: please)?[?.!]*")
_EXPLAIN_PREVIOUS = re.compile(
    r"(?:explain|elaborate on|break down) (?:it|this|that|(?:this |that |the |your )?(?:previous )?(?:answer|result))|"
    r"what does (?:it|this|that) mean|how (?:did you (?:get|calculate)|was) (?:it|this|that)(?: calculated)?|"
    r"(?:iska|uska|yeh) (?:matlab|kaise)|(?:ise|isko) samjhao"
)
_SCOPE_REPLY = ("What would you like to look up in the Flo-Wing dashboard? "
                "You can ask in your own words, like “Who visited the factory yesterday?” or “How much is still pending?”")


def _month_index(word: str) -> int | None:
    return MONTH_ALIASES.get(word)


def parse(question: str, vocab: Vocabulary, today_month: str | None) -> Query:
    q = Query(text=question)
    t = norm(question)
    if _TERSE.search(t):
        q.style = "terse"
    elif _DETAIL.search(t):
        q.style = "detail"
    t = _TERSE.sub(" ", t)
    t = _DETAIL.sub(" ", t)
    # "target kitna bacha / baki hai" asks for the remaining target, not pending pcs
    if re.search(r"\btarget\b", t):
        t = re.sub(r"\b(bacha|bachi|bache|baki|baaki|left)\b", "remaining", t)

    words = raw_tokens(t)
    used = [False] * len(words)

    # months ------------------------------------------------------------------
    fy = vocab.months
    by_no = {}
    for m in fy:
        no = _month_index(m.split("-")[0].lower())
        if no:
            by_no.setdefault(no, m)
    if today_month and today_month in fy:
        i = fy.index(today_month)
        rel = {("this", "month"): today_month, ("current", "month"): today_month, ("is", "mahine"): today_month,
               ("last", "month"): fy[i - 1] if i else None, ("previous", "month"): fy[i - 1] if i else None,
               ("pichhle", "mahine"): fy[i - 1] if i else None, ("pichle", "mahine"): fy[i - 1] if i else None,
               ("pichla", "mahina"): fy[i - 1] if i else None}
        for j in range(len(words) - 1):
            m = rel.get((words[j], words[j + 1]))
            if m:
                q.months.append(m)
                used[j] = used[j + 1] = True
    found = []
    for j, w in enumerate(words):
        if used[j]:
            continue
        base = w.split("-")[0]
        no = _month_index(base)
        if not no or no not in by_no:
            continue
        if base == "may" and j + 1 < len(words) and words[j + 1] in {"i", "you", "we", "be", "have"}:
            continue
        if base in {"mar", "jan", "dec"} and j > 0 and words[j - 1] in {"to", "will"}:
            pass
        found.append((j, by_no[no]))
        used[j] = True
        if j + 1 < len(words) and re.fullmatch(r"(20)?\d{2}", words[j + 1]):
            used[j + 1] = True
    # "april to june" / "april se june tak"
    if len(found) == 2 and any(words[k] in {"to", "se", "till", "until", "-", "through"}
                               for k in range(found[0][0] + 1, found[1][0])):
        a, b = fy.index(found[0][1]), fy.index(found[1][1])
        q.months.extend(fy[min(a, b): max(a, b) + 1])
    else:
        q.months.extend(m for _, m in found)
    q.months = list(dict.fromkeys(q.months))

    # PO numbers ---------------------------------------------------------------
    po_keys = {e.key: e for e in vocab.entities.values() if e.type == "po"}
    if po_keys:
        for j, w in enumerate(words):
            if used[j]:
                continue
            if w in po_keys:
                q.entities.append(po_keys[w])
                used[j] = True
                continue
            # Flo-Wing PO numbers: "FWPO-00098/2627", "fwpo 98", "po 98"
            fw = re.fullmatch(r"(?:fw)?po-?0*(\d{1,6})(?:/\d+)?", w) or (
                re.fullmatch(r"0*(\d{1,6})(?:/\d+)?", w) if j > 0 and words[j - 1] in {"po", "fwpo", "pos"} else None)
            if fw:
                hits = [e for k, e in po_keys.items() if re.search(rf"(?:^|\s|-)0*{int(fw.group(1))}(?:/|$)", k)]
                if len(hits) == 1:
                    q.entities.append(hits[0])
                    used[j] = True
                    continue
            m = _PO_NO.fullmatch(w)
            if m and (j > 0 and words[j - 1] in {"po", "fpo", "pos"} or w.startswith("fpo")):
                hits = [e for k, e in po_keys.items() if re.search(rf"\D{m.group(1)}$", k)]
                if len(hits) == 1:
                    q.entities.append(hits[0])
                    used[j] = True

    # names: longest exact n-gram first, then distinctive first words, then fuzzy ---------
    maxn = max((len(k.split(" ")) for k in vocab.by_key), default=1)
    for n in range(min(maxn, 5), 0, -1):
        for j in range(0, len(words) - n + 1):
            if any(used[j:j + n]):
                continue
            key = name_key(" ".join(words[j:j + n]))
            ents = [e for e in vocab.by_key.get(key, []) if e.type != "po"]
            if key == "top":             # the category "TOP" collides with "top" (= highest); only "tops" names it
                ents = []
            if key == "tops":
                ents = vocab.by_key.get("top", [])
            if ents:
                q.entities.extend(ents[:1] if len({e.type for e in ents}) == 1 else ents)
                for k in range(j, j + n):
                    used[k] = True
    for j, w in enumerate(words):
        if used[j] or w in vocab.common or len(w) < 4:
            continue
        ents = vocab.by_first.get(w)
        if ents and len({(e.type, e.key) for e in ents}) == 1:
            q.entities.append(ents[0])
            used[j] = True
            continue
        best, score = None, 0.0
        for key, ents in vocab.by_key.items():
            if " " in key or ents[0].type == "po" or abs(len(key) - len(w)) > 2 or key[0] != w[0]:
                continue
            s = similar(w, key)
            if s > score:
                best, score = ents[0], s
        if best and score >= 0.84:
            q.entities.append(best)
            used[j] = True
    seen = set()
    q.entities = [e for e in q.entities if not ((e.type, e.key) in seen or seen.add((e.type, e.key)))]

    rest = " ".join(w for j, w in enumerate(words) if not used[j])
    q.toks = [token for token in tokens(rest) if token != "also" and not _PRONOUN.fullmatch(token)]
    q.dims = list(dict.fromkeys(DIMENSION_WORDS[x] for x in q.toks if x in DIMENSION_WORDS))
    lower_words = q.metric_toks & _LOWER_RANK_WORDS
    if q.dims and lower_words and q.metric_toks - lower_words and not (_COMPARE.search(t) or _LOWER_COMPARISON.search(t)):
        q.toks = [token for token in q.toks if token not in lower_words] + [BOTTOM]
    m = re.search(r"\b(?:top|bottom|best|worst|highest|lowest)\s*(\d{1,2}|three|five|ten)\b", t) or \
        re.search(r"\b(\d{1,2})\s*(?:top|best|highest|lowest|worst)\b", t)
    if m:
        q.n = {"three": 3, "five": 5, "ten": 10}.get(m.group(1)) or int(m.group(1))
        q.n = max(1, min(q.n, 20))
        q.toks = [x for x in q.toks if x != m.group(1)]

    for page in PAGES.values():
        if any(re.search(rf"\b{re.escape(w)}\b", t) for w in page.words):
            q.pages.append(page.key)
    # Flo-Wing: money owed to suppliers lives on the dues page; PO lines on the orders page
    if re.search(r"\b(dues?|payables?|payments?|pay|bills?|net payable|dena|dene|bhugtan|ageing|aging|agency)\b", t) \
            and "dues" not in q.pages:
        q.pages.append("dues")
    if re.search(r"\b(po|pos|purchase orders?|delivery|deliveries|order qty|lines?)\b", t) and "orders" not in q.pages:
        q.pages.append("orders")
    if re.search(r"\b(on[- ]?time|scorecard|reliable|delay|late)\b", t) and "vendors" not in q.pages:
        q.pages.append("vendors")

    # intent --------------------------------------------------------------------
    same_type = {}
    for e in q.entities:
        same_type.setdefault(e.type, []).append(e)
    if any(e.type == "po" for e in q.entities):
        q.intent = "record"
    elif _COMPARE.search(t) and (any(len(v) >= 2 for v in same_type.values()) or len(q.months) >= 2):
        q.intent = "compare"
    elif any(len(v) >= 2 for v in same_type.values() if v[0].type != "month"):
        q.intent = "compare"
    elif _EXPLAIN.search(t):
        q.intent = "explain"
    elif _WHERE.search(t) and q.metric_toks:
        q.intent = "where"
    elif TREND in q.toks:
        q.intent = "trend"
    elif re.search(r"\b(vendor|vender|supplier|party|category|item|product|department|city|agency)s?[- ]?wise\b|"
                   r"\b(by|per|har) (vendor|vender|supplier|party|category|item|product|department|city|agency)s?\b",
                   t) and q.dims:
        q.intent = "rank"
        q.n = max(q.n, 10)
    elif _EACH.search(t) and q.dims and q.dims[0] != "po" and q.metric_toks and not q.entities:
        q.intent = "rank"
        q.n = max(q.n, 10)
    elif q.markers & {TOP, BOTTOM}:
        q.intent = "rank"
    elif q.dims and q.dims[0] != "po" and not q.metric_toks and not q.entities and not q.months and (
            _LIST.search(t) or HOWMANY in q.toks):
        q.intent = "count" if HOWMANY in q.toks and not _LIST.search(t) else "list"
    elif q.dims and re.search(r"\b(which|kaun|kon|konsa|kaunsa|who)\b", t) and q.dims[0] not in {
            e.type for e in q.entities}:
        q.intent = "rank"
    if q.intent == "rank" and m is None and q.n == 1 and _LIST.search(t):
        q.n = 5
    # "best vendor" / "worst fabricator" with no measure: rank by on-time rate, not by size
    if q.intent == "rank" and q.dims and q.dims[0] in QUALITY and not q.metric_toks and _QUALITY.search(t):
        q.toks += tokens(QUALITY[q.dims[0]])
    return q


def is_unrelated_request(question: str) -> bool:
    return bool(_UNRELATED.search(norm(question)))


def _is_date_follow_up(text: str) -> bool:
    day_text = _DATE_FOLLOW_PREFIX.sub("", text.rstrip("?.!"), count=1)
    return is_day_expression(_DATE_FOLLOW_SUFFIX.sub("", day_text))


def is_factory_visit_question(question: str, context: dict | None = None) -> bool:
    text = norm(question)
    return bool(_FACTORY_VISIT.search(text) or (
        context and context.get("intent") == "factory_visits" and _is_date_follow_up(text)
    ))


def _presentation_style(question: str) -> str | None:
    text = norm(question).rstrip("?.!")
    text = re.sub(r"^(?:please |(?:can|could|would) you )+|(?:,? please| pls| plz)$", "", text).strip()
    if _REPEAT.fullmatch(text):
        return "repeat"
    if _EXPLAIN_PREVIOUS.fullmatch(text):
        return "detail"
    if _TERSE.search(text) and set(_TERSE.sub(" ", text).split()) <= {
        "in", "it", "this", "that", "me", "say", "give", "tell", "show", "answer", "summarize",
        "explain", "make", "keep", "bas", "sirf", "batao", "bolo",
    }:
        return "terse"
    if _DETAIL.fullmatch(text) or re.fullmatch(r"explain (?:it|this|that) in detail", text):
        return "detail"
    return None


def is_dashboard_question(q: Query, context: dict | None, vocab: Vocabulary) -> bool:
    """Check the current question before inheriting a previous turn's dashboard scope."""
    t = norm(q.text)
    if q.pages or q.intent == "record" or _DASHBOARD_PHRASES.search(t) or label_tokens(t) & _DASHBOARD_TERMS:
        return True
    if (q.entities and not q.metric_toks) or (q.dims and q.intent in ("list", "count")):
        return True
    if _HELP.fullmatch(t.rstrip("?.!")):
        return True
    words = set(raw_tokens(t))
    if words & _FEATURE_TERMS and (words - STOP - {"how", "kaise"}) <= (_FEATURE_TERMS | {"csv"}):
        return True
    if q.metric_toks:
        for label in vocab.labels:
            measure = label_tokens(label) - {"rate", "qty", "inr"}
            if measure <= q.metric_toks and measure - _GENERIC_LABEL_TERMS:
                return True
    if not isinstance(context, dict) or not context.get("metric"):
        return False
    if q.months and set(q.toks) <= {"how"}:
        return True
    return bool(q.metric_toks and q.metric_toks <= _FOLLOW_UP_TERMS)


# ------------------------------------------------------------------------------------------------ scoring
def mscore(label: str, q: Query, unit: str = "", fmt_: str | None = None) -> float:
    lt = label_tokens(label)
    if not lt:
        return 0.0
    if unit:
        lt = lt | (label_tokens(unit) & {"po"})
    added = {"rate"} - lt if fmt_ == "pct" else set()   # "On-time delivery" is a rate even without the word
    lt = lt | added
    qt = set(q.toks)
    matched = lt & qt
    if not matched or not (matched - MARKERS):
        return 0.0
    specific = bool(q.metric_toks - CONTEXT_WORDS)

    def w(t):
        if t in MARKERS or t in DIMENSION_WORDS:
            return 0.6
        return 0.5 if (specific and t in CONTEXT_WORDS) else 1.0
    weight = sum(w(t) for t in matched)
    # "paise / value / ₹" prefers rupee figures; "pcs / maal" prefers piece counts
    if "inr" in qt:
        weight += 0.6 if fmt_ in ("inr", "inr_full") else (-0.6 if (unit or "").lower() in ("pcs", "pc") else 0.0)
    if "qty" in qt and fmt_ in ("inr", "inr_full") and "qty" not in lt:
        weight -= 0.6
    if not (matched - MARKERS - set(DIMENSION_WORDS)) and q.metric_toks:
        weight *= 0.5                          # only "top"/"designer" matched while a real metric was asked
    extra = [w for w in lt - matched - added if w not in SOFT]
    penalty = 0.2 * len(extra)
    # "New order qty" is only part of "total orders"; "(new)" in brackets is just a note, as in "Achieved (new)"
    if "new" in lt and "new" not in qt and not re.search(r"\(new", label, re.I):
        penalty += 0.3
    # "Total revenue (new + repeat)" is neither "new revenue" nor "repeat revenue" alone
    if re.search(r"\bnew\s*\+\s*repeat\b", label, re.I) and len({"new", "repeat"} & qt) == 1:
        penalty += 0.5
    return weight + 0.5 * len(matched) / len(lt - (added - matched)) - penalty


def col_unit(label: str, data: dict) -> tuple[str, str]:
    """A column's display label and unit; 'Pending' borrows 'pcs' from the page's own 'Pending' KPI."""
    label, unit = fmt.unit_of(label)
    if not unit:
        want = label_tokens(label)
        unit = next((k.get("unit") or "" for k in kpi_list(data)
                     if want and k.get("unit") and label_tokens(k["label"]) == want), "")
    return label, unit


@dataclass
class Candidate:
    score: float
    kind: str                # kpi | cell | rank | trend
    page: str
    label: str
    fmt: str | None = None
    unit: str = ""
    value: object = None
    row: str = ""
    hint: str = ""
    rows: list = field(default_factory=list)  # rank / trend: [(name, value)]
    entity: Entity | None = None
    payload: dict | None = None

    def text(self):
        return fmt.value(self.value, self.fmt, self.unit)


class Assistant:
    """Answers one question at a time. ``fetch(page, filters)`` returns that dashboard page's API payload."""

    def __init__(self, fetch: Fetch, today_month: Callable[[], str | None] = lambda: None, interpreter=None):
        self.fetch = fetch
        self.today_month = today_month
        self.interpreter = interpreter          # optional Gemini helper (see gemini.py)

    # -------------------------------------------------------------------------------------------- public
    @staticmethod
    def presentation_reply(question: str, context: dict | None) -> dict | None:
        style = _presentation_style(question)
        if style is None:
            return None
        answer = (context or {}).get("answer")
        if not isinstance(answer, str) or not answer:
            return Assistant._reply("Ask me a dashboard question first, and I can shorten or explain the answer.",
                                    understood=False, intent="presentation")

        result = context.get("result") if "result" in context else fmt.reported_result(answer)
        figure = result.get("text") if isinstance(result, dict) else None
        if style == "terse" and isinstance(figure, str) and figure:
            answer = figure
        elif style == "detail":
            hint = context.get("hint")
            if isinstance(hint, str) and hint and hint not in answer:
                answer += f"\n{hint}"
            calculations = context.get("calculation")
            if isinstance(calculations, list):
                for calc in calculations:
                    if isinstance(calc, dict) and isinstance(calc.get("expression"), str):
                        answer += f"\nCalculated as {calc['expression']} = {calc.get('result')}."

        page = context.get("page")
        return Assistant._reply(answer, page if isinstance(page, str) else None, context, intent=style)

    def answer(self, question: str, context: dict | None = None) -> dict:
        question = (question or "").strip()[:MAX_QUESTION]
        if not question:
            return self._reply("Please type a question about the dashboard.", understood=False)
        presentation = self.presentation_reply(question, context)
        if presentation is not None:
            return presentation
        t = norm(question)
        if _GREET.match(t):
            return self._reply("Hi! I'm Flo-Wing Assistant. " + HELP, intent="greet")
        if _THANKS.match(t):
            return self._reply("You're welcome! Ask me anything else about the dashboard.", intent="thanks")
        if is_unrelated_request(t):
            return self._reply(_SCOPE_REPLY, understood=False, intent="out_of_scope")

        if is_factory_visit_question(t, context):
            return self._factory_visits(question, Snapshot(self.fetch))
        if _is_date_follow_up(t):
            return self._reply("What should I look up for that date? For example, factory visits.",
                               understood=False, intent="clarify")
        snap = Snapshot(self.fetch)
        vocab = Vocabulary(snap)
        q = parse(question, vocab, self.today_month())
        if not is_dashboard_question(q, context, vocab):
            return self._reply(_SCOPE_REPLY, understood=False, intent="out_of_scope")
        if len(vocab.errors) == len(PAGES):
            return self._reply("I can't read the dashboard data right now (" + next(iter(vocab.errors.values())) +
                               "). Please try again in a minute.", understood=False)
        self._inherit(q, context, vocab)
        result = self._solve(q, snap, vocab)
        if result is None and self.interpreter is not None:
            hint = self.interpreter.interpret(question, self._catalog(vocab))
            if hint:
                q2 = self._from_hint(hint, question, vocab)
                if q2 is not None:
                    q2.style = q.style
                    result = self._solve(q2, snap, vocab)
                    if result is not None:
                        result["engine"] = "gemini"
        if result is not None:
            return result
        return self._not_understood(q, snap, vocab)

    # -------------------------------------------------------------------------------------------- pieces
    @staticmethod
    def _reply(answer, page=None, context=None, understood=True, intent="", engine="rules"):
        p = PAGES.get(page) if page else None
        if context and "question" in context and "answer" not in context:
            context = {**context, "answer": answer}
        return {"answer": answer, "page": p.path if p else None, "page_label": p.label if p else None,
                "context": context or {}, "understood": understood, "intent": intent, "engine": engine}

    def _factory_visits(self, question: str, snap: Snapshot) -> dict:
        page, intent = "order-to-vendors", "factory_visits"
        day = parse_day(question, today_ist().date())
        if day is None:
            return self._reply("Which date should I look up for factory visits? For example, 12 Nov or 12/11/2026.",
                               page, understood=False, intent=intent)
        try:
            data = snap.get(page, {"visit_date": [day.isoformat()]})
        except DataUnavailable:
            return self._reply("I can't read the Order to vendors tabs right now. Please try again in a minute.",
                               page, understood=False, intent=intent)
        if not data["has_visit_columns"]:
            return self._reply("I couldn't find the Date, Supplier Name and Selection via columns in Order to vendors.",
                               page, understood=False, intent=intent)

        suppliers = data["suppliers"]
        date_label = f"{day.day} {day:%B %Y}"
        if suppliers:
            noun = "supplier" if len(suppliers) == 1 else "suppliers"
            answer = f"**{len(suppliers)} {noun}** marked **Factory Visited** on **{date_label}** in Order to vendors."
            answer += "\n" + "\n".join(f"• {name}" for name in suppliers)
        else:
            answer = f"I found no suppliers marked **Factory Visited** on **{date_label}** in Order to vendors."
        if data["incomplete"]:
            answer += "\nSome tabs could not be checked with up-to-date data, so the results may be incomplete."
        context = {"page": page, "intent": intent, "metric": "Factory visits", "date": day.isoformat(),
                   "question": question, "result": None}
        return self._reply(answer, page, context, intent=intent)

    def _inherit(self, q: Query, ctx: dict | None, vocab: Vocabulary):
        """Follow-up questions ("and for May?", "what about Rekha?") reuse the previous question's subject."""
        if not ctx or not isinstance(ctx, dict):
            return
        t = norm(q.text)
        refers_back = bool(_FOLLOW.search(t) or _PRONOUN.search(t))
        follow = refers_back or (len(q.toks) <= 1 and not q.entities and not q.months
                                 and not re.search(r"\b(total|overall|all)\b", t))
        unit_switch = bool(q.metric_toks) and q.metric_toks <= {"inr", "qty"}   # "paise me bata", "pcs me batao"
        if unit_switch and ctx.get("metric") and not q.entities and not q.months:
            prev = label_tokens(str(ctx["metric"])) - {"qty", "inr"}
            q.toks = q.toks + list(prev or label_tokens(str(ctx["metric"])))
            if not q.pages and ctx.get("page") in PAGES:
                q.pages.append(ctx["page"])
            for ref in ctx.get("entities") or []:
                e = vocab.entities.get((ref.get("type"), name_key(str(ref.get("value", "")))))
                if e:
                    q.entities.append(e)
            q.months = [m for m in ctx.get("months") or [] if m in vocab.months]
            q.inherited = True
            return
        if not q.metric_toks and ctx.get("metric") and (q.entities or q.months or follow) and q.intent in (
                "value", "compare", "rank", "trend"):
            q.toks = q.toks + list(label_tokens(str(ctx["metric"])))
            if not q.pages and ctx.get("page") in PAGES:
                q.pages.append(ctx["page"])
            if q.intent == "value" and ctx.get("intent") in ("rank", "trend") and not q.entities and not q.months:
                q.intent = ctx["intent"]
                q.dims = q.dims or ([ctx["dim"]] if ctx.get("dim") else [])
            q.inherited = True
        if (follow or q.inherited) and q.metric_toks:
            if not q.entities:
                for ref in ctx.get("entities") or []:
                    e = vocab.entities.get((ref.get("type"), name_key(str(ref.get("value", "")))))
                    if e:
                        q.entities.append(e)
            if not q.months:
                q.months = [m for m in ctx.get("months") or [] if m in vocab.months]
            if not q.pages and ctx.get("page") in PAGES:
                q.pages.append(ctx["page"])

    def _filters(self, page: str, q: Query, skip_type: str | None = None) -> dict | None:
        """API filters for this page, or None if a named thing can't be applied there."""
        p = PAGES[page]
        f: dict[str, list] = {}
        if q.months:
            if "month" not in p.filters:
                return None
            f["month"] = list(q.months)
        for e in q.entities:
            if e.type in ("month", skip_type, "po"):
                continue
            param = next((k for k, v in p.filters.items() if v == e.type), None)
            if not param or page not in e.raw:
                return None
            f.setdefault(param, []).append(e.raw[page])
        return f

    def _page_bonus(self, page: str, q: Query) -> float:
        return (0.5 if page in q.pages else 0.0) - 0.01 * PAGES[page].order - (0.3 if page == "overview" else 0.0)

    def _candidates(self, q: Query, snap: Snapshot) -> list[Candidate]:
        out: list[Candidate] = []
        named_types = {e.type for e in q.entities}
        rank_dim = q.dims[0] if q.intent == "rank" and q.dims else None
        for page in PAGES:
            bonus = self._page_bonus(page, q)
            # KPIs: only when every name in the question can be applied as a filter on this page
            f = self._filters(page, q)
            if f is not None and q.intent in ("value", "explain", "where", "rank") and not rank_dim:
                try:
                    data = snap.get(page, f)
                except DataUnavailable:
                    data = None
                if data:
                    for k in kpi_list(data):
                        s = mscore(k["label"], q, k.get("unit") or "", k.get("format"))
                        if s <= 0:
                            continue
                        if q.intent == "rank" and not (label_tokens(k["label"]) & {TOP, BOTTOM}):
                            s -= 0.5
                        out.append(Candidate(s + bonus + 0.1, "kpi", page, k["label"], k.get("format"),
                                             k.get("unit") or "", k.get("value"), hint=_hint(k.get("hint")),
                                             payload=data))
            # tables
            for etype in ({e.type for e in q.entities if e.type not in ("month", "po")} | {rank_dim, "month"}):
                if not etype:
                    continue
                tf = self._filters(page, q, skip_type=etype)
                if tf is None and etype != "month":
                    continue
                month_cell = etype == "month" and len(q.months) == 1 and q.intent in ("value", "explain")                     and not rank_dim
                if etype == "month":
                    if q.intent not in ("trend",) and not (rank_dim == "month") and not month_cell:
                        continue
                    tf = self._filters(page, replace(q, months=[]))
                    if tf is None:
                        continue
                try:
                    data = snap.get(page, tf)
                except DataUnavailable:
                    continue
                for tname, table in table_list(data):
                    if row_type(table) != etype:
                        continue
                    cols = table["columns"]
                    key_col = table.get("key_col")
                    for ci, c in enumerate(cols[1:], start=1):
                        s = mscore(c["label"], q, fmt_=c.get("format"))
                        if s <= 0 and not q.metric_toks and c["key"] == key_col:
                            s = 0.5 + (0.3 if HOME_PAGE.get(etype) == page else 0.0)
                        if s <= 0:
                            continue
                        label, unit = col_unit(c["label"], data)
                        if month_cell:
                            r = next((r for r in table["rows"] if r and r[0] == q.months[0]), None)
                            if r is not None and isinstance(r[ci], (int, float)) and not isinstance(r[ci], bool):
                                out.append(Candidate(s + bonus + 0.05, "mcell", page, label, c.get("format"), unit,
                                                     r[ci], row=str(r[0]), payload=data))
                            continue
                        if etype == rank_dim or (etype == "month" and q.intent == "trend"):
                            rows = [(r[0], r[ci]) for r in table["rows"]
                                    if r and isinstance(r[ci], (int, float)) and not SPECIAL_ROW.match(str(r[0]))]
                            if rows:
                                kind = "trend" if etype == "month" and q.intent == "trend" else "rank"
                                out.append(Candidate(s + bonus + 0.6, kind, page, label, c.get("format"), unit,
                                                     rows=rows, row=etype, payload=data))
                        elif etype in named_types:
                            for e in q.entities:
                                if e.type != etype:
                                    continue
                                r = next((r for r in table["rows"] if r and name_key(str(r[0])) == e.key), None)
                                if r is not None and r[ci] is not None:
                                    out.append(Candidate(s + bonus + 0.4, "cell", page, label, c.get("format"),
                                                         unit, r[ci], row=str(r[0]), entity=e, payload=data))
        out.sort(key=lambda c: -c.score)
        return out

    def _solve(self, q: Query, snap: Snapshot, vocab: Vocabulary) -> dict | None:
        if q.intent == "record":
            return self._record(q, snap)
        if q.intent in ("list", "count"):
            return self._list(q, vocab)
        if q.intent == "compare":
            res = self._compare(q, snap)
            if res:
                return res
            q.intent = "value"
        if q.intent == "value" and _COMPARE.search(norm(q.text)):
            res = self._compare_metrics(q, snap, vocab)
            if res:
                return res
        if q.intent == "explain" and not q.metric_toks:
            page = next(iter(q.pages), None)
            if page:
                return self._page_about(page, snap)
        features = self._feature(q)
        if features and (_HOWTO.search(norm(q.text)) or not q.metric_toks):
            return self._reply(features, intent="help")
        if q.pages and not q.entities and re.search(
                r"\b(what|show|shows|dikhata|dikhati|about|kya|contain|contains|explain|tell)\b", norm(q.text)):
            page = q.pages[0]
            page_words = {w for phrase in PAGES[page].words for w in tokens(phrase)} | {"page", "tab", "dashboard",
                                                                                         "screen", "section"}
            if not (q.metric_toks - page_words) and (re.search(r"\b(page|tab|dashboard|screen|section)\b",
                                                                norm(q.text)) or not q.metric_toks):
                return self._page_about(page, snap)
        if _HELP.search(norm(q.text)) and not q.metric_toks:
            return self._reply(HELP, intent="help")

        cands = self._candidates(q, snap)
        if q.intent in ("rank", "trend") and not any(c.kind in ("rank", "trend") and c.score >= THRESHOLD
                                                     for c in cands):
            q.intent = "value"
            cands = self._candidates(q, snap)
        if not cands or cands[0].score < THRESHOLD:
            return None
        best = cands[0]
        if q.intent == "where":
            p = PAGES[best.page]
            return self._reply(f"**{best.label}** is on the **{p.label}** page.", best.page,
                               self._ctx(q, best), intent="where")
        if q.intent == "explain":
            what = best.hint or self._describe(best)
            return self._reply(f"**{best.label}**: {what} Right now it is **{best.text()}**.", best.page,
                               self._ctx(q, best), intent="explain")
        if best.kind in ("rank",):
            return self._rank(q, best)
        if best.kind == "trend":
            return self._trend(q, best)
        return self._value(q, best, cands)

    # -------------------------------------------------------------------------------------------- answers
    def _ctx(self, q: Query, c: Candidate | None, intent: str | None = None) -> dict:
        result = None
        if c and c.kind in ("kpi", "cell", "mcell") and q.intent in ("value", "explain"):
            unit = {"pct": "%", "inr": "₹", "inr_full": "₹"}.get(c.fmt, c.unit)
            result = {"value": c.value, "unit": unit, "text": c.text()}
        return {"page": c.page if c else None, "metric": c.label if c else None, "intent": intent or q.intent,
                "entities": [e.ref() for e in q.entities if e.type != "po"], "months": q.months,
                "dim": c.row if c and c.kind in ("rank", "trend") else None, "question": q.text,
                "result": result, "hint": c.hint if c and c.hint else None}

    def _value(self, q: Query, best: Candidate, cands: list[Candidate]) -> dict:
        val = best.text()
        if q.style == "terse":
            return self._reply(f"**{val}**", best.page, self._ctx(q, best), intent="value")
        if best.kind == "cell":
            scope = q.scope(skip_type=best.entity.type if best.entity else None)
            who = best.row
            sentence = f"{best.label} for **{who}**{(' ' + scope) if scope else ''} is **{val}**."
        else:
            scope = q.scope()
            sentence = f"{best.label}{(' ' + scope) if scope else ''} is **{val}**."
        if not q.months and best.kind == "kpi" and "month" in PAGES[best.page].filters \
                and not best.label.lower().startswith(("top", "most")):
            sentence = sentence[:-1] + " (all months so far)."
        lines = [sentence]
        same = label_tokens(best.label) & set(q.toks)
        for alt in cands[1:4]:
            if alt.score >= best.score - 0.15 and alt.kind in ("kpi", "cell", "mcell") and alt.text() != val and \
                    alt.label != best.label and label_tokens(alt.label) & set(q.toks) == same and \
                    not (label_tokens(alt.label) - set(q.toks) - SOFT):
                lines.append(f"Also, {alt.label} is **{alt.text()}** ({PAGES[alt.page].label} page).")
                break
        if q.style == "detail":
            if best.hint:
                lines.append(best.hint)
            lines.extend(self._breakdown(best, q))
        return self._reply("\n".join(lines), best.page, self._ctx(q, best), intent="value")

    def _breakdown(self, c: Candidate, q: Query) -> list[str]:
        """For "in detail": the same figure split by designer / vendor / fabricator / category / month."""
        if not c.payload or c.kind == "mcell":
            return []
        best = None
        lt = label_tokens(c.label) - SOFT
        for _, t in table_list(c.payload):
            rt = row_type(t)
            if rt in (None, "po") or (c.entity and rt == c.entity.type):
                continue
            for ci, col in enumerate(t["columns"][1:], start=1):
                ov = len(label_tokens(col["label"]) & lt)
                if ov and (best is None or ov > best[0] or (ov == best[0] and rt != "month" and best[3] == "month")):
                    best = (ov, t, ci, rt)
        if not best:
            return []
        _, t, ci, rt = best
        col = t["columns"][ci]
        label, unit = fmt.unit_of(col["label"])
        rows = [(r[0], r[ci]) for r in t["rows"]
                if isinstance(r[ci], (int, float)) and r[ci] and not SPECIAL_ROW.match(str(r[0]))]
        unit = unit or (c.unit if col.get("format") == c.fmt else "")
        if rt != "month":
            rows.sort(key=lambda x: -x[1])
        if not rows:
            return []
        out = [f"By {TYPE_NAMES.get(rt, rt)} ({label}):"]
        out += [f"• {name}: {fmt.value(v, col.get('format'), unit)}" for name, v in rows[:8]]
        if len(rows) > 8:
            out.append(f"• … and {len(rows) - 8} more on the {PAGES[c.page].label} page.")
        return out

    def _rank(self, q: Query, c: Candidate) -> dict:
        low = BOTTOM in q.markers
        rows = sorted(c.rows, key=lambda x: x[1], reverse=not low)
        if c.row == "month":
            rows = [r for r in rows if r[1] is not None]
        if not rows:
            return None
        n = q.n if q.n > 1 else (5 if q.style == "detail" else 1)
        what = TYPE_NAMES.get(c.row, c.row)
        scope = q.scope()
        word = "lowest" if low else "highest"
        name, v = rows[0]
        tied = [nm for nm, val in rows if val == v]
        if n == 1 and len(tied) > 1 and q.style != "terse":
            names = ", ".join(f"**{x}**" for x in tied[:8]) + (f" and {len(tied) - 8} more" if len(tied) > 8 else "")
            text = (f"{len(tied)} {PLURALS.get(what, what + 's')} share the {word} {c.label}"
                    f"{(' ' + scope) if scope else ''} (**{fmt.value(v, c.fmt, c.unit)}**): {names}.")
        elif q.style == "terse":
            text = f"**{name}**"
        elif n == 1:
            text = (f"**{name}** is the {what} with the {word} {c.label}{(' ' + scope) if scope else ''}: "
                    f"**{fmt.value(v, c.fmt, c.unit)}**.")
        else:
            head = f"{'Bottom' if low else 'Top'} {min(n, len(rows))} {PLURALS.get(what, what + 's')} by {c.label}" + (f" {scope}" if scope else "") + ":"
            text = "\n".join([head] + [f"{i}. **{nm}**: {fmt.value(val, c.fmt, c.unit)}"
                                       for i, (nm, val) in enumerate(rows[:n], 1)])
        return self._reply(text, c.page, self._ctx(q, c, "rank"), intent="rank")

    def _trend(self, q: Query, c: Candidate) -> dict:
        rows = list(c.rows)
        while rows and not rows[-1][1]:
            rows.pop()
        if not rows:
            return None
        scope = q.scope()
        head = f"{c.label} month by month{(' ' + scope) if scope else ''}:"
        lines = [head] + [f"• {m}: **{fmt.value(v, c.fmt, c.unit)}**" for m, v in rows]
        if len({v for _, v in rows}) == 1:
            v = fmt.value(rows[0][1], c.fmt, c.unit)
            span = rows[0][0] if len(rows) == 1 else f"{rows[0][0]} to {rows[-1][0]}"
            lines = [f"**{v}**"] if q.style == "terse" else [
                f"{c.label}{(' ' + scope) if scope else ''} is **{v}** every month ({span})."]
        elif q.style == "terse":
            lines = [", ".join(f"{m}: {fmt.value(v, c.fmt, c.unit)}" for m, v in rows)]
        else:
            peak = max(rows, key=lambda x: x[1])
            lines.append(f"Highest: **{peak[0]}** ({fmt.value(peak[1], c.fmt, c.unit)}).")
        return self._reply("\n".join(lines), c.page, self._ctx(q, c, "trend"), intent="trend")

    def _compare(self, q: Query, snap: Snapshot) -> dict | None:
        groups: dict[str, list] = {}
        for e in q.entities:
            groups.setdefault(e.type, []).append(e)
        if len(q.months) >= 2 and not any(len(v) >= 2 for v in groups.values()):
            items = [("month", m) for m in q.months]
        else:
            etype, ents = max(groups.items(), key=lambda kv: len(kv[1]))
            if len(ents) < 2:
                return None
            items = [(etype, e) for e in ents]
        results = []
        first = None
        for etype, item in items:
            sub = replace(q, entities=list(q.entities), months=list(q.months), pages=list(q.pages))
            sub.intent = "value"
            if etype == "month":
                sub.months = [item]
                name = item
            else:
                sub.entities = [e for e in q.entities if e.type != etype] + [item]
                name = item.display
            if first is not None:
                sub.pages = list(dict.fromkeys([first.page] + sub.pages))
            cands = [c for c in self._candidates(sub, snap) if c.kind in ("kpi", "cell", "mcell")]
            if first is not None:
                cands = [c for c in cands if c.label == first.label and c.page == first.page] or cands
            if not cands or cands[0].score < THRESHOLD:
                return None
            c = cands[0]
            first = first or c
            results.append((name, c))
        lines = [f"{first.label}" + (f" in {fmt.months(q.months)}" if q.months and items[0][0] != "month" else "")
                 + ":"]
        lines += [f"• {name}: **{c.text()}**" for name, c in results]
        nums = [(name, c.value) for name, c in results if isinstance(c.value, (int, float))]
        if len(nums) == 2 and nums[0][1] != nums[1][1]:
            hi, lo = sorted(nums, key=lambda x: -x[1])
            lines.append(f"**{hi[0]}** is higher by **{fmt.diff(hi[1], lo[1], first.fmt, first.unit)}**.")
        elif len(nums) > 2:
            hi = max(nums, key=lambda x: x[1])
            lines.append(f"Highest: **{hi[0]}**.")
        if q.style == "terse":
            lines = [" · ".join(f"{name}: {c.text()}" for name, c in results)]
        return self._reply("\n".join(lines), first.page, self._ctx(q, first, "compare"), intent="compare")

    def _compare_metrics(self, q: Query, snap: Snapshot, vocab: Vocabulary) -> dict | None:
        """Two measures side by side: "new vs repeat revenue" -> New revenue and Repeat revenue."""
        t = _TERSE.sub(" ", _DETAIL.sub(" ", norm(q.text)))
        t = re.sub(r"^\s*(compare|comparison( of)?|difference( between)?|between)\s+", "", t)
        parts = [p.split() for p in re.split(r"\b(?:vs\.?|versus|and|aur|or|compared to|against|with)\b", t)]
        parts = [p for p in parts if p]
        if len(parts) != 2:
            return None
        left, right = parts
        if len(left) == 1 and len(right) > 1:          # "new vs repeat revenue": the shared word is at the end
            left = left + right[1:]
        elif len(right) == 1 and len(left) > 1:        # "revenue new vs repeat": the shared word is at the start
            right = left[:-1] + right
        results = []
        for words in (left, right):
            sub = parse(" ".join(words), vocab, self.today_month())
            sub.entities, sub.months, sub.intent = list(q.entities), list(q.months), "value"
            sub.pages = list(dict.fromkeys(q.pages + sub.pages))
            cands = [c for c in self._candidates(sub, snap) if c.kind in ("kpi", "cell", "mcell")]
            if not sub.metric_toks or not cands or cands[0].score < THRESHOLD:
                return None
            results.append(cands[0])
        a, b = results
        if a.label == b.label or (a.fmt == "pct") != (b.fmt == "pct") or (a.unit != b.unit and a.fmt != "inr"):
            return None
        scope = q.scope()
        if q.style == "terse":
            text = f"{a.label}: **{a.text()}** · {b.label}: **{b.text()}**"
        else:
            lines = [f"{a.label} vs {b.label}{(' ' + scope) if scope else ''}:",
                     f"• {a.label}: **{a.text()}**", f"• {b.label}: **{b.text()}**"]
            if isinstance(a.value, (int, float)) and isinstance(b.value, (int, float)) and a.value != b.value:
                hi, lo = (a, b) if a.value > b.value else (b, a)
                lines.append(f"**{hi.label}** is higher by **{fmt.diff(hi.value, lo.value, hi.fmt, hi.unit)}**.")
            text = "\n".join(lines)
        ctx = self._ctx(q, a, "compare")
        return self._reply(text, a.page, ctx, intent="compare")

    def _record(self, q: Query, snap: Snapshot) -> dict | None:
        e = next(e for e in q.entities if e.type == "po")
        for page in e.raw:
            try:
                data = snap.get(page)
            except DataUnavailable as err:
                return self._reply(f"I can't read the {PAGES[page].label} data right now ({err}).", page,
                                   understood=False)
            for _, t in table_list(data):
                if row_type(t) != "po":
                    continue
                r = next((r for r in t["rows"] if r and name_key(str(r[0])) == e.key), None)
                if r is None or len(t["columns"]) < 6:
                    continue
                parts = []
                for col, v in zip(t["columns"][1:], r[1:]):
                    if v in (None, ""):
                        continue
                    label, unit = fmt.unit_of(col["label"])
                    parts.append(f"• {label}: **{fmt.value(v, col.get('format'), unit)}**")
                timing = next((v for col, v in zip(t["columns"], r) if norm(col["label"]) in ("timing", "status")), "")
                if q.style == "terse":
                    return self._reply(f"**{timing or r[0]}**", page, {"page": page}, intent="record")
                return self._reply(f"**{r[0]}**\n" + "\n".join(parts), page, {"page": page}, intent="record")
        return None

    def _list(self, q: Query, vocab: Vocabulary) -> dict:
        dim = q.dims[0]
        if dim == "month":
            names = vocab.months
        else:
            names = sorted({e.display for e in vocab.of_type(dim)}, key=str.lower)
        what = TYPE_NAMES.get(dim, dim)
        if not names:
            return self._reply(f"I don't see any {PLURALS.get(what, what + 's')} on the dashboard right now.",
                               intent=q.intent)
        whats = PLURALS.get(what, what + "s")
        if q.intent == "count" or q.style == "terse":
            text = f"There are **{len(names)}** {whats} on the dashboard." if q.style != "terse" else f"**{len(names)}**"
            if q.style == "detail":
                text += "\n" + ", ".join(names)
        else:
            text = f"{len(names)} {whats}: " + ", ".join(names) + "."
        return self._reply(text, intent=q.intent, context={"intent": q.intent, "dim": dim})

    def _page_about(self, page: str, snap: Snapshot) -> dict:
        p = PAGES[page]
        lines = [f"The **{p.label}** page: {p.about}"]
        try:
            data = snap.get(page)
            ks = [k for k in kpi_list(data) if k.get("value") not in (None, "")][:6]
            if ks:
                lines.append("Headline numbers right now: " + "; ".join(
                    f"{k['label']} **{fmt.value(k['value'], k.get('format'), k.get('unit') or '')}**" for k in ks) + ".")
        except DataUnavailable:
            pass
        return self._reply("\n".join(lines), page, {"page": page}, intent="page")

    def _feature(self, q: Query) -> str | None:
        words = set(raw_tokens(q.text))
        for triggers, text in FEATURES:
            if words & triggers:
                return text
        return None

    @staticmethod
    def _describe(c: Candidate) -> str:
        return f"a figure on the {PAGES[c.page].label} page."

    def _not_understood(self, q: Query, snap: Snapshot, vocab: Vocabulary) -> dict:
        cands = [c for c in self._candidates(q, snap) if c.score > 0] if q.toks else []
        seen, sugg = set(), []
        for c in cands:
            key = (c.label, c.page)
            if key not in seen:
                seen.add(key)
                sugg.append(f"• {c.label} ({PAGES[c.page].label})")
            if len(sugg) == 3:
                break
        if vocab.errors:
            down = ", ".join(PAGES[p].label for p in vocab.errors)
            text = (f"I can't read some of the dashboard data right now ({down}), so I can't answer that yet. "
                    "Please try again in a minute.")
        elif sugg:
            text = "I'm not sure which number you mean. Did you mean one of these?\n" + "\n".join(sugg)
        else:
            text = ("Sorry, I couldn't match that to anything on the dashboard. " + HELP)
        return self._reply(text, understood=False, intent="unknown")

    # -------------------------------------------------------------------------------------------- Gemini hint
    def _catalog(self, vocab: Vocabulary) -> dict:
        return {"pages": {k: p.label for k, p in PAGES.items()}, "labels": sorted(vocab.labels),
                "dimensions": sorted(set(DIMENSION_WORDS.values())), "months": vocab.months}

    def _from_hint(self, hint: dict, question: str, vocab: Vocabulary) -> Query | None:
        """Turns the model's reading of the question back into words the rules understand, then re-parses."""
        intent = str(hint.get("intent") or "")
        metric = str(hint.get("metric") or "")
        if metric and metric not in vocab.labels:
            return None
        bits = []
        if intent in ("top", "bottom"):
            bits.append("highest" if intent == "top" else "lowest")
            if hint.get("n"):
                bits.append(str(hint["n"]))
        if intent == "trend":
            bits.append("month wise")
        if intent == "where":
            bits.append("where is")
        if intent == "count":
            bits.append("how many")
        if hint.get("dimension") in DIMENSION_WORDS.values():
            bits.append(str(hint["dimension"]))
        bits.append(metric)
        bits += [str(x) for x in hint.get("names") or [] if isinstance(x, str)][:4]
        bits += [str(x) for x in hint.get("months") or [] if isinstance(x, str)][:12]
        q = parse(" ".join(b for b in bits if b), vocab, self.today_month())
        if hint.get("page") in PAGES:
            q.pages = [hint["page"]]
        q.text = question
        return q
