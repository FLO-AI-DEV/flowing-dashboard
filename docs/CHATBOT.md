# Flo-Wing Assistant (chatbot)

The robot in the bottom-right corner of every page. It answers questions about anything in the four sheets
(figures, particular suppliers, POs, bills, enquiries, any tab) and what the words mean, in English, Hindi or
Hinglish, and links to the page that shows the figure.

It does not "memorise" data and is not trained on it. The backend keeps the latest copy of every sheet in memory
(re-read every minute) and the assistant looks the answer up exactly each time, so it always has today's figures.

## How a question is answered (fastest first)

```
question
  1. "PO kya hai", "what does overdue mean"      ──► glossary.py           instant, free
  2. "help", "what needs attention"              ──► quick answers          instant, free
  3. asked before (same data)                    ──► answer cache          instant, free
  4. calculation / particular rows / follow-up   ──► Gemini analyst + data tools (if a key is set)
  5. everything else                             ──► rules engine ──not sure──► Gemini analyst ──► "did you mean…"
```

1. **Glossary** (`glossary.py`). About 80 terms from the dashboard and the sheets (KPI, PO, PO line, pending,
   overdue, on-time %, RCVD %, net payable, ageing, credit days, MSME, GR, LR, debit note, HSN, waiting for PO,
   terms approval, lakh / crore…), with English and Hinglish aliases. "Pending kitna hai" is a figure question, not a
   meaning question, so it goes to the numbers.
2. **Rules** (`engine.py`, `text.py`, `pages.py`). No AI. They learn every KPI label, table column, vendor,
   category, department, city, person and month from the dashboard itself and quote the exact figure the page shows.
3. **Gemini analyst** (`analyst.py`, only with `GEMINI_API_KEY`). Used for calculations, questions about particular
   rows ("kesar ethnic details", "oldest pending enquiry", "which bills of mahavir are overdue"), comparisons,
   loosely worded questions and short follow-ups.
   - Model `GEMINI_MODEL`, default `gemini-flash-lite-latest` (small, low-cost), max 400 output tokens.
   - It gets the page headline figures, a list of every table and column, a short glossary, the last 4 turns of
     this chat, and three tools:

     | Tool | What it does |
     |---|---|
     | `query_table` | Exact filters, totals, counts, averages, group-by and top-N over **every row** (`datatools.py`) |
     | `search_rows` | Finds a name, PO number, design no., phone or words in every row; `scope=all` also reads every other tab of the four sheets |
     | `calculate` | Exact arithmetic (`calc.py`); the model never does sums itself |

     Tables: `po_lines` (Order Status → PO Master), `supplier_bills` (dues list), `vendor_orders` (Order to vendors),
     `enquiries`, `po_by_city`, `terms_approval`, `inactive_suppliers`, `purchase_issues` (Supplier's Enquiry Sheet).
   - **Figure check**: every number in its answer must appear in what the tools / page figures returned (allowing
     for display rounding like ₹14.68 L). If not, it is sent back once to look it up; if it still can't, the answer
     says the figure couldn't be checked.
   - **Time limit**: `ANALYST_DEADLINE` seconds (default 20) for the whole question; after that, or if Google is
     down or out of quota, the rules answer instead. The chat never hangs or breaks.

## Speed

- The rules and glossary answer in well under a second.
- Every sheet is read once at start-up (`WARM_UP`), so the first question doesn't wait for Google.
- The same question on the same data is answered from the cache (15 minutes, in memory).
- Gemini is only called when needed, usually 2-3 short calls per question.

## Chat memory

Each chat window has a random session id (`sessionStorage` in the browser). The API keeps that chat's last 8
question/answer pairs **in memory only** (`memory.py`): restarting the API clears everything, a chat idle for
6 hours is forgotten, and the ↻ button in the chat window starts a fresh chat. Nothing is written to the sheets.

## Settings (`backend/.env`)

| Setting | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | empty | Gemini key. Empty = glossary + rules only. Easiest: `SET GEMINI KEY.bat` |
| `GEMINI_MODEL` | `gemini-flash-lite-latest` | Any Gemini model name; keep a *lite* model to save quota |
| `GEMINI_MODE` | `analyst` | `analyst` (sees figures and can look up rows) or `labels` (sees only labels; no look-ups) |
| `ASSISTANT_GEMINI` | `on` | `off` turns Gemini off without removing the key |
| `ANALYST_DEADLINE` | `20` | Seconds Gemini may take for one question before the rules answer instead |
| `WARM_UP` | `on` | Read every sheet at start-up so the first question is fast |
| `CHAT_LOG` | `on` | Writes question text (no figures) to `backend/chat_questions.log`; `MISSED` = not understood |

`GET /api/health` shows the mode in use, e.g. `"assistant": "rules + gemini analyst (gemini-flash-lite-latest)"`.

## Teaching it

1. Look at `backend/chat_questions.log` for `MISSED` lines (and `GEMINI` lines the rules could answer for free).
2. A new word or meaning: add a `Term` to `glossary.py`. A new way of asking for a figure: `text.py` (`WORDS`,
   `PHRASES`) or page words in `pages.py`. A new sheet / tab: add its table to `build_tables` in `datatools.py`.
3. Add the question to `backend/tests/test_assistant.py` or the bank in `backend/tests/test_chatbot_data.py`.
4. `cd backend && python -m pytest -q` must stay green.
