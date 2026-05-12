"""Realtime coach: LLM-driven turn generation for `mode: realtime` lessons.

The LLM produces each agent utterance from (lesson context + conversation history).
Sessions live in an in-process dict with TTL eviction.
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Dict, List, Tuple

from server.lesson import LessonPlan
from server.llm import call_with_fallback
from server.logging_setup import get_logger


_log = get_logger("coach_realtime")

MAX_USER_TURNS = 6
END_SENTINEL = "[[END_LESSON]]"
SESSION_TTL_S = 30 * 60

SYSTEM_TEMPLATE = (
    "{persona}\n\n"
    "Lesson topic: {topic}\n"
    "Target phrases the learner should practice (weave them in naturally):\n"
    "{target_phrases}\n"
    "Useful vocabulary: {vocabulary}\n\n"
    "Reply with one short coach turn (no more than 2 sentences). "
    "Ask at most one question per turn. "
    f"Emit `{END_SENTINEL}` at the end of your reply when the lesson objectives are covered."
)


def _build_system_prompt(lesson: LessonPlan) -> str:
    phrases = "\n".join(f"- {p}" for p in lesson.target_phrases)
    vocab = ", ".join(lesson.vocabulary)
    return SYSTEM_TEMPLATE.format(
        persona=(lesson.coach_persona or "").strip(),
        topic=lesson.topic or "",
        target_phrases=phrases,
        vocabulary=vocab,
    )


def _format_history_as_prompt(history: List[Dict[str, str]]) -> str:
    """Render history (user/assistant turns) as a single user-prompt string.

    The underlying LLM client only exposes a single user-message + system slot,
    so we serialize the dialogue and ask for the next coach reply.
    """
    if not history:
        return "Begin the lesson with a short, friendly opener that introduces the topic."
    lines = []
    for msg in history:
        role = "Learner" if msg["role"] == "user" else "Coach"
        lines.append(f"{role}: {msg['content']}")
    lines.append("Coach:")
    return "\n".join(lines)


_SESSIONS: Dict[str, Dict] = {}


def _evict_expired(now: float | None = None) -> None:
    now = now if now is not None else time.time()
    expired = [sid for sid, s in _SESSIONS.items() if now - s["created_at"] > SESSION_TTL_S]
    for sid in expired:
        _SESSIONS.pop(sid, None)


def _generate_agent_utterance(lesson: LessonPlan, history: List[Dict[str, str]]) -> str:
    """Call the LLM (or a mock) to produce the next coach turn."""
    if os.environ.get("LLM_MOCK") == "1":
        return _mock_utterance(lesson, history)
    system = _build_system_prompt(lesson)
    prompt = _format_history_as_prompt(history)
    out = call_with_fallback(prompt=prompt, system=system)
    return (out or "").strip() or "Let's keep practicing. Tell me about a tool you've used."


def _mock_utterance(lesson: LessonPlan, history: List[Dict[str, str]]) -> str:
    """Deterministic canned coach turns for tests / e2e (LLM_MOCK=1)."""
    user_turns = sum(1 for m in history if m["role"] == "user")
    canned = [
        f"Welcome! Today we'll talk about {lesson.topic}. What is a tool, in your own words?",
        "Nice. An API is how two programs talk to each other. Can you give me one example?",
        "Great example. The model decides which tool to use. Why is that important?",
        "Good thinking. If an API returns an error, what should the agent do?",
        "Right. A good tool has a clear name and a short description. Why does that help?",
        f"Perfect. You covered the key ideas. {END_SENTINEL}",
    ]
    idx = min(user_turns, len(canned) - 1)
    return canned[idx]


def start_session(lesson: LessonPlan) -> Tuple[str, str]:
    """Create a session for a realtime lesson and return (session_id, first_utterance)."""
    if lesson.mode != "realtime":
        raise ValueError(f"start_session requires realtime lesson, got mode={lesson.mode}")
    _evict_expired()
    session_id = uuid.uuid4().hex
    history: List[Dict[str, str]] = []
    first = _generate_agent_utterance(lesson, history)
    history.append({"role": "assistant", "content": first})
    _SESSIONS[session_id] = {
        "lesson": lesson,
        "history": history,
        "user_turn_count": 0,
        "done": END_SENTINEL in first,
        "created_at": time.time(),
    }
    _log.info("realtime_session_start", session_id=session_id, lesson_id=lesson.id)
    return session_id, first


def handle_turn(session_id: str, user_text: str) -> Dict:
    """Append a user turn, generate the next agent utterance, return turn payload."""
    if session_id not in _SESSIONS:
        raise KeyError(session_id)
    state = _SESSIONS[session_id]
    if state["done"]:
        return {
            "agent_utterance": "",
            "turn_index": state["user_turn_count"],
            "done": True,
        }
    state["history"].append({"role": "user", "content": user_text})
    state["user_turn_count"] += 1
    turn_index = state["user_turn_count"]

    agent_utterance = _generate_agent_utterance(state["lesson"], state["history"])
    state["history"].append({"role": "assistant", "content": agent_utterance})

    done = (turn_index >= MAX_USER_TURNS) or (END_SENTINEL in agent_utterance)
    state["done"] = done
    _log.info("realtime_turn", session_id=session_id, turn_index=turn_index, done=done)
    return {
        "agent_utterance": agent_utterance,
        "turn_index": turn_index,
        "done": done,
    }


def _reset_sessions_for_test() -> None:
    """Test helper — wipe in-process session store."""
    _SESSIONS.clear()
