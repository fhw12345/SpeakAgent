"""Coach state machine. Pure orchestration; no HTTP, no I/O for adapters.

Also provides REST-mode session dispatch: `start_session(spec)` and
`handle_turn(session_id, user_text)` route to either the scripted handler
(below) or `server.coach_realtime` based on `LessonSpec.mode`.
"""
import time
import uuid
from enum import Enum
from typing import Dict, List, Optional

from server import coach_realtime
from server.lesson import LessonPlan
from server.lesson_loader import LessonSpec
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


# ---------------------------------------------------------------------------
# REST-mode dispatch (Phase 2): scripted lessons advance text-only via
# /api/lesson/start + /api/lesson/turn. Audio/scoring stays on the WebSocket.
# ---------------------------------------------------------------------------

_SCRIPTED_REST_SESSIONS: Dict[str, "_ScriptedRestSession"] = {}
_SCRIPTED_REST_TTL_S = 30 * 60


def _evict_scripted_rest_expired() -> None:
    cutoff = time.time() - _SCRIPTED_REST_TTL_S
    stale = [sid for sid, s in _SCRIPTED_REST_SESSIONS.items() if s.last_activity < cutoff]
    for sid in stale:
        _SCRIPTED_REST_SESSIONS.pop(sid, None)


class _ScriptedRestSession:
    def __init__(self, spec: LessonSpec):
        self.spec = spec
        self.turns: List[Dict] = list(spec.turns or [])
        self.idx = 0  # next turn to consume
        self.user_turn_count = 0
        self.done = False
        self.last_activity = time.time()

    def _next_agent_say(self) -> str:
        """Advance idx to the next agent turn and return its text."""
        while self.idx < len(self.turns) and self.turns[self.idx]["speaker"] != "agent":
            self.idx += 1
        if self.idx >= len(self.turns):
            self.done = True
            return ""
        say = self.turns[self.idx].get("say", "")
        self.idx += 1
        return say

    def _consume_user_slot(self) -> None:
        """If the next turn is a user prompt, skip it (we accepted the user_text)."""
        if self.idx < len(self.turns) and self.turns[self.idx]["speaker"] == "user":
            self.idx += 1


def start_session(spec: LessonSpec) -> dict:
    """Start a session in either mode and return the start payload."""
    _evict_scripted_rest_expired()
    if spec.mode == "realtime":
        session_id, first = coach_realtime.start_session(spec)
        return {"session_id": session_id, "mode": "realtime", "first_agent_utterance": first}

    sid = uuid.uuid4().hex
    sess = _ScriptedRestSession(spec)
    first = sess._next_agent_say()
    _SCRIPTED_REST_SESSIONS[sid] = sess
    return {"session_id": sid, "mode": "scripted", "first_agent_utterance": first}


def handle_turn(session_id: str, user_text: str) -> dict:
    """Advance one user turn and return {agent_utterance, turn_index, done}."""
    _evict_scripted_rest_expired()
    if session_id in _SCRIPTED_REST_SESSIONS:
        sess = _SCRIPTED_REST_SESSIONS[session_id]
        sess.last_activity = time.time()
        if sess.done:
            return {"agent_utterance": "", "turn_index": sess.user_turn_count, "done": True}
        sess.user_turn_count += 1
        sess._consume_user_slot()
        say = sess._next_agent_say()
        return {
            "agent_utterance": say,
            "turn_index": sess.user_turn_count,
            "done": sess.done,
        }
    return coach_realtime.handle_turn(session_id, user_text)


def reset_rest_sessions_for_test() -> None:
    _SCRIPTED_REST_SESSIONS.clear()
    coach_realtime.reset_sessions_for_test()
