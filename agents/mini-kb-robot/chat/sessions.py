"""Minimal in-memory conversation state.

No database: a process-local dict is enough at this traffic scale, and the
only multi-turn requirement is "bot asks a clarifying question, user answers,
bot resolves" - which the LLM's own conversational memory handles once we
replay the history, so this layer stays deliberately dumb.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

MAX_HISTORY_MESSAGES = 20
SESSION_TTL_SECONDS = 30 * 60


@dataclass
class SessionState:
    history: list[dict] = field(default_factory=list)
    last_touched: float = field(default_factory=time.time)


_SESSIONS: dict[str, SessionState] = {}


def _evict_stale() -> None:
    now = time.time()
    stale = [sid for sid, s in _SESSIONS.items() if now - s.last_touched > SESSION_TTL_SECONDS]
    for sid in stale:
        del _SESSIONS[sid]


def get_or_create(session_id: str | None) -> tuple[str, SessionState]:
    _evict_stale()
    if session_id and session_id in _SESSIONS:
        return session_id, _SESSIONS[session_id]
    new_id = session_id or str(uuid.uuid4())
    state = SessionState()
    _SESSIONS[new_id] = state
    return new_id, state


def append_turn(state: SessionState, new_messages: list[dict]) -> None:
    state.history.extend(new_messages)
    if len(state.history) > MAX_HISTORY_MESSAGES:
        # Simple tail-slice; a truncation could in principle land mid tool-call/
        # tool-result pair. Not worth guarding against at this session length
        # (MAX_HISTORY_MESSAGES covers ~10 exchanges, well past the 1-2 rounds
        # a clarification flow actually needs).
        state.history = state.history[-MAX_HISTORY_MESSAGES:]
    state.last_touched = time.time()
