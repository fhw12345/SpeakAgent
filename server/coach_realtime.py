"""Realtime (LLM-driven) coach turn generator.

Conversation history + lesson context are sent to the LLM each turn.
Sessions live in an in-process dict with a 30-minute idle TTL.
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

MAX_USER_TURNS = 6
END_SENTINEL = "[[END_LESSON]]"
SESSION_TTL_S = 30 * 60

SYSTEM_TEMPLATE = (
    "{persona}\n\n"
    "Lesson topic: {topic}\n"
    "Target phrases the learner should practice:\n{phrases}\n"
    "Vocabulary to weave in naturally:\n{vocab}\n\n"
    "Reply with one short coach turn (no more than 2 sentences). "
    "Stay on topic. Ask one question at a time. "
    f"Emit `{END_SENTINEL}` (alone or at the end of your reply) when the "
    "objectives have been comfortably covered."
)


@dataclass
class _Session:
    session_id: str
    lesson: LessonSpec
    history: List[dict] = field(default_factory=list)
    user_turn_count: int = 0
    done: bool = False
    last_activity: float = field(default_factory=time.time)


_SESSIONS: Dict[str, _Session] = {}


def _evict_expired(now: float | None = None) -> None:
    cutoff = (now or time.time()) - SESSION_TTL_S
    stale = [sid for sid, s in _SESSIONS.items() if s.last_activity < cutoff]
    for sid in stale:
        _SESSIONS.pop(sid, None)


def _build_system_prompt(lesson: LessonSpec) -> str:
    phrases = "\n".join(f"- {p}" for p in (lesson.target_phrases or []))
    vocab = ", ".join(lesson.vocabulary or [])
    return SYSTEM_TEMPLATE.format(
        persona=(lesson.coach_persona or "").strip(),
        topic=lesson.topic or "",
        phrases=phrases,
        vocab=vocab,
    )


def start_session(lesson: LessonSpec) -> tuple[str, str]:
    """Create a new realtime session and return (session_id, first_agent_utterance)."""
    if lesson.mode != "realtime":
        raise ValueError(f"start_session called on non-realtime lesson: {lesson.mode}")

    _evict_expired()
    session_id = uuid.uuid4().hex
    sess = _Session(session_id=session_id, lesson=lesson)
    system = _build_system_prompt(lesson)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "(Begin the lesson — greet the learner and ask your first question.)"},
    ]
    utterance = generate(messages).strip()
    done = END_SENTINEL in utterance
    if done:
        utterance = utterance.replace(END_SENTINEL, "").strip()
        sess.done = True
    sess.history.append({"role": "assistant", "content": utterance})
    _SESSIONS[session_id] = sess
    return session_id, utterance


def handle_turn(session_id: str, user_text: str) -> dict:
    """Process one user turn and return {agent_utterance, turn_index, done}."""
    _evict_expired()
    if session_id not in _SESSIONS:
        raise KeyError(f"unknown session_id: {session_id}")
    sess = _SESSIONS[session_id]
    sess.last_activity = time.time()

    if sess.done:
        return {"agent_utterance": "", "turn_index": sess.user_turn_count, "done": True}

    sess.user_turn_count += 1
    sess.history.append({"role": "user", "content": user_text})

    system = _build_system_prompt(sess.lesson)
    messages = [{"role": "system", "content": system}] + list(sess.history)
    utterance = generate(messages).strip()

    done = sess.user_turn_count >= MAX_USER_TURNS or END_SENTINEL in utterance
    if END_SENTINEL in utterance:
        utterance = utterance.replace(END_SENTINEL, "").strip()
    sess.history.append({"role": "assistant", "content": utterance})
    sess.done = done

    return {
        "agent_utterance": utterance,
        "turn_index": sess.user_turn_count,
        "done": done,
    }


def reset_sessions_for_test() -> None:
    """Test helper — wipe in-memory session store."""
    _SESSIONS.clear()
