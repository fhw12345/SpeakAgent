"""Realtime coach: LLM-driven turn generator (Phase 2 of conversational coach upgrade).

Still turn-based (no token streaming yet, that is Phase 3). Each call to
`handle_turn` appends the user message to history, asks the LLM for the
next short coach utterance, and returns it.

Sessions are stored in-process with TTL eviction (default 30 minutes).
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List

from server.lesson_loader import LessonSpec
from server.llm_client import generate
from server.logging_setup import get_logger

_log = get_logger("coach_realtime")

MAX_USER_TURNS: int = 6
END_SENTINEL: str = "[[END_LESSON]]"
_SESSION_TTL_S: float = 30 * 60.0

SYSTEM_TEMPLATE = (
    "You are {persona}. You are coaching a Chinese learner of English on the topic: {topic}.\n"
    "Target phrases the learner should use: {phrases}.\n"
    "Vocabulary in scope: {vocab}.\n"
    "Reply with one short coach turn (one or two sentences max). Ask a question or give a short prompt.\n"
    "When the learner has practiced the target phrases and you are satisfied, end your reply with the literal sentinel "
    f"`{END_SENTINEL}`."
)


@dataclass
class _RealtimeSession:
    id: str
    lesson: LessonSpec
    history: List[Dict] = field(default_factory=list)
    user_turns: int = 0
    created_at: float = field(default_factory=time.time)
    done: bool = False


_SESSIONS: Dict[str, _RealtimeSession] = {}


def _evict_expired(now: float | None = None) -> None:
    now = now or time.time()
    expired = [sid for sid, s in _SESSIONS.items() if now - s.created_at > _SESSION_TTL_S]
    for sid in expired:
        _SESSIONS.pop(sid, None)


def _build_system_prompt(lesson: LessonSpec) -> str:
    return SYSTEM_TEMPLATE.format(
        persona=lesson.coach_persona or "a friendly English speaking coach",
        topic=lesson.topic or "general conversation",
        phrases="; ".join(lesson.target_phrases or []),
        vocab=", ".join(lesson.vocabulary or []),
    )


def _strip_sentinel(text: str) -> tuple[str, bool]:
    if END_SENTINEL in text:
        return text.replace(END_SENTINEL, "").strip(), True
    return text.strip(), False


def start_session(lesson: LessonSpec) -> tuple[str, str]:
    """Begin a realtime session. Returns `(session_id, first_agent_utterance)`."""
    if lesson.mode != "realtime":
        raise ValueError(f"start_session requires a realtime lesson, got mode={lesson.mode!r}")
    _evict_expired()

    sid = uuid.uuid4().hex[:12]
    sess = _RealtimeSession(id=sid, lesson=lesson)
    system = _build_system_prompt(lesson)
    sess.history.append({"role": "system", "content": system})

    kickoff = (
        "Greet the learner briefly and pose your first short question to start practicing the topic."
    )
    sess.history.append({"role": "user", "content": kickoff})
    raw = generate(sess.history, max_tokens=256)
    text, ended = _strip_sentinel(raw)

    sess.history.pop()  # drop synthetic kickoff so subsequent history is clean
    sess.history.append({"role": "assistant", "content": text})
    if ended:
        _log.warning("realtime_sentinel_on_kickoff_ignored", lesson_id=lesson.lesson_id)
    sess.done = False

    _SESSIONS[sid] = sess
    return sid, text


def handle_turn(session_id: str, user_text: str) -> dict:
    """Process one user turn. Returns `{agent_utterance, turn_index, done}`."""
    if session_id not in _SESSIONS:
        raise KeyError(session_id)
    sess = _SESSIONS[session_id]
    if sess.done:
        return {"agent_utterance": "", "turn_index": sess.user_turns, "done": True}

    sess.user_turns += 1
    sess.history.append({"role": "user", "content": user_text})

    raw = generate(sess.history, max_tokens=256)
    text, ended = _strip_sentinel(raw)
    sess.history.append({"role": "assistant", "content": text})

    if ended or sess.user_turns >= MAX_USER_TURNS:
        sess.done = True

    return {
        "agent_utterance": text,
        "turn_index": sess.user_turns,
        "done": sess.done,
    }


def _reset_for_tests() -> None:
    """Test helper — clear all in-memory sessions."""
    _SESSIONS.clear()
