# Flo-Wing Operations Dashboard

Live orders, vendors, supplier dues and supplier enquiries for Flo-Wing, read straight from Google Sheets and refreshed every minute,
with a chatbot that answers questions about the numbers in English or Hinglish.

Built on the FLO Operations Dashboard (`akshatparashar/flo-dashboard`): same FastAPI + React architecture, design,
live sync, intro, dark mode, phone layout and assistant. Only the sheets, calculations and pages are Flo-Wing's.

[![CI](https://github.com/FLO-AI-DEV/flowing-dashboard/actions/workflows/ci.yml/badge.svg)](https://github.com/FLO-AI-DEV/flowing-dashboard/actions/workflows/ci.yml)

## Pages

| Page | Sheet | What it answers |
|---|---|---|
| **Overview** | all | What needs attention now: the sheets wired into FLO, alert cards, orders, dues, vendor orders |
| **Orders** | Order Status (2026-2027) → `PO Master` | What's still to come in and what's late, by month, vendor, category, department, city; every PO |
| **Vendors** | Order Status → `PO Master` | Who owes the most, who is late, who delivers on time (scorecard) |
| **Order to vendors** | Order to vendors | Rows, totals and breakdown by status and vendor (columns found by name) |
| **Supplier dues** | DUES PAYMENT SUPPLIERS | Payable, overdue, due in 7 days, ageing, by supplier and agency, every bill |
| **Supplier enquiries** | Supplier's Enquiry Sheet → `Sheet1`, `Supplier's Enquiry Sheet`, `Terms Approval`, `Inactive25-26`, `purchase issues` | Pending / unsolved enquiries, who is following up and for how long, topics; suppliers waiting for a PO by city; payment-terms approvals; inactive suppliers. Switch lists at the top; filters and search per list |
| **Sheets** | all | Any tab of any sheet, live, with search and CSV |

**Flo-Wing Assistant** (robot, bottom right): "total pending", "sabse zyada pending kis vendor ke paas hai",
"pending kitna percent hai ordered ka", "payment due this week", "status of po 12",
"kitni enquiry pending hai gungun ke paas", "suppliers waiting for PO in surat", follow-ups like "and received?".
See [`docs/CHATBOT.md`](docs/CHATBOT.md).

## How it works

```
Google Sheets ──(read-only service account)──► FastAPI backend ──JSON──► React frontend
                                               │ store.py: 60 s cache, one read per sheet per minute
                                               │ dashboards/*.py: KPIs, tables, charts
                                               │ assistant/: rules + optional Gemini analyst
```

- **Read-only.** The key uses the `spreadsheets.readonly` scope; nothing can ever change a sheet.
- **Messy sheets are fine.** Header rows are found by their text and columns by name (the sheets' own spellings
  such as "vender name", "Recived Amt", "Pending Order Velue" are accepted), dates and amounts like
  `3,48,112.00` / `56700.00 Cr` are parsed. A missing column is reported on the page.
- **Resilient.** If Google doesn't answer, the last good copy stays on screen and the top bar says *Delayed*; one
  failing sheet never blanks the others.

## Run it

**Windows, no setup:** put the service-account key at `backend/service-account.json`, install Node.js LTS and
Python 3.12, then double-click **`START DASHBOARD.bat`**. For the chatbot's Gemini mode double-click
**`SET GEMINI KEY.bat`** once.

**Developers:** see [`CONTRIBUTING.md`](CONTRIBUTING.md). In short:

```bash
cd backend  && pip install -r requirements.txt -r requirements-dev.txt && python -m uvicorn app.main:app --reload --port 8000
cd frontend && npm ci && npm run dev        # http://localhost:5173
```

Without a key the API serves **demo data** (*Demo data* badge in the top bar). `GET /api/health` shows
`"source": "google"` when the real sheets are read. API docs: http://localhost:8000/api/docs.

## Configuration — `backend/.env` (copy from `backend/.env.example`)

| Setting | Default | Meaning |
|---|---|---|
| `GOOGLE_SERVICE_ACCOUNT_FILE` / `_JSON` | `backend/service-account.json` | The read-only Google key |
| `DATA_SOURCE` | `google` if a key is found, else `demo` | Force `demo` for development |
| `LIVE_TTL_SECONDS` | `60` | How often a sheet is re-read |
| `DASHBOARD_PASSCODE` | empty | Team passcode; empty = no sign-in |
| `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_MODE` | empty, `gemini-flash-lite-latest`, `analyst` | Chatbot AI (optional) |
| `CHAT_LOG` | `on` | Local log of chatbot questions (no figures) |

Sheet IDs and tab names: `backend/app/config.py` → `SHEET_REGISTRY`.

## Project layout

```
backend/
  app/
    main.py              API routes (read-only)
    config.py            settings + SHEET_REGISTRY (the sheets)
    store.py             reads, caches and parses sheets
    sources/             google.py (Sheets API, read-only) · demo.py (sample data)
    dashboards/          orders.py · dues.py · generic.py · overview.py  (all calculations)
    assistant/           chatbot: engine.py (rules) · analyst.py (Gemini) · calc.py · memory.py
  tests/                 pytest: API, chatbot question bank, analyst
frontend/
  src/pages/             one file per page
  src/components/        shell, charts, tables, filters, data-flow, assistant
docs/                    ADDING_A_SHEET.md · CHATBOT.md
.github/                 CI workflow + PR template
```

## Team workflow

`main` is always the tested dashboard. Each developer works on a branch (`feature/<sheet>-…`), opens a pull request,
and merges after CI passes and the numbers have been checked against the sheet. Adding a sheet is a step-by-step
recipe: [`docs/ADDING_A_SHEET.md`](docs/ADDING_A_SHEET.md).

## Security

Never commit `service-account.json`, `.env` or any API key — `.gitignore` blocks the usual names; check your diff
anyway. If a key is ever shared or committed, delete it in Google Cloud / AI Studio and create a new one.
