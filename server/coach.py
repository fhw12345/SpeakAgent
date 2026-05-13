"""Coach state machine. Pure orchestration; no HTTP, no I/O for adapters.

Phase 2 adds `dispatch_turn` which routes to either the legacy scripted
state machine or the realtime LLM-driven handler in `coach_realtime`,
based on `LessonSpec.mode`.

Phase 3 also exposes `stream_agent_turn(ws, conversation_state)` — a
streaming agent-speech path that pipes Claude SSE -> sentence splitter ->
Azure TTS per sentence -> WebSocket frames. Selected via env flag
`SPEAKAGENT_STREAMING=on`. When unset/off (default), callers should fall
back to the Phase 2 blocking path (`tts.synthesize_stream`).
"""
import base64
import os
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import WebSocketDisconnect

from server.lesson import LessonPlan
from server.llm_stream import stream_claude
from server.logging_setup import get_logger
from server.scorer import score_turn, TurnScore
from server.sentence_splitter import SentenceAccumulator
from server.tts import synthesize_bytes
from server import ws_messages

_log = get_logger("coach")


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


def streaming_enabled() -> bool:
    return os.environ.get("SPEAKAGENT_STREAMING", "off").lower() == "on"


async def stream_agent_turn(
    ws,
    messages: list[dict],
    voice: str,
    *,
    model: str | None = None,
    stream_fn: Callable[..., Any] | None = None,
    tts_fn: Callable[[str, str], Awaitable[bytes]] | None = None,
) -> str:
    """Stream an agent turn: Claude SSE -> sentence -> TTS -> WS.

    Emits `agent_partial_text` per completed sentence, `agent_audio` per
    synthesized sentence, and a single `agent_done` at the end. Errors on a
    single sentence emit `agent_error` and continue. Returns the full text.

    `stream_fn` and `tts_fn` are injected for tests.
    """
    sf = stream_fn or stream_claude
    tf = tts_fn or synthesize_bytes
    splitter = SentenceAccumulator()
    full_parts: list[str] = []
    index = 0

    async def _emit_sentence(sentence: str) -> None:
        nonlocal index
        await ws.send_json(ws_messages.agent_partial_text(sentence, index))
        try:
            audio = await tf(sentence, voice)
            b64 = base64.b64encode(audio).decode("ascii")
            await ws.send_json(ws_messages.agent_audio(b64, index))
        except WebSocketDisconnect:
            raise
        except Exception as e:
            _log.warning("tts_sentence_failed", index=index, error=str(e)[:200])
            try:
                await ws.send_json(ws_messages.agent_error(f"tts_failed: {e}", index))
            except WebSocketDisconnect:
                raise
        index += 1

    try:
        kwargs = {}
        if model is not None:
            kwargs["model"] = model
        async for delta in sf(messages, **kwargs):
            full_parts.append(delta)
            for sentence in splitter.push(delta):
                await _emit_sentence(sentence)
    except WebSocketDisconnect:
        _log.info("ws_disconnect_during_stream")
        return "".join(full_parts).strip()
    except Exception as e:
        _log.warning("llm_stream_failed", error=str(e)[:200])
        try:
            await ws.send_json(ws_messages.agent_error(f"llm_stream_failed: {e}", None))
        except WebSocketDisconnect:
            return "".join(full_parts).strip()

    try:
        for sentence in splitter.flush():
            await _emit_sentence(sentence)
        full_text = "".join(full_parts).strip()
        await ws.send_json(ws_messages.agent_done(full_text))
    except WebSocketDisconnect:
        _log.info("ws_disconnect_during_flush")
        return "".join(full_parts).strip()
    return full_text

