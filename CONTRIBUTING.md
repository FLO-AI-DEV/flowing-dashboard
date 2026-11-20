# Working on the Flo-Wing dashboard

`main` is the tested, working dashboard. Nobody commits to `main` directly: every change goes through a branch and a
pull request (PR), and is merged only when CI is green and someone has checked the numbers against the sheet.

## 1. Get the code running

```bash
git clone https://github.com/FLO-AI-DEV/flowing-dashboard.git
cd flowing-dashboard
```

Backend (Python 3.12):

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS / Linux: source .venv/bin/activate)
pip install -r requirements.txt -r requirements-dev.txt
python -m uvicorn app.main:app --reload --port 8000
```

Frontend (Node 20.19+ or 22):

```bash
cd frontend
npm ci
npm run dev                         # http://localhost:5173
```

Without a key everything runs on built-in **demo data** (a *Demo data* badge shows in the top bar). For the real
sheets, ask the project owner for access and put the key at `backend/service-account.json` (it is git-ignored).
Never commit keys, `.env` files or `service-account.json`.

## 2. Make a branch

Always start from an up-to-date `main`:

```bash
git checkout main
git pull
git checkout -b feature/<sheet-or-area>-<short-description>
```

Branch names:

| Prefix | Use for | Example |
|---|---|---|
| `feature/` | a new sheet, page, KPI or chatbot skill | `feature/logistics-sheet`, `feature/gr-returns-page` |
| `fix/` | a wrong number or a bug | `fix/dues-ageing-dates` |
| `chore/` | docs, tooling, refactors without behaviour change | `chore/ci-cache` |

One sheet or one feature per branch keeps PRs small and easy to review.

## 3. Commit

Small commits with a clear message in the imperative:

```
Add logistics sheet to the registry
Show dispatch delay on the Logistics page
Fix ageing buckets when "Dues On" is blank
```

## 4. Check before you push

```bash
cd backend  && python -m pytest -q
cd frontend && npm run typecheck && npm test && npm run build
```

Then open the dashboard on the **real** sheets (`/api/health` → `"source": "google"`) and compare a few headline
numbers with the sheet itself.

## 5. Open a pull request into `main`

```bash
git push -u origin feature/<...>
```

On GitHub, open a PR into `main` and fill in the template. CI (`.github/workflows/ci.yml`) runs the backend tests and
the frontend typecheck, tests and build. Merge with **Squash and merge** once CI is green and a reviewer has approved.
Delete the branch after merging.

If `main` moved on while you worked, update your branch before merging:

```bash
git checkout main && git pull
git checkout feature/<...> && git merge main      # fix any conflicts, re-run the checks, push
```

## Recommended GitHub settings (owner)

Settings → Branches → add a rule for `main`: *Require a pull request before merging*, *Require status checks to
pass* (select **Backend (FastAPI) tests** and **Frontend (React) typecheck, tests, build**), and *Do not allow
bypassing the above settings*.

## Where things live

| Need to change… | Look in |
|---|---|
| Add a new Google Sheet | [`docs/ADDING_A_SHEET.md`](docs/ADDING_A_SHEET.md) |
| Sheet IDs / tab names | `backend/app/config.py` → `SHEET_REGISTRY` |
| Read & cache sheets | `backend/app/store.py`, `backend/app/sources/google.py` |
| A calculation / KPI | `backend/app/dashboards/*.py` |
| API routes | `backend/app/main.py` |
| A page | `frontend/src/pages/*.tsx` (+ types in `frontend/src/api/types.ts`, nav in `components/shell/Shell.tsx`) |
| Chatbot | [`docs/CHATBOT.md`](docs/CHATBOT.md) |

## Code style

- Python: 4 spaces, max ~120 characters per line, type hints on public functions, a docstring on each module saying
  which sheet / tab it reads. Calculations stay in `dashboards/`, never in `main.py`.
- TypeScript: strict mode (the typecheck must pass), one page per file, shared UI from `components/`.
- The API is read-only: nothing may ever write to a Google Sheet.
