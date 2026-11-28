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
    "orders": {
        "name": "Order Sheet",
        # The dashboard reads "Flo-Wing Data Mirror" (owned by ai@floindia.com): one IMPORTRANGE per month tab, values
        # only. NEW ORDERSHEET-2026-27 itself is too slow to read directly (4.5 million cells under NOW() colour
        # rules make the Sheets API time out), and its owners keep it as it is.
        "id": "1HS61QM69oQXf6HeEeRo9GrM-2UaMzeiZtVxGptCPvSI",
        "source_id": "1jFwMi8NNxo8q_-6-AMOA9M58-rO1Cf_wgN54pAjCnHk",   # NEW ORDERSHEET-2026-27
        # Every month / channel tab is read (NOV CREDIT SALE, NOV CASH SALE, Nov MUMBAI SALE, OCT …).
        # New month tabs are picked up automatically by name; "full payment rcvd orders" is left out.
        "tab_rule": "orders.is_order_tab",
    },
    "enquiries": {
        "name": "Customer enquiries",
        # ENQUIRY SHEET 2025-2026 (owned by customercare@flowingindia.com). The tabs read are listed in
        # dashboards/enquiries.py (TABS); "NEW DATA" and "OLD DATA" are not used.
        # Read through its own mirror, "Flo-Wing Enquiries Mirror" (owned by ai@floindia.com): tabs ENQ CALLS / ENQ LOGISTICS /
        # ENQ BILLING are IMPORTRANGE of the real sheet 1140OgnYZ6B4_Cv2rSdD9wWUofvQfG0B_0KYnU7BWMoQ.
        "id": "1OqnAbP8B1VFw6ZJXT1_ZTMQLt4hQ3AWzzxjFCZcM3Bc",
    },
    "payments": {
        "name": "Payment follow-up",
        # CRM "New po sheet" (owner deepak@flowingindia.com, view-only for us) has ~12,000 rows. It is read through its own
        # mirror, "Flo-Wing PO Mirror" (owned by ai@floindia.com): tab PO LOG = IMPORTRANGE of 'Form responses 1'!A1:T20000
        # of the real sheet 1YtzUTartI0f1gDWwLFNDKsbwyYLO1cHeEhCL0ZaYQnE. Only the rows of the chosen time window are read.
        "id": "1XaVX7YA_7mYThyJctaXNguwWgaD-dRUgRi5dgeviT8Y",
        "source_id": "1YtzUTartI0f1gDWwLFNDKsbwyYLO1cHeEhCL0ZaYQnE",
        "tab": "PO LOG",
    },
    "returns": {
        "name": "Sales returns",
        # SALES RETURN 2025-2026 (owner digital@flowingindia.com), tab "Quality Check Sheet" (~50,000 rows, headings on
        # row 2). Read directly: share the sheet with the service account (Viewer). Only the rows of the chosen time
        # window are read.
        "id": "1F104Hy40W2Veqhzt_spZs-47l_LK4fcy1x5T-MP_55Q",
        "tab": "Quality Check Sheet",
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
    token_hours: int = 24
    cors_origins: list[str] = field(default_factory=list)


def _load_service_account() -> dict | None:
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
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
    if os.getenv("FLO_SKIP_DOTENV") == "1":     # the test suite runs on demo data, whatever is in .env
        return
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
        return hashlib.sha256(("flo-token:" + sa["private_key"]).encode()).hexdigest()
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
        token_hours=int(os.getenv("TOKEN_HOURS", "24")),
        cors_origins=origins,
    )
