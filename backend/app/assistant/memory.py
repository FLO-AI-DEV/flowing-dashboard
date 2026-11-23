"""Per-chat memory for the assistant.

Each browser chat gets a random session id. The last few questions and answers of that chat are kept here so the
assistant can follow the conversation. Everything lives in this process's memory only: restarting the API clears
it ("reset on reboot"), and a chat that has been idle for SESSION_TTL seconds is forgotten.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from copy import deepcopy

MAX_TURNS = 10           # question/answer pairs kept per chat
MAX_SESSIONS = 500       # oldest chats are dropped beyond this
SESSION_TTL = 6 * 3600   # idle chats are forgotten after 6 hours


class ChatMemory:
    def __init__(self, max_turns: int = MAX_TURNS, max_sessions: int = MAX_SESSIONS, ttl: int = SESSION_TTL):
        self.max_turns, self.max_sessions, self.ttl = max_turns, max_sessions, ttl
        self._data: OrderedDict[str, tuple[float, deque[tuple[str, str, dict | None]]]] = OrderedDict()
        self._lock = threading.Lock()

    def _prune(self, now: float):
        for sid in [s for s, (seen, _) in self._data.items() if now - seen > self.ttl]:
            del self._data[sid]
        while len(self._data) > self.max_sessions:
            self._data.popitem(last=False)

    def history(self, sid: str | None) -> list[tuple[str, str]]:
        return self.recall(sid)[0]

    def recall(self, sid: str | None) -> tuple[list[tuple[str, str]], dict | None]:
        if not sid:
            return [], None
        with self._lock:
            hit = self._data.get(sid)
            if hit is None:
                return [], None
            seen, turns = hit
            if time.time() - seen > self.ttl:
                del self._data[sid]
                return [], None
            history = [(question, answer) for question, answer, _ in turns]
            for question, answer, context in reversed(turns):
                if context:
                    context = deepcopy(context)
                    context.setdefault("question", question)
                    context.setdefault("answer", answer)
                    return history, context
            return history, None

    def add(self, sid: str | None, question: str, answer: str, context: dict | None = None):
        if not sid:
            return
        now = time.time()
        with self._lock:
            seen, turns = self._data.pop(sid, (now, deque(maxlen=self.max_turns)))
            if now - seen > self.ttl:
                turns.clear()
            turns.append((question[:500], answer[:1200], deepcopy(context)))
            self._data[sid] = (now, turns)
            self._prune(now)

    def clear(self, sid: str | None):
        with self._lock:
            self._data.pop(sid or "", None)

    def __len__(self):
        return len(self._data)
