# Checkpoint: web dashboard ready for Vercel

**Date:** 28 November 2026 · **Branch:** `main` (same commit as `vidihika`) · **Next phase:** the phone app

This file records where the project stands, what was decided, what was checked, and what is left, so work can pick up
from here.

---

## 1. Where things stand

| Area | State | Notes |
|---|---|---|
| Web dashboard (7 pages) | ✅ Done | Today, Orders, PO follow-up, Enquiries, Sales returns, Team, Clients |
| Password screen | ✅ Done | Asked first, before the preloader. Again every 24 hours. Password set by `DASHBOARD_PASSCODE`. |
| Preloader | ✅ Done | Plays right after every sign-in, once per browser session otherwise |
| Flo-Wing Assistant (chatbot) | ✅ Done | Ported from the old `main` and rewired to this dashboard's data |
| Vercel config | ✅ Ready | `vercel.json` with two services (`frontend`, `backend`), confirmed |
| Environment file | ✅ Ready | `backend/.env` on the developer PC (git-ignored), import it in Vercel |
| Tests | ✅ Passing | Backend 90, frontend 14, web build, mobile typecheck / lint / tests |
| Deployed on Vercel | ⏳ Not yet | To do next (steps in §5) |
| WhatsApp nudges | ⚠️ Off | `NUDGE_SHEET_ID` is empty, so the Send buttons are hidden |
| Gemini for the chatbot | ⚠️ Off | `GEMINI_API_KEY` is empty, so the chatbot uses rules + glossary only |
| Phone app | 🔜 Next phase | Expo project linked; screens not adapted yet (§6) |

---

## 2. What changed in this round

### Password every 24 hours, before the preloader
- `frontend/src/App.tsx`: nothing is shown until the server says whether a password is needed, so the preloader can
  never flash before the password screen. After sign-in the preloader plays, then the dashboard.
- A saved sign-in is only trusted until its expiry (read from the token itself); an open tab goes back to the password
  screen by itself when the 24 hours are up (`frontend/src/api/client.ts` → `tokenExpiry`).
- Server default `TOKEN_HOURS` is now 24 (`backend/app/config.py`). The phone app also drops an expired sign-in at
  start-up (`mobile/src/lib/auth.tsx`).

### Chatbot from the old `main`, on this dashboard's data
- `backend/app/assistant/`: engine, Gemini analyst, memory and formatting from the old `main`. Written for this
  dashboard:
  - `pages.py`: the pages, their filters and what each kind of row is (client, sales person, CRM member, step owner);
  - `datatools.py`: the tables Gemini can query (`orders`, `payments`, `enquiries`, `returns`);
  - `glossary.py`: about 40 terms (Mona's reply, PO, billing, on hold, CRM, SO, escalation L1/L2/L3, past the limit, GR,
    CR, QC pass / fail, 90-day policy…);
  - `text.py` / `engine.py`: Hinglish phrases, names that only appear in tables (Mona, a client), "this month" vs a named
    month.
- `backend/app/main.py`: `POST /api/chat`, `POST /api/chat/reset`, quick answers ("what needs attention", the PO split,
  where orders are waiting) and the assistant mode in `/api/health`.
- `frontend/src/components/assistant/`: the chat window from the old `main`, with starter questions for these pages.
- `backend/tests/test_assistant.py`: 17 tests that check the chat's figures against the pages.

### Branches
- `vidihika` had the right dashboard; old `main` had a different dashboard plus the chatbot.
- `main` was merged into `vidihika` keeping vidihika's files, then `main` was moved forward to that commit (no force
  push). The old `main` commits are still in the history (`0d97948` and before) if anything from them is needed.
- Not carried over from the old `main`: its pages (vendors, dues, order-to-vendors, today/filters), `.github/workflows/ci.yml`,
  `CONTRIBUTING.md`, `docs/CHATBOT.md`, the `.bat` launchers.

### Other
- `backend/tests/conftest.py`: tests always use demo data, even with a real `backend/.env` present.
- `vercel.json`: backend service marked `"framework": "fastapi"`.
- `.vercelignore`: `backend/secrets` added so key files are never uploaded.
- `mobile/app.json`: Expo owner `flo-wings-team`, slug `flowing`, project id `44b86b45-7422-437b-95a7-f2dd59547385`.
- `README.md`: rewritten with screenshots (`docs/screenshots/`) and diagrams.

---

## 3. Checked

| Check | Result |
|---|---|
| `cd backend && pytest` | 90 passed |
| `cd frontend && npm test` · `npm run build` | 14 passed · build OK |
| `cd mobile && npm run typecheck && npm run lint && npm test` | OK |
| Password API against the real `.env` | wrong password → 401; the team password → 24 h token; data needs the token |
| Browser, demo data | password screen → preloader → Today; chat answers ("Mona ke paas kitne waiting hai" → 9) |
| Chat figures vs page figures (demo) | match: late, orders today / this month, open, pending payments, enquiries, returns, open POs |

**Not checked yet:** the dashboard and chatbot on the real sheets on Vercel; Gemini answers (no key set).

---

## 4. Decisions to remember

- The dashboard **only reads** the order, payment, enquiry and returns sheets. The nudges sheet is the only one it
  writes to (adds rows to its Trigger tab).
- One password for the team, kept on the server only. Changing `TOKEN_SECRET` signs everyone out.
- Stage owners and deadlines (Mona 1 day, PO 3, Billing 3) and PO limits (due 7 days, limit 10) are the team's current
  rules; they live in `STAGES` (orders.py) and `DUE_DAYS` / `LIMIT_DAYS` / `ESC_LEVELS` (payments.py).
- Screenshots in the README use demo data only.

---

## 5. Deploy steps (next)

1. Vercel → **Add New Project** → import `FLO-AI-DEV/flowing-dashboard`, branch `main`, root = repo root.
2. **Settings → Environment Variables → Import .env** → `backend/.env`.
3. Optional now: fill `GEMINI_API_KEY` (smarter chatbot) and `NUDGE_SHEET_ID` (WhatsApp Send buttons).
4. Deploy, open the URL, sign in, check every page and ask the chatbot a few questions.
5. Note the final URL. If it is not `https://flo-dashboardd.vercel.app`, update `NUDGE_DASHBOARD_URL` in Vercel and
   `EXPO_PUBLIC_API_URL` in `mobile/eas.json`.

---

## 6. Next phase: the phone app

**State today.** `mobile/` is the earlier FLO phone app. Sign-in (with the 24 h rule) and the assistant screen work against
this API, but the other screens still call FLO endpoints that this API doesn't have (`/overview`, `/production`,
`/fabric-po`, `/target`, `/designer`, `/client`, `/samples`, `/fabricator`). **Don't hand out an APK built from the
current code**: those screens would show errors.

**Plan.**
1. Tabs to match the web: **Today** (`/api/home`), **Orders** (`/api/orders`, `/api/cause/{key}`), **PO follow-up**
   (`/api/po`, `/api/po/person`), **Enquiries** (`/api/enquiries`), **More** → Sales returns (`/api/returns`), Team
   (`/api/team`), Clients (`/api/clients`), Assistant, sign out.
2. Reuse the app's existing tables, KPI tiles, filters sheet and pull-to-refresh; replace the FLO screens and types.
3. Point `EXPO_PUBLIC_API_URL` at the live Vercel URL.
4. Build: `npx eas-cli@latest build --profile preview --platform android` → APK link and QR code on
   expo.dev (project **flo-wings-team / flowing**). The first build asks to generate an Android keystore: answer **Y**.
5. Later: iOS build (`--profile production --platform ios`, Apple account needed).
