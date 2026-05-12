"""Coach state machine. Pure orchestration; no HTTP, no I/O for adapters.

Also hosts `stream_agent_turn`, the Phase 3 streaming agent-turn coroutine
that wires Claude SSE -> sentence accumulator -> Azure TTS -> WebSocket.
"""
from enum import Enum
from typing import Any, Dict, List, Optional

from server.lesson import LessonPlan
from server.scorer import score_turn, TurnScore
from server.sentence_splitter import SentenceAccumulator
from server.llm_stream import stream_claude
from server.tts import synthesize_stream
from server.ws_messages import (
    agent_audio_b64,
    agent_done,
    agent_error,
    agent_partial_text,
)


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


async def stream_agent_turn(
    ws: Any,
    messages: list[dict],
    voice: str,
    *,
    model: Optional[str] = None,
    system: Optional[str] = None,
) -> str:
    """Stream an agent turn end-to-end. Returns the full agent text.

    Emits, in order per sentence i:
      {type: agent_partial_text, text, index: i}
      one or more {type: agent_audio, b64, index: i}
    Then a single {type: agent_done, full_text}.

    Errors on a single sentence emit `agent_error` and the loop continues.
    """
    acc = SentenceAccumulator()
    full_parts: list[str] = []
    sentence_index = 0

    async def _emit_sentence(text: str, idx: int) -> None:
        await ws.send_json(agent_partial_text(text, idx))
        try:
            async for chunk in synthesize_stream(text, voice=voice):
                if chunk:
                    await ws.send_json(agent_audio_b64(chunk, idx))
        except Exception as e:  # noqa: BLE001
            await ws.send_json(agent_error(f"tts_failed: {e}"[:200], index=idx))

    kwargs: dict[str, Any] = {}
    if model is not None:
        kwargs["model"] = model
    if system is not None:
        kwargs["system"] = system

    try:
        async for delta in stream_claude(messages, **kwargs):
            full_parts.append(delta)
            for sent in acc.push(delta):
                await _emit_sentence(sent, sentence_index)
                sentence_index += 1
    except Exception as e:  # noqa: BLE001
        await ws.send_json(agent_error(f"llm_stream_failed: {e}"[:200], index=None))

    for sent in acc.flush():
        await _emit_sentence(sent, sentence_index)
        sentence_index += 1

    full_text = "".join(full_parts).strip()
    await ws.send_json(agent_done(full_text))
    return full_text
