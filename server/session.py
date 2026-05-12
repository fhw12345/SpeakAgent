"""Per-WebSocket session state container."""
import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Optional

from server.coach import Coach
from server.lesson import LessonPlan


@dataclass
class SpeechSession:
    id: str
    coach: Coach
    audio_buffer: bytearray = field(default_factory=bytearray)
    # Phase 4: barge-in support. `cancel_event` is set whenever the user
    # starts talking (either via VAD or an explicit `interrupt` message)
    # while the agent is mid-stream. The streaming TTS loop checks it
    # between chunks and bails out so a new turn can begin.
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    # True only while the agent TTS loop is actively streaming chunks.
    # Used to gate barge-in signals so user speech during a user turn
    # does not leak a stale cancel into the next agent turn.
    agent_streaming: bool = False
    # When VAD is on we accept audio frames continuously rather than only
    # between explicit ptt_start/ptt_end markers.
    vad_segment_id: Optional[str] = None


def new_session(plan: LessonPlan) -> SpeechSession:
    return SpeechSession(id=uuid.uuid4().hex[:12], coach=Coach(plan))
