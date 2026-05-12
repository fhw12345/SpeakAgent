"""Thin LLM message-based wrapper used by the realtime coach.

Wraps `server.llm.call_with_fallback` and adds an `LLM_MOCK` deterministic
mode for tests. When `LLM_MOCK=1` is set, `generate()` returns scripted
responses from a per-process queue, falling back to a default canned reply.
"""
from __future__ import annotations

import os
from collections import deque
from typing import Deque, Iterable, List

from server.llm import call_with_fallback
from server.logging_setup import get_logger

_log = get_logger("llm_client")

_MOCK_QUEUE: Deque[str] = deque()
_DEFAULT_MOCK_TEMPLATES = [
    "Sure — tell me more about that.",
    "Nice. Can you use the word 'tool' in a sentence?",
    "Good. Now describe an API you've used.",
    "Great answer. What does the function return?",
    "Got it. Let's try one more — what's a parameter?",
    "Excellent. We've covered the basics today.",
]
_default_mock_idx = 0


def llm_mock_enabled() -> bool:
    return os.environ.get("LLM_MOCK", "").lower() in ("1", "true", "yes")


if llm_mock_enabled():
    _log.warning(
        "llm_mock_enabled",
        msg="LLM_MOCK is active — generate() returns canned replies, not live LLM output. "
            "Unset LLM_MOCK in production environments.",
    )


def set_mock_responses(responses: Iterable[str]) -> None:
    """Replace the mock queue with the given canned responses (in order)."""
    _MOCK_QUEUE.clear()
    _MOCK_QUEUE.extend(responses)


def push_mock_response(response: str) -> None:
    _MOCK_QUEUE.append(response)


def clear_mock_responses() -> None:
    global _default_mock_idx
    _MOCK_QUEUE.clear()
    _default_mock_idx = 0


def generate(messages: List[dict], max_tokens: int = 256) -> str:
    """Generate a single text completion from a list of {role, content} messages.

    System messages are concatenated and passed as the system prompt.
    User/assistant messages are flattened into a single user turn (the
    underlying `call_with_fallback` is single-shot).
    """
    global _default_mock_idx
    if llm_mock_enabled():
        if _MOCK_QUEUE:
            return _MOCK_QUEUE.popleft()
        reply = _DEFAULT_MOCK_TEMPLATES[_default_mock_idx % len(_DEFAULT_MOCK_TEMPLATES)]
        _default_mock_idx += 1
        return reply

    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    convo_parts: List[str] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            continue
        prefix = "User" if role == "user" else "Coach"
        convo_parts.append(f"{prefix}: {m.get('content', '')}")
    system = "\n\n".join(system_parts) if system_parts else "You are a helpful English speaking coach."
    prompt = "\n".join(convo_parts) if convo_parts else "Begin the lesson."
    return call_with_fallback(prompt, system=system)
