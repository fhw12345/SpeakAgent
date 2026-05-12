"""Realtime (LLM-driven) lesson coach.

Turn-based: each user message triggers a single LLM call to produce the next
agent utterance, given lesson context + conversation history. No streaming.
Sessions are kept in an in-process dict with TTL eviction.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from server.lesson_loader import LessonSpec
from server.llm_client import generate
from server.logging_setup import get_logger

_log = get_logger("coach_realtime")

MAX_USER_TURNS = 6
END_SENTINEL = "[[END_LESSON]]"
_SESSION_TTL_S = 30 * 60

SYSTEM_TEMPLATE = (
    "You are {persona}.\n"
    "Today's topic: {topic}.\n"
    "Target phrases the learner should practice: {phrases}.\n"
    "Vocabulary to weave in: {vocab}.\n"
    "Reply with one short coach turn (<=2 sentences). "
    "Ask a focused question or give brief feedback. "
    f"Emit `{END_SENTINEL}` at the end of your message when objectives are covered."
)


@dataclass
class _Session:
    id: str
    lesson: LessonSpec
    history: list[dict] = field(default_factory=list)  # {role, content}
    user_turn_count: int = 0
    done: bool = False
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)


_SESSIONS: dict[str, _Session] = {}


def _evict_stale(now: Optional[float] = None) -> None:
    now = now or time.time()
    stale = [sid for sid, s in _SESSIONS.items() if now - s.last_activity > _SESSION_TTL_S]
    for sid in stale:
        _SESSIONS.pop(sid, None)


def _build_system(lesson: LessonSpec) -> str:
    return SYSTEM_TEMPLATE.format(
        persona=lesson.coach_persona or "a friendly English speaking coach",
        topic=lesson.topic or "general conversation",
        phrases="; ".join(lesson.target_phrases) or "(none specified)",
        vocab=", ".join(lesson.vocabulary) or "(none specified)",
    )


def _strip_sentinel(text: str) -> tuple[str, bool]:
    if END_SENTINEL in text:
        return text.replace(END_SENTINEL, "").strip(), True
    return text.strip(), False


def start_session(lesson: LessonSpec) -> tuple[str, str]:
    """Open a realtime session. Returns (session_id, first_agent_utterance)."""
    if lesson.mode != "realtime":
        raise ValueError(f"start_session requires realtime lesson, got mode={lesson.mode!r}")
    _evict_stale()
    sid = uuid.uuid4().hex[:12]
    sess = _Session(id=sid, lesson=lesson)
    system = _build_system(lesson)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "Begin the lesson. Greet the learner and ask the first question."},
    ]
    raw = generate(messages, max_tokens=256)
    text, done = _strip_sentinel(raw or "Hello! Let's get started.")
    sess.history.append({"role": "assistant", "content": text})
    sess.done = done
    _SESSIONS[sid] = sess
    return sid, text


def handle_turn(session_id: str, user_text: str) -> dict:
    """Process one user utterance, return the next agent reply."""
    if session_id not in _SESSIONS:
        raise KeyError(f"unknown session: {session_id}")
    sess = _SESSIONS[session_id]
    sess.last_activity = time.time()
    if sess.done:
        return {"agent_utterance": "", "turn_index": sess.user_turn_count, "done": True}

    sess.history.append({"role": "user", "content": user_text})
    sess.user_turn_count += 1

    system = _build_system(sess.lesson)
    messages = [{"role": "system", "content": system}] + sess.history
    raw = generate(messages, max_tokens=256)
    text, sentinel = _strip_sentinel(raw or "")
    sess.history.append({"role": "assistant", "content": text})

    done = sentinel or sess.user_turn_count >= MAX_USER_TURNS
    sess.done = done
    return {
        "agent_utterance": text,
        "turn_index": sess.user_turn_count,
        "done": done,
    }


def get_session(session_id: str) -> Optional[_Session]:
    return _SESSIONS.get(session_id)


def reset_sessions() -> None:
    """Test helper."""
    _SESSIONS.clear()
