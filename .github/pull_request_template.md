## What this changes

<!-- One or two lines. Which sheet / page / feature? -->

## Sheet(s) touched

- [ ] Order Status (PO Master)
- [ ] DUES PAYMENT SUPPLIERS
- [ ] Order to vendors
- [ ] New sheet: <!-- name + ID, and it is shared with the service account as Viewer -->

## Checks

- [ ] `cd backend && python -m pytest -q` passes
- [ ] `cd frontend && npm run typecheck && npm test && npm run build` passes
- [ ] Tested on the real sheets (`/api/health` shows `"source": "google"`) — numbers match the sheet
- [ ] No keys, `.env` or `service-account.json` in the diff
- [ ] New chatbot words / questions added to `backend/tests/test_assistant.py` (if the chatbot changed)

## Screenshots

<!-- Before / after of the page, light and dark if the UI changed -->
