"""Per-WebSocket session state container."""
import uuid
from dataclasses import dataclass, field

from server.coach import Coach
from server.lesson import LessonPlan


@dataclass
class SpeechSession:
    id: str
    coach: Coach
    audio_buffer: bytearray = field(default_factory=bytearray)


def new_session(plan: LessonPlan) -> SpeechSession:
    return SpeechSession(id=uuid.uuid4().hex[:12], coach=Coach(plan))
