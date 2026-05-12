"""Streaming agent-turn driver: Claude SSE -> sentence accumulator -> Azure TTS -> WS."""
import asyncio
import os
from base64 import b64encode
from typing import AsyncIterator

from server.llm_stream import stream_claude
from server.logging_setup import get_logger
from server.sentence_splitter import SentenceAccumulator
from server.tts import synthesize_bytes
from server.ws_messages import (
    agent_audio_b64,
    agent_done,
    agent_error,
    agent_partial_text,
)

_log = get_logger("agent_turn")


_FAKE_REPLY = "Hi there. How are you today? Tell me more about your week."


async def _fake_stream(messages, model=None, system="", gateway_url=None) -> AsyncIterator[str]:
    """Deterministic stub used by e2e/manual smoke when SPEAKAGENT_FAKE_STREAM=1.

    Yields short deltas with a small sleep so the streaming pipeline is observable.
    """
    text = os.environ.get("SPEAKAGENT_FAKE_STREAM_TEXT", _FAKE_REPLY)
    chunk = 6
    for i in range(0, len(text), chunk):
        yield text[i:i + chunk]
        await asyncio.sleep(0.01)


async def _emit_sentence(ws, sentence: str, voice: str, index: int) -> None:
    await ws.send_json(agent_partial_text(sentence, index))
    try:
        audio = await synthesize_bytes(sentence, voice)
        await ws.send_json(agent_audio_b64(b64encode(audio).decode("ascii"), index))
    except Exception as e:
        _log.warning("tts_sentence_failed", index=index, error=str(e)[:200])
        await ws.send_json(agent_error(f"tts_failed: {str(e)[:160]}", index=index))


def _build_messages(turn: dict) -> list[dict]:
    say = turn.get("say", "").strip()
    user = (
        f"You are an English speaking coach. Deliver this line naturally to the learner "
        f"in 1-3 short sentences (you may rephrase slightly). Line: {say!r}."
    )
    return [{"role": "user", "content": user}]


async def stream_agent_turn(ws, sess, turn: dict, voice: str, plan) -> None:
    """Stream Claude reply, sentence-by-sentence, with TTS audio per sentence.

    Sends `agent_caption` once up front so the existing UI dialogue rendering and
    `currentBuffer` initialization stay parity-compatible with Phase 2.
    Emits `agent_partial_text` + `agent_audio` (JSON, base64) per sentence.
    Always finishes with exactly one `agent_done`.
    """
    await ws.send_json({
        "type": "agent_caption",
        "text": turn.get("say", ""),
        "voice": voice,
        "gloss": turn.get("gloss", []),
        "translation": turn.get("translation", ""),
    })

    use_fake = os.environ.get("SPEAKAGENT_FAKE_STREAM", "0").lower() in ("1", "true", "on")
    stream_fn = _fake_stream if use_fake else stream_claude

    full_text = ""
    index = 0
    acc = SentenceAccumulator()
    try:
        async for delta in stream_fn(_build_messages(turn)):
            full_text += delta
            for sentence in acc.push(delta):
                await _emit_sentence(ws, sentence, voice, index)
                index += 1
        for sentence in acc.flush():
            await _emit_sentence(ws, sentence, voice, index)
            index += 1
    except Exception as e:
        _log.error("agent_stream_failed", error=str(e)[:200])
        await ws.send_json(agent_error(str(e)[:200]))

    await ws.send_json(agent_done(full_text))
