"""Check what a Google service-account key can read.

    python scripts/check_access.py path/to/key.json

For every Flo-Wing sheet it prints OK (with its tabs and the first row of data) or the reason it failed.
Read-only: it never changes anything in the sheets.
"""
from __future__ import annotations

import json
import sys
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
API = "https://sheets.googleapis.com/v4/spreadsheets"

SHEETS = {
    "CRM": {
        "NEW ORDERSHEET-2026-27": "1jFwMi8NNxo8q_-6-AMOA9M58-rO1Cf_wgN54pAjCnHk",
        "ENQUIRY SHEET 2025-2026": "1140OgnYZ6B4_Cv2rSdD9wWUofvQfG0B_0KYnU7BWMoQ",
        "New po sheet": "1YtzUTartI0f1gDWwLFNDKsbwyYLO1cHeEhCL0ZaYQnE",
    },
    "Merchandiser": {
        "Flowing Vendor Details (Responses)": "1mG9hJoZCf7bJcjXULdSoNf01XsB70MGECt0tJHkISEE",
        "Vendor details sheet new": "18WmdcJOqRg6vQGD0Thl1FMg1-hoSrJjbJiriTPGKLdM",
        "Supplier's Enquiry Sheet": "16-BtrzzzHdoQ7HZrMyCUkZxEQJ7YduoaHbmW_v1d9B0",
        "DUES PAYMENT SUPPLIERS": "1QqWW4bnzeYvIz2atW19__Fv_r_jN8BbSKLpcByfeayI",
        "ORDER STATUS REPORT": "1zvH9hUmP_UPnaw2ir7F4DaErfppx-fEiVedKTGK3iBg",
        "Order to vendors": "1IM7wW2ev7TC-Ud08dHOXWiMOESVSRI9LILS2TaAoIO4",
    },
    "Logistics": {
        "Parcel Inward OutWard 2026-2027": "1gjXsflqBalB5O5QMU9Z1fdEy0KPHJ7eH1KVZp_UA-6Y",
    },
    "GR": {
        "SALES RETURN 2025-2026": "1F104Hy40W2Veqhzt_spZs-47l_LK4fcy1x5T-MP_55Q",
    },
    "Digital": {
        "INSTAGRAM CLIENTS": "17LBrUkDyLFgmPrYQ5dQkiDeDy89O3CiFch0-OnnWCOI",
        "SEND PHOTOS TO CLIENTS": "1Hub4UHneEFAPX60MrGe7jqhU1eu7UzCvfZ5Pktsge0A",
    },
}

GREEN, RED, DIM, END = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def reason(resp) -> str:
    try:
        msg = resp.json().get("error", {}).get("message", "")
    except ValueError:
        msg = resp.text[:150]
    if resp.status_code == 403 and ("has not been used" in msg or "disabled" in msg):
        return "Google Sheets API is not enabled in this Cloud project (APIs & Services → Library → Enable)"
    if resp.status_code == 403:
        return "not shared with this key's email — Share the sheet with it as Viewer"
    if resp.status_code == 404:
        return "sheet not found (wrong ID or deleted)"
    return f"HTTP {resp.status_code}: {msg}"


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        info = json.load(f)
    if info.get("type") != "service_account":
        sys.exit("That file is not a service-account key (expected \"type\": \"service_account\").")
    session = AuthorizedSession(Credentials.from_service_account_info(info, scopes=SCOPES))
    print(f"Key: {info['client_email']}\n")

    ok = total = 0
    for dept, sheets in SHEETS.items():
        print(dept)
        for name, sid in sheets.items():
            total += 1
            r = session.get(f"{API}/{sid}", params={"fields": "properties.title,sheets.properties.title"}, timeout=30)
            if r.status_code != 200:
                print(f"  {RED}✗{END} {name}: {reason(r)}")
                continue
            tabs = [s["properties"]["title"] for s in r.json().get("sheets", [])]
            a1 = "'" + tabs[0].replace("'", "''") + "'!A1:H3"           # tab names with spaces/quotes
            first = session.get(f"{API}/{sid}/values/{quote(a1, safe='')}", timeout=30)
            rows = first.json().get("values", []) if first.status_code == 200 else []
            sample = " | ".join(c for c in (rows[0] if rows else []) if c.strip())[:90]
            ok += 1
            print(f"  {GREEN}✓{END} {name}: {len(tabs)} tabs {DIM}(first tab '{tabs[0]}': {sample or 'empty'}){END}")
        print()
    print(f"{ok} of {total} sheets readable with this key.")


if __name__ == "__main__":
    main()
