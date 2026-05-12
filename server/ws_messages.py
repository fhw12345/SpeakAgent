"""WS message constructors for the coach session protocol.

Centralizes JSON-serializable shapes so server and tests share one source
of truth. Binary `agent_audio` frames remain raw bytes on the WS — only
JSON message constructors live here.
"""
from __future__ import annotations

from typing import Any, Optional


def session_start(session_id: str, lesson: str) -> dict:
    return {"type": "session_start", "session_id": session_id, "lesson": lesson}


def session_end(scores: list[dict]) -> dict:
    return {"type": "session_end", "scores": scores}


def agent_caption(text: str, voice: str, gloss: list, translation: str) -> dict:
    return {
        "type": "agent_caption",
        "text": text,
        "voice": voice,
        "gloss": gloss,
        "translation": translation,
    }


def agent_partial_text(text: str, index: int) -> dict:
    return {"type": "agent_partial_text", "text": text, "index": index}


def agent_done(full_text: str = "") -> dict:
    return {"type": "agent_done", "full_text": full_text}


def agent_error(detail: str, index: Optional[int] = None) -> dict:
    return {"type": "agent_error", "detail": detail, "index": index}


def user_prompt(prompt: str, ideal: str, gloss: list, translation: str) -> dict:
    return {
        "type": "user_prompt",
        "prompt": prompt,
        "ideal": ideal,
        "gloss": gloss,
        "translation": translation,
    }


def user_transcript(text: str, confidence: float) -> dict:
    return {"type": "user_transcript", "text": text, "confidence": confidence}


def score(score_dict: dict[str, Any]) -> dict:
    return {"type": "score", "score": score_dict}
