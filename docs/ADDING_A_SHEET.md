# Adding a new sheet (e.g. Logistics, GR, CRM, Merchandiser)

Each developer can own one sheet on their own branch. The steps are always the same; `Order to vendors` and
`Supplier dues` are small examples to copy.

## 0. Share the sheet

Share the Google Sheet with the service account's `client_email` (inside `service-account.json`) as **Viewer**.

## 1. Register it — `backend/app/config.py`

```python
SHEET_REGISTRY = {
    ...
    "logistics": {
        "name": "Logistics",
        "id": "<the long ID from the sheet URL, between /d/ and /edit>",
        "source_tabs": ["Dispatch 2026-27"],   # tab to read; [] = the left-most tab
    },
}
```

The **Sheets** page shows it straight away (any tab, live, with search), with no other code.

## 2. Parse and calculate — `backend/app/dashboards/logistics.py`

Follow `orders.py`:

- `parse_logistics(grid, today)` → `(DataFrame, error)`. Find the header row by its text (`find_header`), map
  columns by name with aliases (`map_columns`), clean numbers with `core.num`, dates with `core.parse_dates`.
  Return an error message (not an exception) when a needed column is missing.
- `logistics_dashboard(df, filters)` → a dict with `options`, `notices`, `kpis` (built with `tables.kpi`),
  `tables` (built with `tables.table`) and `charts`.

Then teach the store to load it — `backend/app/store.py`: add the key to `KINDS` and a branch in `_parse`.

## 3. Expose it — `backend/app/main.py`

```python
@app.get("/api/logistics", dependencies=[Depends(require_auth)])
def logistics(month: Multi = [], transporter: Multi = []):
    ds = get_store().dataset("logistics")
    return _envelope(lgs.logistics_dashboard(_need(ds), {"month": _clean(month), "transporter": _clean(transporter)}), ds)
```

Add a test in `backend/tests/test_api.py` and demo data in `backend/app/sources/demo.py` so CI can run it.

## 4. Show it — `frontend/`

1. Response type in `src/api/types.ts` (copy `OrdersData` and adjust).
2. Page in `src/pages/Logistics.tsx` (copy `Orders.tsx`: `useDashboard`, `PageHead`, `FilterBar`, `KpiStrip`,
   `Panel`, `DataTable`, charts).
3. Route in `src/App.tsx` and a sidebar item in `src/components/shell/Shell.tsx` (`NAV`).
4. Optional: a wire on the Overview (`src/components/DataFlow.tsx` `ORDER` / `LABEL`, and an alert in
   `backend/app/dashboards/overview.py`).

## 5. Teach the chatbot

In `backend/app/assistant/pages.py` add a `Page(...)` for the new endpoint (its words, description and filters),
and register the function in `_ASSISTANT_PAGES` in `main.py`. New words (Hindi / Hinglish) go in
`backend/app/assistant/text.py`. Add the questions you expect people to ask, with the expected answer, to
`backend/tests/test_assistant.py`.

## 6. Check and open the PR

```bash
cd backend && python -m pytest -q
cd frontend && npm run typecheck && npm test && npm run build
```

Compare the page with the sheet on real data, then open a PR into `main` (see `CONTRIBUTING.md`).
