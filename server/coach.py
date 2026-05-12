"""Coach state machine and streaming agent-turn orchestration.

The `Coach` class itself stays pure (no I/O). `stream_agent_turn` lives
here per Phase 3 PRD: it reads from the Claude SSE gateway, splits into
sentences, synthesizes each via Azure TTS, and emits WS frames in order
(`agent_partial_text` → binary audio per sentence → `agent_done`).
"""
from enum import Enum
from typing import Dict, List, Optional

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


async def stream_agent_turn(
    ws,
    prompt: str,
    voice: str,
    *,
    system: str = "You are a helpful English speaking coach. Reply naturally in 2-4 short sentences.",
) -> str:
    """Stream Claude → split into sentences → TTS → WS, in order.

    Returns the full concatenated text spoken. Errors on a single sentence
    emit `agent_error` and the loop continues; the turn always ends with
    `agent_done`.
    """
    acc = SentenceAccumulator()
    sentences: list[str] = []
    full_parts: list[str] = []

    async def _emit(sentence: str) -> None:
        idx = len(sentences)
        sentences.append(sentence)
        full_parts.append(sentence)
        await ws.send_json(ws_messages.agent_partial_text(sentence, idx))
        try:
            audio = await synthesize_bytes(sentence, voice=voice)
        except Exception as e:
            _log.warning("stream_tts_failed", index=idx, error=str(e)[:200])
            await ws.send_json(ws_messages.agent_error(f"tts_failed: {e}", index=idx))
            return
        if audio:
            await ws.send_bytes(audio)

    try:
        async for delta in stream_claude(messages=[{"role": "user", "content": prompt}], system=system):
            for sentence in acc.push(delta):
                await _emit(sentence)
    except Exception as e:
        _log.warning("stream_llm_failed", error=str(e)[:200])
        await ws.send_json(ws_messages.agent_error(f"llm_stream_failed: {e}", index=None))

    for sentence in acc.flush():
        await _emit(sentence)

    full_text = " ".join(full_parts).strip()
    await ws.send_json(ws_messages.agent_done(full_text))
    return full_text
