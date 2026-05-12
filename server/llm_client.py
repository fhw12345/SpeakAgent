"""Thin chat-style wrapper over server.llm.

`generate(messages, max_tokens)` accepts an OpenAI/Anthropic-style message list
[{"role": "system"|"user"|"assistant", "content": str}, ...] and returns the
assistant text via the configured backend (Claude gateway -> Azure GPT
fallback). Honors the LLM_MOCK env var: when set to "1", returns deterministic
canned responses for tests/e2e.
"""
from __future__ import annotations

import json
import os
from typing import Iterable

from server.llm import call_with_fallback
from server.logging_setup import get_logger

_log = get_logger("llm_client")

_MOCK_REPLIES = [
    "Great, let's start. What's an API?",
    "Nice. Can you give an example of a tool an agent might call?",
    "Good. How does the agent know which tool to use?",
    "Right. What happens if the tool fails?",
    "Makes sense. How do you keep the agent from looping forever?",
    "Excellent — last one: why are clear schemas important for tools?",
    "Perfect. [[END_LESSON]]",
]


def _mock_generate(messages: list[dict]) -> str:
    # The first user message is the synthetic "Begin the lesson..." opener
    # injected by coach_realtime.start_session; subtract it so index 0 maps
    # to the opener reply and subsequent indices map to real user turns.
    user_turns = sum(1 for m in messages if m.get("role") == "user")
    idx = max(0, min(user_turns - 1, len(_MOCK_REPLIES) - 1))
    return _MOCK_REPLIES[idx]


def _flatten(messages: Iterable[dict]) -> tuple[str, str]:
    """Split messages into (system, user_prompt) for the urllib-based client.

    The transcript is folded into a single prompt with role-tagged lines so the
    backend (which only takes system + user) sees the conversation history.
    """
    system_parts: list[str] = []
    body_lines: list[str] = []
    for m in messages:
        role = m.get("role", "user")
        content = str(m.get("content", ""))
        if role == "system":
            system_parts.append(content)
        else:
            body_lines.append(f"{role.upper()}: {content}")
    system = "\n\n".join(system_parts) if system_parts else "You are a helpful English speaking coach."
    body_lines.append("ASSISTANT:")
    return system, "\n".join(body_lines)


def generate(messages: list[dict], max_tokens: int = 256) -> str:
    if os.environ.get("LLM_MOCK") == "1":
        return _truncate(_mock_generate(messages), max_tokens)
    system, prompt = _flatten(messages)
    try:
        return _truncate(call_with_fallback(prompt, system=system).strip(), max_tokens)
    except Exception as e:
        _log.error("generate_failed", error=str(e))
        return ""


def _truncate(text: str, max_tokens: int) -> str:
    """Approximate token cap (~4 chars/token) applied at the boundary.

    The underlying clients use a fixed model-side max; this client-side cap
    enforces the realtime "<=2 sentences" constraint when the model overshoots.
    """
    if max_tokens <= 0:
        return text
    char_budget = max_tokens * 4
    if len(text) <= char_budget:
        return text
    cut = text[:char_budget].rsplit(" ", 1)[0]
    return cut.rstrip() + "..."
