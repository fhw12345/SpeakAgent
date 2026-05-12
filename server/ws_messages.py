"""WebSocket message helpers for the streaming agent path."""
from __future__ import annotations

import base64
from typing import Any


def agent_partial_text(text: str, index: int) -> dict[str, Any]:
    return {"type": "agent_partial_text", "text": text, "index": int(index)}


def agent_audio_b64(audio: bytes, index: int) -> dict[str, Any]:
    return {
        "type": "agent_audio",
        "b64": base64.b64encode(audio).decode("ascii"),
        "index": int(index),
    }


def agent_done(full_text: str) -> dict[str, Any]:
    return {"type": "agent_done", "full_text": full_text}


def agent_error(detail: str, index: int | None = None) -> dict[str, Any]:
    return {"type": "agent_error", "detail": detail, "index": index}
