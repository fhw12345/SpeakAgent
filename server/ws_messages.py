"""Pure dict builders for streaming-related WS server->client messages."""
from typing import Optional


def agent_partial_text(text: str, index: int) -> dict:
    return {"type": "agent_partial_text", "text": text, "index": index}


def agent_audio_b64(b64: str, index: int) -> dict:
    return {"type": "agent_audio", "b64": b64, "index": index}


def agent_done(full_text: str = "") -> dict:
    return {"type": "agent_done", "full_text": full_text}


def agent_error(detail: str, index: Optional[int] = None) -> dict:
    return {"type": "agent_error", "detail": detail, "index": index}
