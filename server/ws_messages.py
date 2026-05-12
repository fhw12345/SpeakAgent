"""WebSocket message types for /ws/session.

Server -> client JSON envelopes. The serializers return plain dicts so they
can be passed straight to `WebSocket.send_json`.

This module is the schema source of truth for streaming-related messages
introduced in Phase 3, plus serializers for the existing AgentAudio,
AgentDone, and AgentError shapes already used in coach turns.
"""
from __future__ import annotations

import base64
from typing import Any


def agent_partial_text(sentence: str, index: int) -> dict[str, Any]:
    return {"type": "agent_partial_text", "text": sentence, "index": index}


def agent_audio(audio_bytes: bytes, index: int) -> dict[str, Any]:
    return {
        "type": "agent_audio",
        "b64": base64.b64encode(audio_bytes).decode("ascii"),
        "index": index,
    }


def agent_done(full_text: str) -> dict[str, Any]:
    return {"type": "agent_done", "full_text": full_text}


def agent_error(detail: str, index: int | None = None) -> dict[str, Any]:
    return {"type": "agent_error", "detail": detail, "index": index}
