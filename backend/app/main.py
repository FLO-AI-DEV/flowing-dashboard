"""Flo-Wing Operations API (read-only). Built on the FLO dashboard's API.

Every dashboard is one GET endpoint that takes its filters as query parameters (repeat a parameter to select
several values: ?month=April-26&month=May-26) and returns ready-to-draw JSON: KPIs, tables and chart series.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .assistant import Assistant
from .assistant.analyst import GeminiAnalyst, build_facts, wants_analysis
from .assistant.gemini import GeminiInterpreter
from .assistant.memory import ChatMemory
from .config import SHEET_REGISTRY, get_settings
from .core import FY_LABEL, FY_MONTH_LABELS, MONTHNO_TO_LABEL, now_ist, today_ist
from .dashboards import dues as dus
from .dashboards import enquiry as enq
from .dashboards import generic as gen
from .dashboards import orders as ords
from .dashboards import overview as ovw
from .store import KINDS, Dataset, DataStore, meta

API_VERSION = "1.0.0"


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


app = FastAPI(title="Flo-Wing Operations API", version=API_VERSION, docs_url="/api/docs", openapi_url="/api/openapi.json")
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
            "auth_required": bool(s.passcode),
            "assistant": _assistant_mode()}


@app.get("/api/status", dependencies=[Depends(require_auth)])
def status():
    s = get_settings()
    return {"source": s.data_source, "ttl": s.live_ttl, "fy": FY_LABEL, "server_time": now_ist().isoformat(),
            "sources": get_store().status()}


@app.post("/api/refresh", dependencies=[Depends(require_auth)])
def refresh():
    done = get_store().refresh()
    return {"refreshed": done, "cooldown": get_settings().refresh_cooldown}


@app.get("/api/overview", dependencies=[Depends(require_auth)])
def overview(month: Multi = []):
    ds = get_store().datasets(KINDS)
    sources = {k: (v.data, v.error if v.data is None else None) for k, v in ds.items()}
    return _envelope(ovw.overview_dashboard(sources, _clean(month), today_ist()), *ds.values())


ORDER_KEYS = ("month", "vendor", "department", "category", "city", "timing")


@app.get("/api/orders", dependencies=[Depends(require_auth)])
def orders(month: Multi = [], vendor: Multi = [], department: Multi = [], category: Multi = [], city: Multi = [],
           timing: Multi = []):
    ds = get_store().dataset("order_status")
    f = {"month": _clean(month), "vendor": _clean(vendor), "department": _clean(department),
         "category": _clean(category), "city": _clean(city), "timing": _clean(timing)}
    return _envelope(ords.orders_dashboard(_need(ds), f), ds)


@app.get("/api/vendors", dependencies=[Depends(require_auth)])
def vendors(month: Multi = [], department: Multi = [], category: Multi = [], city: Multi = []):
    ds = get_store().dataset("order_status")
    f = {"month": _clean(month), "department": _clean(department), "category": _clean(category), "city": _clean(city)}
    return _envelope(ords.vendors_dashboard(_need(ds), f), ds)


@app.get("/api/dues", dependencies=[Depends(require_auth)])
def dues(tab: str = "", supplier: Multi = [], agency: Multi = []):
    store = get_store()
    ds = store.dataset("dues", tab or None)
    body = dus.dues_dashboard(_need(ds), {"supplier": _clean(supplier), "agency": _clean(agency)}, today_ist())
    body["tab"] = ds.tabs[0] if ds.tabs else ""
    body["tabs"] = store.all_tabs("dues")
    return _envelope(body, ds)


@app.get("/api/order-to-vendors", dependencies=[Depends(require_auth)])
def order_to_vendors(tab: str = "", vendor: Multi = [], status: Multi = []):
    store = get_store()
    ds = store.dataset("order_to_vendors", tab or None)
    body = gen.otv_dashboard(_need(ds), {"vendor": _clean(vendor), "status": _clean(status)})
    body["tab"] = ds.tabs[0] if ds.tabs else ""
    body["tabs"] = store.all_tabs("order_to_vendors")
    return _envelope(body, ds)


ENQUIRY_KEYS = ("month", "status", "handler", "topic", "party", "city", "po_status", "approval")


@app.get("/api/enquiries", dependencies=[Depends(require_auth)])
def enquiries(month: Multi = [], status: Multi = [], handler: Multi = [], topic: Multi = [], party: Multi = [],
              city: Multi = [], po_status: Multi = [], approval: Multi = []):
    store = get_store()
    ds = store.dataset("supplier_enquiry")
    f = dict(zip(ENQUIRY_KEYS, map(_clean, (month, status, handler, topic, party, city, po_status, approval))))
    body = enq.enquiry_dashboard(_need(ds), f, today_ist())
    body["tabs"] = {r: t for r, t in zip(SHEET_REGISTRY["supplier_enquiry"]["tabs"], ds.tabs)}
    return _envelope(body, ds)


@app.get("/api/sheets", dependencies=[Depends(require_auth)])
def sheets():
    store = get_store()
    out = []
    for k in KINDS:
        cfg = SHEET_REGISTRY[k]
        try:
            tabs = store.all_tabs(k)
            default = next((t for t in store.source_tabs(k) if t), "")
            err = None
        except Exception as e:  # noqa: BLE001
            tabs, default, err = [], "", str(e)
        out.append({"key": k, "name": cfg["name"], "url": f"https://docs.google.com/spreadsheets/d/{cfg['id']}/edit",
                    "tabs": tabs, "default_tab": default, "error": err})
    return {"sheets": out}


@app.get("/api/sheet", dependencies=[Depends(require_auth)])
def sheet(source: str, tab: str = "", q: str = Query(default="", max_length=100)):
    if source not in SHEET_REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown sheet.")
    store = get_store()
    try:
        title = store.source_tabs(source, tab or None)[0]
        e = store.grid(SHEET_REGISTRY[source]["id"], title)
    except Exception as ex:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(ex))
    ds = Dataset(source, e.value, e.fetched_at, e.version, error=e.error, stale=bool(e.error), tabs=[title])
    body = gen.sheet_view(e.value, q)
    body.update({"tab": title, "name": SHEET_REGISTRY[source]["name"]})
    return _envelope(body, ds)


# ------------------------------------------------------------------------------------------------ assistant
_ASSISTANT_PAGES = {"overview": overview, "orders": orders, "vendors": vendors, "dues": dues,
                    "order-to-vendors": order_to_vendors, "enquiries": enquiries}


def _assistant_fetch(page: str, filters: dict) -> dict:
    """The assistant reads the dashboard only through the same read-only functions the pages call."""
    return _ASSISTANT_PAGES[page](**filters)


@lru_cache(maxsize=1)
def get_assistant() -> Assistant:
    # GEMINI_MODE=labels: the older, stricter helper (sees only the question and label names)
    labels_mode = os.getenv("GEMINI_MODE", "analyst").strip().lower() == "labels"
    return Assistant(_assistant_fetch, today_month=lambda: MONTHNO_TO_LABEL.get(now_ist().month),
                     interpreter=GeminiInterpreter.from_env() if labels_mode else None)


@lru_cache(maxsize=1)
def get_analyst() -> GeminiAnalyst | None:
    return GeminiAnalyst.from_env()


def _assistant_mode() -> str:
    if get_analyst() is not None:
        return f"rules + gemini analyst ({get_analyst().model})"
    if get_assistant().interpreter is not None:
        return "rules + gemini labels"
    return "rules"


# Chat memory lives in this process only: it resets when the API restarts.
CHAT_MEMORY = ChatMemory()


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


SHEET_PAGES = {"orders": ("/orders", "Orders"), "vendors": ("/vendors", "Vendors"), "dues": ("/dues", "Supplier dues"),
               "order-to-vendors": ("/order-to-vendors", "Order to vendors"), "overview": ("/", "Overview")}


@app.post("/api/chat", dependencies=[Depends(require_auth)])
def chat(body: ChatIn):
    """Flo-Wing Assistant: answers a question from the dashboard's own numbers (read-only).

    Order: calculations / "why" questions go to the Gemini analyst (when a key is set); everything else is answered
    by the rules first, and the analyst only gets what the rules could not place. The chat's earlier turns
    (session_id) are kept in memory so follow-ups work.
    """
    history = CHAT_MEMORY.history(body.session_id)
    out = None
    if wants_analysis(body.message):
        out = _analyst_reply(body.message, history)
    if out is None:
        out = get_assistant().answer(body.message, body.context)
        if not out.get("understood"):
            out = _analyst_reply(body.message, history) or out
    CHAT_MEMORY.add(body.session_id, body.message, out.get("answer", ""))
    _log_question(body.message, out)
    return out


@app.post("/api/chat/reset", dependencies=[Depends(require_auth)])
def chat_reset(body: ChatReset):
    """Forget one chat's history (the reset button in the chat window)."""
    CHAT_MEMORY.clear(body.session_id)
    return {"ok": True}


_CHAT_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chat_questions.log")


def _log_question(question: str, out: dict):
    """Keeps a local list of questions (not answers or figures) so missed ones can be taught to the assistant.
    Turn off with CHAT_LOG=off in backend/.env."""
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
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")


@app.exception_handler(Exception)
async def unhandled(request, exc):
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on the server."})
