# Flo-Wing Assistant (chatbot)

The robot in the bottom-right corner of every page. It answers questions about the dashboard's numbers in English,
Hindi or Hinglish, and links to the page that shows the figure.

## How a question is answered

```
question ──► calculation / "why" / "explain"? ──yes──► Gemini analyst (if a key is set)
                 │ no                                        │ no answer
                 ▼                                           ▼
            rules engine (free, exact) ──not sure──► Gemini analyst ──► rules' "did you mean…"
```

1. **Rules** (`backend/app/assistant/engine.py`, `text.py`, `pages.py`). No AI. They learn every KPI label, table
   column, vendor, category, department, city and month from the dashboard itself, read the question (names,
   months, "top 5", "month wise", "in one word"…), and quote the exact figure the page shows. Most questions end
   here and cost nothing.
2. **Gemini analyst** (`analyst.py`, only with `GEMINI_API_KEY`). Used for calculations ("pending kitna percent hai
   ordered ka", "average pending per vendor", "difference between June and July"), loosely worded or misspelt
   questions the rules can't place, and conversational follow-ups.
   - Model: `GEMINI_MODEL`, default `gemini-flash-lite-latest` (small and low-cost), max 400 output tokens.
   - Input: the question, the last 4 turns of **this** chat, and a compact text summary of the dashboard (headline
     figures + top rows of each table, filtered by the vendor / month in the question, capped at ~8,000 characters).
   - Maths is never done by the model: it calls the `calculate` tool (`calc.py`, safe arithmetic only) and uses
     the exact result.
   - Told to answer only from those figures, briefly, in the user's language style, and to say so when the data
     doesn't have the answer.

## Chat memory

Each chat window has a random session id (`sessionStorage` in the browser). The API keeps that chat's last 8
question/answer pairs **in memory only** (`memory.py`): restarting the API clears everything, a chat idle for
6 hours is forgotten, and the ↻ button in the chat window starts a fresh chat. Nothing is written to the sheets.

## Settings (`backend/.env`)

| Setting | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | empty | Gemini key. Empty = rules only. Easiest: `SET GEMINI KEY.bat` |
| `GEMINI_MODEL` | `gemini-flash-lite-latest` | Any Gemini model name; keep a *lite* model to save quota |
| `GEMINI_MODE` | `analyst` | `analyst` (sees a summary of the figures) or `labels` (sees only labels; no calculations) |
| `ASSISTANT_GEMINI` | `on` | `off` turns Gemini off without removing the key |
| `CHAT_LOG` | `on` | Writes question text (no figures) to `backend/chat_questions.log`; `MISSED` = not understood |

`GET /api/health` shows the mode in use, e.g. `"assistant": "rules + gemini analyst (gemini-flash-lite-latest)"`.

## Teaching it

1. Look at `backend/chat_questions.log` for `MISSED` lines (and `GEMINI` lines that the rules should handle for free).
2. Add words / phrases to `text.py` (`WORDS`, `PHRASES`), or page words to `pages.py`.
3. Add the question and the words a correct answer contains to `backend/tests/test_assistant.py`.
4. `cd backend && python -m pytest -q` must stay green.
