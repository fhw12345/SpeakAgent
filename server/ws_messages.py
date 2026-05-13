"""WebSocket message types and serializers (server -> client JSON)."""
from typing import Any


def session_start(session_id: str, lesson: str) -> dict[str, Any]:
    return {"type": "session_start", "session_id": session_id, "lesson": lesson}


def agent_caption(text: str, voice: str, gloss: list, translation: str) -> dict[str, Any]:
    return {
        "type": "agent_caption",
        "text": text,
        "voice": voice,
        "gloss": gloss,
        "translation": translation,
    }


def agent_partial_text(text: str, index: int) -> dict[str, Any]:
    return {"type": "agent_partial_text", "text": text, "index": index}


def agent_audio(b64: str, index: int) -> dict[str, Any]:
    return {"type": "agent_audio", "b64": b64, "index": index}


def agent_done(full_text: str = "") -> dict[str, Any]:
    return {"type": "agent_done", "full_text": full_text}


def agent_error(detail: str, index: int | None = None) -> dict[str, Any]:
    return {"type": "agent_error", "detail": detail, "index": index}
