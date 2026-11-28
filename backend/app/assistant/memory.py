"""Per-chat memory for the assistant.

Each browser chat gets a random session id. The last few questions and answers of that chat are kept here so the
assistant can follow the conversation. Everything lives in this process's memory only: restarting the API clears
it ("reset on reboot"), and a chat that has been idle for SESSION_TTL seconds is forgotten.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque

MAX_TURNS = 8            # question/answer pairs kept per chat
MAX_SESSIONS = 500       # oldest chats are dropped beyond this
SESSION_TTL = 6 * 3600   # idle chats are forgotten after 6 hours


class ChatMemory:
    def __init__(self, max_turns: int = MAX_TURNS, max_sessions: int = MAX_SESSIONS, ttl: int = SESSION_TTL):
        self.max_turns, self.max_sessions, self.ttl = max_turns, max_sessions, ttl
        self._data: "OrderedDict[str, tuple[float, deque]]" = OrderedDict()
        self._lock = threading.Lock()

    def _prune(self, now: float):
        for sid in [s for s, (seen, _) in self._data.items() if now - seen > self.ttl]:
            del self._data[sid]
        while len(self._data) > self.max_sessions:
            self._data.popitem(last=False)

    def history(self, sid: str | None) -> list[tuple[str, str]]:
        if not sid:
            return []
        with self._lock:
            hit = self._data.get(sid)
            return list(hit[1]) if hit else []

    def add(self, sid: str | None, question: str, answer: str):
        if not sid:
            return
        now = time.time()
        with self._lock:
            _, turns = self._data.pop(sid, (now, deque(maxlen=self.max_turns)))
            turns.append((question[:500], answer[:1200]))
            self._data[sid] = (now, turns)
            self._prune(now)

    def clear(self, sid: str | None):
        with self._lock:
            self._data.pop(sid or "", None)

    def __len__(self):
        return len(self._data)


class AnswerCache:
    """Answers to questions asked before, for the same data version: the same question gives the same answer
    instantly and costs no Gemini call. Only questions asked without earlier context are cached (a follow-up
    depends on its chat). Lives in this process only."""

    def __init__(self, ttl: int = 900, max_items: int = 500):
        self.ttl, self.max_items = ttl, max_items
        self._data: "OrderedDict[tuple, tuple[float, dict]]" = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def key(question: str, context: dict | None, version: str) -> tuple:
        q = " ".join(question.lower().split()).strip(" ?!.")
        page = (context or {}).get("page") or ""
        return (q, page, version)

    def get(self, key: tuple) -> dict | None:
        now = time.time()
        with self._lock:
            hit = self._data.get(key)
            if not hit or now - hit[0] > self.ttl:
                return None
            self._data.move_to_end(key)
            return dict(hit[1])

    def put(self, key: tuple, value: dict):
        with self._lock:
            self._data[key] = (time.time(), dict(value))
            self._data.move_to_end(key)
            while len(self._data) > self.max_items:
                self._data.popitem(last=False)

    def clear(self):
        with self._lock:
            self._data.clear()
