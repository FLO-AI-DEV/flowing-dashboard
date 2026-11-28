"""Flo-Wing Operations API (read-only).

Every dashboard is one GET endpoint that takes its filters as query parameters (repeat a parameter to select
several values: ?month=April-26&month=May-26) and returns ready-to-draw JSON: KPIs, tables and chart series.
GET /api/alerts returns the WhatsApp messages built from the same numbers (for the Iris trigger tab).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .config import SHEET_REGISTRY, get_settings
from .core import FY_LABEL, FY_MONTH_LABELS, MONTHNO_TO_LABEL, now_ist
from .assistant import Assistant
from .assistant import glossary
from .assistant.analyst import GeminiAnalyst, build_facts, wants_analysis
from .assistant.datatools import DataTools
from .assistant.gemini import GeminiInterpreter
from .assistant.memory import AnswerCache, ChatMemory
from .assistant.fmt import value as fmt_value
from .dashboards import enquiries as enqs
from .dashboards import orders as ords
from .dashboards import payments as pays
from .dashboards import returns as rets
from . import nudges
from .store import DEFAULT_PO_WINDOW, DEFAULT_RET_WINDOW, PO_WINDOWS, RET_WINDOWS, Dataset, DataStore, meta

API_VERSION = "1.4.0-po"


@lru_cache(maxsize=1)
def get_store() -> DataStore:
    settings = get_settings()
    if settings.data_source == "google":
        from .sources.google import GoogleSheetSource
        source = GoogleSheetSource(settings.service_account_info)
    else:
        from .sources.demo import DemoSheetSource
        source = DemoSheetSource()
    return DataStore(source, settings)


@asynccontextmanager
async def lifespan(_app):
    if os.getenv("SERVE_FRONTEND") == "1" or os.getenv("KEEP_WARM") == "1":    # a long-running local server
        get_store().keep_warm()
    if os.getenv("WARM_UP", "on").strip().lower() not in ("off", "0", "false", "no"):
        threading.Thread(target=_warm_up, daemon=True).start()
    yield


app = FastAPI(lifespan=lifespan, title="Flo-Wing Operations API", version=API_VERSION, docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(GZipMiddleware, minimum_size=1024)
_origins = get_settings().cors_origins
if _origins:
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def no_store(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


# ------------------------------------------------------------------------------------------------ auth
def _sign(payload: str) -> str:
    key = get_settings().token_secret.encode()
    return base64.urlsafe_b64encode(hmac.new(key, payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")


def make_token() -> str:
    exp = int(time.time()) + get_settings().token_hours * 3600
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"{payload}.{_sign(payload)}"


def check_token(token: str) -> bool:
    try:
        payload, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(payload)):
            return False
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return int(data.get("exp", 0)) > time.time()
    except Exception:
        return False


def require_auth(authorization: str | None = Header(default=None)):
    if not get_settings().passcode:
        return
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token or not check_token(token):
        raise HTTPException(status_code=401, detail="Sign in required.")


class Login(BaseModel):
    passcode: str


@app.get("/api/auth/status")
def auth_status(authorization: str | None = Header(default=None)):
    required = bool(get_settings().passcode)
    token = (authorization or "").removeprefix("Bearer ").strip()
    return {"required": required, "signed_in": (not required) or (bool(token) and check_token(token))}


_failed_logins: dict[str, list[float]] = {}


@app.post("/api/auth/login")
def login(body: Login):
    passcode = get_settings().passcode
    if not passcode:
        return {"token": "", "required": False}
    now = time.time()
    recent = [t for t in _failed_logins.get("all", []) if now - t < 60]
    if len(recent) >= 10:
        raise HTTPException(status_code=429, detail="Too many attempts. Wait a minute and try again.")
    if not hmac.compare_digest(body.passcode.encode(), passcode.encode()):
        _failed_logins["all"] = recent + [now]
        raise HTTPException(status_code=401, detail="That passcode is not right.")
    return {"token": make_token(), "required": True, "expires_in_hours": get_settings().token_hours}


# ------------------------------------------------------------------------------------------------ helpers
def _need(ds: Dataset):
    if ds.data is None:
        raise HTTPException(status_code=503, detail=ds.error or f"{SHEET_REGISTRY[ds.kind]['name']} is unavailable.")
    return ds.data


def _envelope(body: dict, *datasets: Dataset) -> dict:
    s = get_settings()
    metas = [meta(d) for d in datasets]
    synced = [m["synced_at"] for m in metas if m["synced_at"]]
    return {"meta": {"fy": FY_LABEL, "fy_months": FY_MONTH_LABELS, "source": s.data_source, "ttl": s.live_ttl,
                     "server_time": now_ist().isoformat(), "synced_at": min(synced) if synced else None,
                     "version": "-".join(m["version"] for m in metas), "stale": any(m["stale"] for m in metas),
                     "sources": metas},
            **body}


def _clean(values: list[str] | None) -> list[str]:
    return [v for v in (values or []) if v not in ("", "All")]


# One Query() per parameter (a shared Query instance would bind every list parameter to the first one's name).
Multi = Annotated[list[str], Query()]


# ------------------------------------------------------------------------------------------------ routes
@app.get("/api/health")
def health():
    s = get_settings()
    return {"ok": True, "version": API_VERSION, "source": s.data_source, "ttl": s.live_ttl,
            "auth_required": bool(s.passcode), "assistant": _assistant_mode()}


@app.get("/api/status", dependencies=[Depends(require_auth)])
def status():
    s = get_settings()
    return {"source": s.data_source, "ttl": s.live_ttl, "fy": FY_LABEL, "server_time": now_ist().isoformat(),
            "sources": get_store().status()}


@app.post("/api/refresh", dependencies=[Depends(require_auth)])
def refresh():
    done = get_store().refresh()
    return {"refreshed": done, "cooldown": get_settings().refresh_cooldown}


def _orders():
    ds = get_store().dataset("orders")
    return _need(ds), ds


@app.get("/api/home", dependencies=[Depends(require_auth)])
def home(month: Multi = [], channel: Multi = [], sales_person: Multi = []):
    """Four numbers, where orders are waiting, and who must act — the owner's one screen."""
    store = get_store()
    both = store.datasets(["orders", "payments"])
    ds, pds = both["orders"], both["payments"]
    d = _need(ds)
    f = {"month": _clean(month), "channel": _clean(channel), "sales_person": _clean(sales_person)}
    body = ords.home_dashboard(d, f)
    if pds.data is not None:      # payments joins the "Needs action" list; Today still works if that sheet is down
        rank = {"bad": 0, "warn": 1, "good": 2}
        body["actions"] = sorted(body["actions"] + pays.po_actions(pds.data),
                                 key=lambda r: (rank[r["tone"]], -r["late"], -r["oldest_days"]))
        body["notices"] = body["notices"] + [n for n in pds.data.get("issues", []) if n["kind"] != "info"]
        return _envelope(body, ds, pds)
    body["notices"] = body["notices"] + [{"kind": "warning", "text": f"Payment follow-up not loaded: {pds.error}"}]
    return _envelope(body, ds)


def _po(window: str):
    if window not in PO_WINDOWS:
        window = DEFAULT_PO_WINDOW
    ds = get_store().payments_dataset(window)
    return _need(ds), ds


@app.get("/api/po", dependencies=[Depends(require_auth)])
def po_overview(window: str = DEFAULT_PO_WINDOW, range: str = "", bucket: str = ""):
    """PO follow-up: how many POs are on track / due / overdue, and one row per caller and per sales person.
    Only the rows of `window` are read from the (very long) PO log."""
    d, ds = _po(window)
    body = pays.po_overview(d, period=range, bucket=bucket)
    body["windows"] = [{"key": k, "label": v[0]} for k, v in PO_WINDOWS.items()]
    return _envelope(body, ds)


@app.get("/api/po/person", dependencies=[Depends(require_auth)])
def po_person(role: str, name: str, window: str = DEFAULT_PO_WINDOW, range: str = "", bucket: str = "", order: str = "", focus: str = ""):
    """One caller's (role=crm) or sales person's (role=sp) open POs with what to do about each."""
    d, ds = _po(window)
    try:
        return _envelope(pays.person_dashboard(d, role, name, period=range, bucket=bucket, order=order, focus=focus), ds)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown person.")


@app.get("/api/po/report", dependencies=[Depends(require_auth)])
def po_report(role: str, name: str, window: str = DEFAULT_PO_WINDOW):
    """A small performance report for one sales person (role=sp) or caller (role=crm)."""
    d, ds = _po(window)
    try:
        return _envelope(pays.person_report(d, role, name), ds)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown person.")


@app.get("/api/returns", dependencies=[Depends(require_auth)])
def sales_returns(window: str = DEFAULT_RET_WINDOW, box: str = "", client: str = ""):
    """Sales returns (GR): QC pass / fail, calls still to be made, the 90-day policy, months, clients and reasons."""
    if window not in RET_WINDOWS:
        window = DEFAULT_RET_WINDOW
    ds = get_store().returns_dataset(window)
    d = _need(ds)
    body = rets.returns_dashboard(d, box=box, client=client)
    body["windows"] = [{"key": k, "label": v[0]} for k, v in RET_WINDOWS.items()]
    return _envelope(body, ds)


@app.get("/api/payments", dependencies=[Depends(require_auth)])
def payments(owner: Multi = [], sales_person: Multi = []):
    """Pending payments, who has not followed up, and collections — from the CRM payment follow-up sheet."""
    ds = get_store().dataset("payments")
    d = _need(ds)
    return _envelope(pays.payments_dashboard(d, {"owner": _clean(owner), "sales_person": _clean(sales_person)}), ds)


@app.get("/api/orders", dependencies=[Depends(require_auth)])
def orders(month: Multi = [], channel: Multi = [], sales_person: Multi = [], stage: Multi = [],
           late_only: bool = False, days: int = 0, range: str = "", order: str = "newest"):
    d, ds = _orders()
    f = {"month": _clean(month), "channel": _clean(channel), "sales_person": _clean(sales_person),
         "stage": _clean(stage), "late_only": late_only, "days": max(0, days), "range": range, "order": order}
    return _envelope(ords.orders_dashboard(d, f), ds)


@app.get("/api/cause/{key}", dependencies=[Depends(require_auth)])
def cause(key: str, range: str = "", order: str = "oldest"):
    d, ds = _orders()
    try:
        return _envelope(ords.cause_dashboard(d, key, period=range, order=order), ds)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown cause.")


# ------------------------------------------------------------------------------------------------ enquiries
def _enquiries():
    ds = get_store().dataset("enquiries")
    return _need(ds), ds


@app.get("/api/enquiries", dependencies=[Depends(require_auth)])
def enquiries():
    """Customer-care enquiries: today's counts, and what is still open grouped by what it is about."""
    d, ds = _enquiries()
    return _envelope(enqs.home_dashboard(d), ds)


@app.get("/api/enquiries/categories", dependencies=[Depends(require_auth)])
def enquiry_categories():
    """For each enquiry tab, a column of categories (the team's own, else a best guess) to paste into the sheet."""
    ds = get_store().dataset("enquiries")
    _need(ds)
    sid = SHEET_REGISTRY["enquiries"]["id"]
    out = []
    for tab, label in enqs.TABS:
        grid = get_store().grid(sid, tab).value
        try:
            out.append({"label": label, **enqs.suggest_column(grid, tab)})
        except Exception:
            continue
    return _envelope({"tabs": out}, ds)


@app.get("/api/enquiries/cause/{key}", dependencies=[Depends(require_auth)])
def enquiry_cause(key: str, range: str = "", order: str = "oldest", status: str = ""):
    d, ds = _enquiries()
    try:
        return _envelope(enqs.cause_dashboard(d, key, period=range, order=order, status=status), ds)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown enquiry group.")


# ------------------------------------------------------------------------------------------------ nudges
class NudgeBody(BaseModel):
    cause: str
    scope: str = "today"            # today / week / month / older / custom
    min_days: int = 0               # for scope=custom: waiting this many days or more
    force: bool = False             # send again although the same list went out recently
    group: str = "all"              # cause "enquiry": what the enquiries are about; cause "payment": "crm:Kiran" / "sp:Piyush"


def _nudge(body: NudgeBody, send: bool):
    box = nudges.get_outbox(get_settings())
    if box is None:
        raise HTTPException(status_code=404, detail="WhatsApp sending is not set up. Add NUDGE_SHEET_ID to the dashboard settings.")
    if body.cause == "enquiry":
        view, _ds = _enquiries()
    elif body.cause == "payment":
        view, _ds = _po(DEFAULT_PO_WINDOW)
    else:
        d, _ds = _orders()
        view = ords.stage_view(d["orders"])
    try:
        if send:
            return nudges.send(box, view, body.cause, body.scope, body.min_days, body.force, body.group)
        return nudges.preview(box, view, body.cause, body.scope, body.min_days, body.group)
    except nudges.NudgeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:     # the nudges sheet could not be reached
        raise HTTPException(status_code=502, detail=f"Could not reach the nudges sheet: {e}")


class NudgeAllBody(BaseModel):
    role: str = "crm"               # crm = calling team, sp = sales people, kavita = escalation digest
    scope: str = "todo"             # todo / escalated / overdue / all
    force: bool = False


def _nudge_all(body: NudgeAllBody, send: bool):
    box = nudges.get_outbox(get_settings())
    if box is None:
        raise HTTPException(status_code=404, detail="WhatsApp sending is not set up. Add NUDGE_SHEET_ID to the dashboard settings.")
    view, _ds = _po(DEFAULT_PO_WINDOW)
    try:
        return (nudges.send_all if send else nudges.preview_all)(box, view, body.role, body.scope, *([body.force] if send else []))
    except nudges.NudgeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not reach the nudges sheet: {e}")


@app.post("/api/nudge/all/preview", dependencies=[Depends(require_auth)])
def nudge_all_preview(body: NudgeAllBody):
    return _nudge_all(body, send=False)


@app.post("/api/nudge/all/send", dependencies=[Depends(require_auth)])
def nudge_all_send(body: NudgeAllBody):
    return _nudge_all(body, send=True)


@app.get("/api/nudge/who", dependencies=[Depends(require_auth)])
def nudge_who():
    """Whether sending is set up, and who each cause goes to (for the button label)."""
    box = nudges.get_outbox(get_settings())
    if box is None:
        return {"enabled": False, "test_mode": False, "who": {}}
    try:
        return {"enabled": True, "test_mode": box.test_mode, "who": nudges.who(box)}
    except Exception as e:
        return {"enabled": False, "test_mode": box.test_mode, "who": {}, "error": str(e)}


@app.post("/api/nudge/preview", dependencies=[Depends(require_auth)])
def nudge_preview(body: NudgeBody):
    return _nudge(body, send=False)


@app.post("/api/nudge/send", dependencies=[Depends(require_auth)])
def nudge_send(body: NudgeBody):
    return _nudge(body, send=True)


@app.get("/api/team", dependencies=[Depends(require_auth)])
def team(month: Multi = [], channel: Multi = []):
    d, ds = _orders()
    return _envelope(ords.team_dashboard(d, {"month": _clean(month), "channel": _clean(channel)}), ds)


@app.get("/api/clients", dependencies=[Depends(require_auth)])
def clients(channel: Multi = [], sales_person: Multi = []):
    d, ds = _orders()
    return _envelope(ords.clients_dashboard(d, {"channel": _clean(channel), "sales_person": _clean(sales_person)}), ds)


@app.get("/api/alerts", dependencies=[Depends(require_auth)])
def alerts():
    """WhatsApp-ready messages: the owner's morning summary and one message per person with late work."""
    both = get_store().datasets(["orders", "payments"])
    ds, pds = both["orders"], both["payments"]
    body = ords.alerts(_need(ds))
    if pds.data is not None:
        body["employees"] = body["employees"] + pays.alerts(pds.data)
        stale = int(pds.data["orders"]["stale"].sum()) if not pds.data["orders"].empty else 0
        if stale:
            body["owner"] += f" Payments: {stale} pending payments not followed up for {pays.FOLLOWUP_DAYS}+ days."
        return _envelope(body, ds, pds)
    return _envelope(body, ds)


# ------------------------------------------------------------------------------------------------ assistant
def _assistant_fetch(page: str, filters: dict) -> dict:
    """The assistant reads the dashboard only through the same read-only functions the pages call."""
    one = {k: (v[0] if v else "") for k, v in filters.items()}
    if page == "home":
        return home(**filters)
    if page == "orders":
        return orders(**filters)
    if page == "team":
        return team(**filters)
    if page == "clients":
        return clients(**filters)
    if page == "payments":
        return payments(**filters)
    if page == "po":
        return po_overview()
    if page == "enquiries":
        return enquiries()
    if page == "returns":
        return sales_returns(client=one.get("client", ""))
    raise KeyError(page)


@lru_cache(maxsize=1)
def get_assistant() -> Assistant:
    # GEMINI_MODE=labels: the older, stricter helper (sees only the question and label names)
    labels_mode = os.getenv("GEMINI_MODE", "analyst").strip().lower() == "labels"
    return Assistant(_assistant_fetch, today_month=lambda: MONTHNO_TO_LABEL.get(now_ist().month),
                     interpreter=GeminiInterpreter.from_env() if labels_mode else None)


@lru_cache(maxsize=1)
def get_datatools() -> DataTools:
    return DataTools(get_store())


@lru_cache(maxsize=1)
def get_analyst() -> GeminiAnalyst | None:
    return GeminiAnalyst.from_env(tools=get_datatools())


def _assistant_mode() -> str:
    if get_analyst() is not None:
        return f"rules + gemini analyst ({get_analyst().model})"
    if get_assistant().interpreter is not None:
        return "rules + gemini labels"
    return "rules"


# Chat memory and the answer cache live in this process only: they reset when the API restarts.
CHAT_MEMORY = ChatMemory()
ANSWER_CACHE = AnswerCache()

SHEET_PAGES = {"home": ("/", "Today"), "orders": ("/orders", "Orders"), "team": ("/team", "Team"),
               "clients": ("/clients", "Clients"), "payments": ("/payments", "PO follow-up"),
               "po": ("/payments", "PO follow-up"), "enquiries": ("/enquiries", "Enquiries"),
               "returns": ("/returns", "Sales returns")}


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    context: dict | None = None
    session_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]*$")


class ChatReset(BaseModel):
    session_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]*$")


def _analyst_reply(question: str, history: list) -> dict | None:
    analyst = get_analyst()
    if analyst is None:
        return None
    try:
        facts, page = build_facts(get_assistant(), question, MONTHNO_TO_LABEL.get(now_ist().month))
    except Exception:  # noqa: BLE001 - never break the chat because a sheet is down
        return None
    text = analyst.answer(question, facts, history)
    if not text:
        return None
    p = SHEET_PAGES.get(page) if page else None
    return {"answer": text, "page": p[0] if p else None, "page_label": p[1] if p else None, "context": {},
            "understood": True, "intent": "analysis", "engine": "gemini"}


@app.post("/api/chat", dependencies=[Depends(require_auth)])
def chat(body: ChatIn):
    """Flo-Wing Assistant: answers a question from the dashboard's own data (read-only).

    Order (fastest first):
      1. meaning of a word ("GR kya hai")          -> glossary, instant
      2. the same question asked before            -> answer cache (same data version), instant
      3. calculations, look-ups of particular rows -> Gemini analyst with exact data tools (when a key is set)
      4. everything else                           -> the rules; what they can't place goes to the analyst
    The chat's earlier turns (session_id) are kept in memory so follow-ups work.
    """
    history = CHAT_MEMORY.history(body.session_id)
    out = glossary.answer(body.message)
    key = None
    if out is None and not history:
        try:
            key = AnswerCache.key(body.message, body.context, get_datatools().version())
            out = ANSWER_CACHE.get(key)
        except Exception:  # noqa: BLE001 - the cache is only a shortcut
            key = None
    if out is None:
        out = _answer(body, history)
        if key is not None and out.get("understood"):
            ANSWER_CACHE.put(key, out)
    CHAT_MEMORY.add(body.session_id, body.message, out.get("answer", ""))
    _log_question(body.message, out)
    return out


_HELLO = re.compile(r"^\s*(hi|hello|hey|help|madad|menu|what can you do|kya kar sakte ho)\s*[?!.]*\s*$", re.I)
_ATTENTION = re.compile(r"\b(needs? attention|attention|urgent|alerts?|what should i (check|look at)|who must act|"
                        r"kya dekhna|kya urgent|aaj ka summary|today'?s summary|summary of (everything|all)|"
                        r"sab ka summary|status report|kya chal raha|what happened today|aaj kya hua)\b", re.I)


def _attention_answer() -> dict | None:
    data = home()
    figs = ", ".join(f"{k['label'].lower()} **{fmt_value(k.get('value'), k.get('format'), k.get('unit') or '')}**"
                     for k in data.get("kpis", []))
    lines = [f"**Today**: {figs}." if figs else "**Today**"]
    acts = [a for a in data.get("actions", []) if a.get("tone") in ("bad", "warn")][:8]
    for a in acts:
        late = f", {a['late']} late" if a.get("late") else ""
        lines.append(f"• **{a['who']}** ({a['stage']}{late}): {a.get('what', '')}".rstrip(": "))
    for n in data.get("notices", [])[:3]:
        lines.append(f"• ⚠ {n.get('text', '') if isinstance(n, dict) else n}")
    if len(lines) == 1 and not figs:
        return None
    return {"answer": "\n".join(lines), "page": "/", "page_label": "Today", "context": {}, "understood": True,
            "intent": "overview", "engine": "rules"}


_PO_SPLIT = re.compile(r"\b(escalat\w*|l[123]|past (the )?limit|overdue pos?|due soon|on track|not sent|"
                       r"po (status|buckets?|split))\b", re.I)
_PIPELINE = re.compile(r"\b(on hold|hold|pipeline|where are (the )?orders|waiting for (mona|po|billing)|"
                       r"kahan atke|kaha atke|stuck)\b", re.I)


def _money(v) -> str:
    return fmt_value(v, "inr")


def _po_split() -> dict:
    d = po_overview()
    lines = ["**PO follow-up** (open POs by days since the PO was sent):"]
    lines += [f"• {b['label']}: **{b['count']}** ({_money(b['amount'])})" for b in d.get("buckets", [])]
    lv = (d.get("escalation") or {}).get("levels") or []
    if lv:
        lines.append("Escalation: " + "; ".join(f"**{x['key']}** {x['count']} ({_money(x['amount'])})" for x in lv) + ".")
    return {"answer": "\n".join(lines), "page": "/payments", "page_label": "PO follow-up", "context": {},
            "understood": True, "intent": "summary", "engine": "rules"}


def _pipeline() -> dict:
    d = home()
    lines = ["**Where orders are waiting:**"]
    for p in d.get("pipeline", []):
        late = f", {p['late']} late" if p.get("late") else ""
        who = f" ({p['owner']})" if p.get("owner") else ""
        lines.append(f"• {p['label']}{who}: **{p['count']}**{late}")
    return {"answer": "\n".join(lines), "page": "/", "page_label": "Today", "context": {}, "understood": True,
            "intent": "summary", "engine": "rules"}


def _quick(message: str) -> dict | None:
    """Greetings, 'what needs attention', the PO split and the order pipeline are answered without parsing."""
    try:
        if _PO_SPLIT.search(message) and len(message.split()) <= 10:
            return _po_split()
        if _PIPELINE.search(message) and len(message.split()) <= 10:
            return _pipeline()
    except Exception:  # noqa: BLE001 - a sheet that can't be read: fall through to the rules
        pass
    if _HELLO.match(message):
        out = get_assistant().answer("what can you do", None)
        out["answer"] = out["answer"] + "\n\nYou can also ask what any word means, e.g. \"GR kya hai\" or \"what is L3 escalation\"."
        return out
    if _ATTENTION.search(message) and len(message.split()) <= 8:
        try:
            return _attention_answer()
        except Exception:  # noqa: BLE001 - fall back to the rules
            return None
    return None


def _answer(body: ChatIn, history: list) -> dict:
    quick = _quick(body.message)
    if quick is not None:
        return quick
    follow_up = bool(history) and len(body.message.split()) <= 4      # "and late?", "uska total?"
    if get_analyst() is not None and (wants_analysis(body.message) or follow_up):
        out = _analyst_reply(body.message, history)
        if out is not None:
            return out
    rules = get_assistant().answer(body.message, body.context)
    if not rules.get("understood"):
        return _analyst_reply(body.message, history) or rules
    return rules


def _warm_up():
    """Reads every sheet and builds the lookup tables once at start, so the first question is fast."""
    try:
        get_datatools().tables()
        get_assistant().answer("open orders", None)
    except Exception:  # noqa: BLE001 - warming up is best effort
        pass


@app.post("/api/chat/reset", dependencies=[Depends(require_auth)])
def chat_reset(body: ChatReset):
    """Forget one chat's history (the reset button in the chat window)."""
    CHAT_MEMORY.clear(body.session_id)
    return {"ok": True}


_CHAT_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chat_questions.log")


def _log_question(question: str, out: dict):
    """Keeps a local list of questions (not answers or figures) so missed ones can be taught to the assistant.
    Turn off with CHAT_LOG=off. On Vercel the disk is read-only, so nothing is written there."""
    if os.getenv("CHAT_LOG", "on").strip().lower() in ("off", "0", "false", "no"):
        return
    try:
        status = "MISSED" if not out.get("understood") else ("GEMINI" if out.get("engine") == "gemini" else "ok")
        with open(_CHAT_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{now_ist():%Y-%m-%d %H:%M}\t{status}\t{question.strip()[:300]}\n")
    except OSError:
        pass


# ------------------------------------------------------------------------------------------------ static (optional)
_dist = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend", "dist")
if os.getenv("SERVE_FRONTEND") == "1" and os.path.isdir(_dist):
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=os.path.join(_dist, "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        # Real files (logo, favicon) as they are; every page address (/orders, /team, ...) gets the app.
        f = os.path.join(_dist, path)
        if path and not path.startswith("api") and os.path.isfile(f):
            return FileResponse(f)
        return FileResponse(os.path.join(_dist, "index.html"))


@app.exception_handler(Exception)
async def unhandled(request, exc):
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on the server."})
