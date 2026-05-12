"""WebSocket message types and serializers used by the streaming agent path.

The existing ad-hoc `ws.send_json({...})` calls in main.py remain valid; this
module exists so new message shapes (notably `agent_partial_text`) live in one
place and can be unit-tested.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentPartialText:
    text: str
    index: int

    def to_dict(self) -> dict:
        return {"type": "agent_partial_text", "text": self.text, "index": self.index}


@dataclass(frozen=True)
class AgentAudio:
    b64: str
    index: int

    def to_dict(self) -> dict:
        return {"type": "agent_audio", "b64": self.b64, "index": self.index}


@dataclass(frozen=True)
class AgentDone:
    full_text: str

    def to_dict(self) -> dict:
        return {"type": "agent_done", "full_text": self.full_text}


@dataclass(frozen=True)
class AgentError:
    detail: str
    index: int | None = None

    def to_dict(self) -> dict:
        return {"type": "agent_error", "detail": self.detail, "index": self.index}
