# Flo-Wing Operations Dashboard

One clean screen for the owner: how many orders came in, where open orders are waiting, and **who must act**. It
reads Flo-Wing's **NEW ORDERSHEET-2026-27** Google Sheet (read-only) every minute. Built on the FLO dashboard code
(`akshatparashar/flo-dashboard`): the same API, cache, sign-in, tables and app shell, with Flo-Wing's order logic
added.

## Pages

| Page | What it answers |
|---|---|
| **Today** | Orders today and this month, open orders, how many are late. *Needs action*: one line per person who must act, worst first (red = late, amber = needs a look, green = clear). *Where open orders are waiting*: Mona's reply → PO → Billing, plus on hold. Every line opens the orders behind it. |
| **Orders** | Every open order, most overdue first: who must act, days open, status, and the reason typed in the sheet. Filter by stage, sales person, channel, late only. |
| **Team** | Who is holding orders (Mona, PO team, Billing team), the sales team's orders, sets, clients and days to bill, and the sheet rows someone forgot to complete. |
| **Clients** | Biggest clients, repeat buyers, and who has gone quiet. |
| **Payments** (CRM) | From the "New po sheet" payment follow-up form: pending ₹ per CRM member (Kiran, Suryansh, Lokesh), orders **not followed up for 2+ days** (measured from the form's time stamps), paid orders whose status was never set to RECIEVED, and money collected this month. |

The UI is the flo-dashboard UI unchanged: intro animation, data-flow panel, shell, tables and charts. Only the pages
and the data behind them are Flo-Wing's. The FLO logo is still in place until Flo-Wing artwork is added in
`frontend/src/components/Brand.tsx` and `frontend/public/brand/`.

## How the order sheet is read (messy sheets are expected)

`backend/app/locate.py` finds every table **by its headings, never by column letter**:

- the heading row can be anywhere in the top 30 rows (title rows, filter rows, blank rows above it are fine);
- inserted or moved columns don't matter;
- each column can have several spellings: `MONA REPLY` = `BILL/PO BY MONA`, `CLIENT NAME` = `PARTY NAME`…;
- merged two-row headings are read together (`PCS` under `DISPATCH` → `DISPATCH PCS`);
- blank rows, TOTAL rows, count rows and a pasted second heading row are skipped;
- quantities like `3+6 pcs` count as 9.

If a tab loses a heading the dashboard needs, that tab is left out and Today shows *"NOV CASH SALE: layout changed —
client not found"*, so you never get wrong figures without a warning. To support a new spelling, add it to
`ORDER_COLS` in `backend/app/dashboards/orders.py`.

Tabs read: every `… CREDIT SALE`, `… CASH SALE`, `… MUMBAI SALE` tab. New month tabs are picked up by name with no
code change. `full payment rcvd orders …` is ignored.

## The rules (change them in one place)

`STAGES` in `backend/app/dashboards/orders.py`:

| Stage | Owner | Deadline (days after order date) | Reason column shown |
|---|---|---|---|
| Mona's reply (BILL / PO), **CREDIT only** | Mona | 1 | HOLD REASON |
| PO: CREDIT when Mona said PO; **every CASH / MUMBAI order** | PO team | 3 | PO NOT DONE REASON |
| Billing (BILL STATUS = DONE) | Billing team | 3 | BILL NOT DONE REASON |

On-time % and usual days for each stage come from the real dates in the sheet: Mona's reply date (the column after
MONA REPLY), PO STATUS DATE TIME, and BILL STATUS TIME AND DATE. An order with a HOLD REASON is parked with its sales
person. Rows with no quantity, no sales person, or DONE without its date are listed for the sales person to fix.
**Owners and deadlines are first guesses and must be confirmed.**

Layouts seen in the real sheet, all covered by tests (`tests/test_orders_layout.py`):

- the heading row is in row 1 on some tabs and row 2 on others;
- an extra empty column shifts everything (APR CREDIT);
- Mona's columns have blank headings (APR CREDIT), or the date column is headed by a date (NOV CREDIT);
- a client's name was typed over CLIENT NAME (APR CASH);
- two DATE columns appear on one tab.

Headings that are blank or typed over are found by position (for example, "the column right after LEDGER"). That
guess is only used when the column's data looks right.

This month's and last month's tabs are re-read every minute; older month tabs every 6 hours (Google read limits).

## Automations (same numbers as the screen)

`GET /api/alerts` returns WhatsApp-ready text: the owner's morning summary, plus one message per person with late
work or incomplete rows. The next step is to write these into a Trigger tab that Iris sends, on a schedule (owner
9:30, employees 10:30 and 4 PM) and from a Nudge button.

## Run locally

```bash
# API (demo data unless a Google key is set)
cd backend && python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt && cp .env.example .env
uvicorn app.main:app --reload --port 8000
# Web (second terminal)
cd frontend && npm install && npm run dev                        # http://localhost:5173
```

Real data: set `DATA_SOURCE=google` and `GOOGLE_SERVICE_ACCOUNT_JSON` (or `_FILE`) in `backend/.env`, and share the
order sheet with the service account's `client_email` as **Viewer**. Use a **new** service-account key made for
Flo-Wing; don't reuse FLO's.

Deploy to Vercel exactly like the FLO dashboard: `vercel.json` is unchanged. Set `DATA_SOURCE`,
`GOOGLE_SERVICE_ACCOUNT_JSON`, `DASHBOARD_PASSCODE` and `TOKEN_SECRET`.

## Check real data with your key

```bash
cd backend
python scripts/check_access.py secrets/<key>.json   # which sheets the key can open
python scripts/check_data.py secrets/<key>.json     # what the dashboard reads from them, tab by tab
```

## Tests

`cd backend && pytest` covers the heading reader against shuffled and messy layouts, both real tab layouts, the
stage, late and owner rules, the alert texts, and every endpoint on the demo sheet. `cd frontend && npm test` runs
the unit tests, and `npm run build` typechecks and builds.

## Not adapted yet

`mobile/` is still the FLO phone app. Adapt it after the web pages are approved: same API, four screens.
