"""Coach state machine. Pure orchestration; no HTTP, no I/O for adapters.

Phase 2 adds `dispatch_turn` which routes to either the legacy scripted
state machine or the realtime LLM-driven handler in `coach_realtime`,
based on `LessonSpec.mode`."""
from enum import Enum
from typing import Dict, List, Optional

from server.lesson import LessonPlan
from server.scorer import score_turn, TurnScore


class CoachState(str, Enum):
    IDLE = "idle"
    SPEAK_PROMPT = "speak_prompt"
    LISTEN_USER = "listen_user"
    SCORE = "score"
    NEXT_TURN = "next_turn"
    SESSION_END = "session_end"


class Coach:
    def __init__(self, plan: LessonPlan):
        self.plan = plan
        self.state = CoachState.IDLE
        self._idx = -1
        self._last_user_ideal: Optional[str] = None
        self.scores: List[TurnScore] = []

    def next_turn(self) -> Optional[Dict]:
        self._idx += 1
        if self._idx >= len(self.plan.turns):
            self.state = CoachState.SESSION_END
            return None
        turn = self.plan.turns[self._idx]
        if turn["speaker"] == "agent":
            self.state = CoachState.SPEAK_PROMPT
        else:
            self.state = CoachState.LISTEN_USER
            self._last_user_ideal = turn.get("ideal", "")
        return turn

    def submit_user_response(self, text: str, words: List[Dict], confidence: float) -> TurnScore:
        self.state = CoachState.SCORE
        s = score_turn(
            user_text=text,
            user_words=words,
            user_confidence=confidence,
            ideal_text=self._last_user_ideal or text,
        )
        self.scores.append(s)
        if self._idx + 1 >= len(self.plan.turns):
            self.state = CoachState.SESSION_END
        else:
            self.state = CoachState.NEXT_TURN
        return s


def dispatch_turn(lesson, session_id: str, user_text: str) -> dict:
    """Route a user turn to the correct handler based on lesson mode.

    Scripted lessons keep their existing per-WS handling (caller uses
    `Coach.submit_user_response` directly). Realtime lessons go through
    `coach_realtime.handle_turn`. This dispatcher exists so REST callers
    can stay mode-agnostic.
    """
    mode = getattr(lesson, "mode", "scripted")
    if mode == "realtime":
        from server import coach_realtime
        return coach_realtime.handle_turn(session_id, user_text)
    raise NotImplementedError(
        "dispatch_turn for scripted mode is handled via the existing Coach.submit_user_response path"
    )
