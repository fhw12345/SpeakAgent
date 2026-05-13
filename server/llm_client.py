"""LLM client wrapper exposing a `generate(messages, max_tokens)` API.

Thin layer over `server.llm.ClaudeAssistant` (with GPT fallback). Honors
`LLM_MOCK=1` env var which returns a deterministic canned sequence — used
by tests so realtime coach behavior is reproducible.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

from server.llm import ClaudeAssistant, GptAssistant, GRACEFUL_ERROR
from server.logging_setup import get_logger

_log = get_logger("llm_client")

_MOCK_SEQUENCE: List[str] = [
    "Welcome! Today we'll talk about tools and APIs. Can you tell me what an API is?",
    "Good. An API lets two programs talk to each other. What tool have you used recently?",
    "Nice example. Why do you think APIs need authentication?",
    "Right. How would you describe REST in one sentence?",
    "Great. When would you use a webhook instead of polling?",
    "Excellent work today. [[END_LESSON]]",
]
_mock_idx = 0


def _reset_mock() -> None:
    global _mock_idx
    _mock_idx = 0


def _next_mock() -> str:
    global _mock_idx
    out = _MOCK_SEQUENCE[_mock_idx % len(_MOCK_SEQUENCE)]
    _mock_idx += 1
    return out


def generate(messages: List[Dict], max_tokens: int = 256) -> str:
    """Generate one assistant turn from a chat-style `messages` list.

    `messages[0]` may be a `{role:"system", content:str}` system prompt;
    remaining items are `{role:"user"|"assistant", content:str}`.
    Returns a non-empty string (graceful error on total failure).
    """
    if os.environ.get("LLM_MOCK") == "1":
        return _next_mock()

    system = "You are a helpful English speaking coach."
    convo: List[Dict] = []
    for m in messages:
        role = m.get("role")
        content = str(m.get("content", ""))
        if role == "system":
            system = content
        elif role in ("user", "assistant"):
            convo.append({"role": role, "content": content})

    rendered = "\n\n".join(f"{m['role'].upper()}: {m['content']}" for m in convo) or " "

    try:
        out = ClaudeAssistant()._call(rendered, system=system)
        if out:
            return out
    except Exception as e:
        _log.error("claude_unexpected", error=str(e))

    try:
        out = GptAssistant()._call(rendered, system=system)
        if out:
            return out
    except Exception as e:
        _log.error("gpt_unexpected", error=str(e))

    _log.error("llm_all_backends_failed")
    return GRACEFUL_ERROR
