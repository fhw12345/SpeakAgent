"""Coach state machine + streaming agent-turn driver.

Most of this file is pure orchestration with no I/O. `stream_agent_turn`
is the exception: it is the Phase 3 streaming path that pulls Claude SSE
deltas, splits them into sentences, synthesizes each one with Azure TTS,
and forwards results to the client over the WebSocket.
"""
import os
from enum import Enum
from typing import Any, Dict, List, Optional

from server import ws_messages
from server.lesson import LessonPlan
from server.llm_stream import stream_claude
from server.logging_setup import get_logger
from server.scorer import score_turn, TurnScore
from server.sentence_splitter import SentenceAccumulator
from server.tts import synthesize_bytes

_log = get_logger("coach")


def streaming_enabled() -> bool:
    return os.environ.get("SPEAKAGENT_STREAMING", "on").lower() not in ("off", "0", "false", "no")


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
    ws,
    text: str,
    voice: str,
    *,
    use_llm: bool = False,
    llm_messages: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Stream an agent utterance to the client.

    When `use_llm` is True, pulls deltas from Claude SSE and accumulates
    them into sentences. Otherwise treats `text` as a fixed reply and
    splits it the same way (still useful for sentence-level audio).

    For each completed sentence, emits:
      1. `agent_partial_text` (text + index)
      2. `agent_audio` (base64 MP3 + index)

    Errors on a single sentence emit `agent_error` and continue. The
    final `agent_done` is sent by the caller (so callers can append the
    full text to a transcript first).

    Returns the full concatenated text actually emitted.
    """
    acc = SentenceAccumulator()
    sentences: List[str] = []
    full_parts: List[str] = []

    async def _emit(sentence: str) -> None:
        idx = len(sentences)
        sentences.append(sentence)
        full_parts.append(sentence)
        await ws.send_json(ws_messages.agent_partial_text(sentence, idx))
        try:
            audio = await synthesize_bytes(sentence, voice=voice)
            await ws.send_json(ws_messages.agent_audio(audio, idx))
        except Exception as e:
            _log.warning("tts_sentence_failed", index=idx, error=str(e)[:200])
            await ws.send_json(ws_messages.agent_error(f"tts_failed: {e}", index=idx))

    try:
        if use_llm:
            async for delta in stream_claude(llm_messages or [{"role": "user", "content": text}]):
                for s in acc.push(delta):
                    await _emit(s)
        else:
            for s in acc.push(text):
                await _emit(s)
    except Exception as e:
        _log.warning("llm_stream_failed", error=str(e)[:200])
        await ws.send_json(ws_messages.agent_error(f"llm_stream_failed: {e}", index=None))

    for s in acc.flush():
        await _emit(s)

    return " ".join(full_parts)
