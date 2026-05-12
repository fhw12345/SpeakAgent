"""Coach state machine + streaming agent-turn driver.

The Coach class is pure orchestration. `stream_agent_turn` is the Phase 3
streaming pipeline that pumps Claude SSE -> sentence splitter -> TTS -> WS.
"""
from __future__ import annotations

import base64
import os
from enum import Enum
from typing import AsyncIterator, Callable, Dict, List, Optional

from server.lesson import LessonPlan
from server.logging_setup import get_logger
from server.scorer import score_turn, TurnScore
from server.sentence_splitter import SentenceAccumulator
from server.ws_messages import AgentDone, AgentError, AgentPartialText

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


def streaming_enabled() -> bool:
    """SPEAKAGENT_STREAMING=on (default) enables Phase 3 streaming path."""
    return os.environ.get("SPEAKAGENT_STREAMING", "on").lower() == "on"


# Default LLM stream source. Tests override this attribute on the module.
async def _default_stream_source(turn: Dict) -> AsyncIterator[str]:
    from server.llm_stream import stream_claude
    say = turn.get("say", "")
    prompt = (
        "Deliver this line naturally as a friendly English speaking coach. "
        "Keep the meaning and split into clear sentences. "
        f"Line: {say!r}"
    )
    async for delta in stream_claude(messages=[{"role": "user", "content": prompt}]):
        yield delta


async def _default_tts(text: str, voice: str) -> bytes:
    from server.tts import synthesize_stream
    chunks: list[bytes] = []
    async for c in synthesize_stream(text, voice=voice):
        chunks.append(c)
    return b"".join(chunks)


# Indirection points for tests. Reassign module attributes to override.
stream_source: Callable[[Dict], AsyncIterator[str]] = _default_stream_source
tts_bytes: Callable[[str, str], "any"] = _default_tts


async def stream_agent_turn(ws, turn: Dict, voice: str) -> str:
    """Stream one agent utterance.

    Pumps text deltas from `stream_source(turn)` into a SentenceAccumulator;
    each completed sentence is sent as `agent_partial_text`, then synthesized
    via `tts_bytes(...)` and forwarded as `agent_audio` (b64). Final utterance
    text is returned and `agent_done` is sent exactly once. Per-sentence TTS or
    SSE errors emit `agent_error` and continue.
    """
    acc = SentenceAccumulator()
    full: list[str] = []
    index = 0

    async def _emit(sentence: str, idx: int) -> None:
        await ws.send_json(AgentPartialText(text=sentence, index=idx).to_dict())
        try:
            audio = await tts_bytes(sentence, voice)
        except Exception as e:
            _log.warning("stream_tts_error", index=idx, error=str(e)[:200])
            await ws.send_json(AgentError(detail=f"tts_failed: {e}", index=idx).to_dict())
            return
        if audio:
            b64 = base64.b64encode(audio).decode("ascii")
            await ws.send_json({"type": "agent_audio", "b64": b64, "index": idx})

    try:
        async for delta in stream_source(turn):
            sentences = acc.push(delta)
            for s in sentences:
                full.append(s)
                await _emit(s, index)
                index += 1
    except Exception as e:
        _log.warning("stream_source_error", error=str(e)[:200])
        await ws.send_json(AgentError(detail=f"stream_failed: {e}", index=index).to_dict())

    for s in acc.flush():
        full.append(s)
        await _emit(s, index)
        index += 1

    full_text = " ".join(full).strip()
    await ws.send_json(AgentDone(full_text=full_text).to_dict())
    return full_text
