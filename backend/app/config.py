"""Settings and the registry of Google Sheets the dashboard reads.

Everything that changes between environments comes from environment variables (see backend/.env.example).
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from functools import lru_cache


SHEET_REGISTRY: dict[str, dict] = {
    "order_status": {
        "name": "Order Status",
        "id": "1_qotGLwvg50KScUYij7sLYv7O2DANifLL-AhdGt0VzE",
        # one row per PO line
        "source_tabs": ["PO Master"],
    },
    "dues": {
        "name": "Supplier Dues",
        "id": "1QqWW4bnzeYvIz2atW19__Fv_r_jN8BbSKLpcByfeayI",
        # dated dues lists ("18th sep.", "4th Sep." ...). Empty = the left-most tab; the page can pick another.
        "source_tabs": [],
        # supplier credit days / discount / agency
        "terms_tabs": ["Updated Sheet", "List of creditor's"],
    },
    "order_to_vendors": {
        "name": "Order to Vendors",
        "id": "1IM7wW2ev7TC-Ud08dHOXWiMOESVSRI9LILS2TaAoIO4",
        "source_tabs": [],  # empty = the left-most tab; the page can pick another
    },
}


@dataclass(frozen=True)
class Settings:
    data_source: str = "demo"                   # "google" or "demo"
    service_account_info: dict | None = None    # parsed service-account JSON (google mode)
    live_ttl: int = 60                          # sheet DATA is re-read at most this often (seconds)
    tab_ttl: int = 600                          # tab list is re-read at most this often (seconds)
    refresh_cooldown: int = 15                  # minimum seconds between two forced refreshes
    passcode: str | None = None                 # when set, the API requires a login
    token_secret: str = "dev-only-secret"
    token_hours: int = 24 * 14
    cors_origins: list[str] = field(default_factory=list)


def _load_service_account() -> dict | None:
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    if not raw and not path:
        # simplest setup: the key saved as backend/service-account.json
        default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "service-account.json")
        if os.path.isfile(default):
            path = default
    if not raw and path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    if not raw:
        return None
    info = json.loads(raw)
    if "private_key" in info:
        info["private_key"] = str(info["private_key"]).replace("\\n", "\n")
    return info


def _load_dotenv() -> None:
    """Minimal .env reader (KEY=VALUE lines) so local runs need no extra package."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(here, ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)


_PUBLIC_SECRETS = {"", "dev-only-secret", "change-me"}


def _token_secret(sa: dict | None) -> str:
    """TOKEN_SECRET, or — if it was left empty or at the example value — one derived from the service account's private
    key, so a forgotten setting never leaves sign-in tokens signed with a publicly known secret."""
    secret = os.getenv("TOKEN_SECRET", "").strip()
    if secret not in _PUBLIC_SECRETS:
        return secret
    if sa and sa.get("private_key"):
        return hashlib.sha256(("flowing-token:" + sa["private_key"]).encode()).hexdigest()
    return "dev-only-secret"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _load_dotenv()
    sa = _load_service_account()
    source = os.getenv("DATA_SOURCE", "").strip().lower() or ("google" if sa else "demo")
    if source == "google" and sa is None:
        raise RuntimeError("DATA_SOURCE=google needs GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE.")
    origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
    return Settings(
        data_source=source,
        service_account_info=sa,
        live_ttl=int(os.getenv("LIVE_TTL_SECONDS", "60")),
        tab_ttl=int(os.getenv("TAB_TTL_SECONDS", "600")),
        refresh_cooldown=int(os.getenv("REFRESH_COOLDOWN_SECONDS", "15")),
        passcode=os.getenv("DASHBOARD_PASSCODE") or None,
        token_secret=_token_secret(sa),
        token_hours=int(os.getenv("TOKEN_HOURS", str(24 * 14))),
        cors_origins=origins,
    )
