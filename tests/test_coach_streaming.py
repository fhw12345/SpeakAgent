"""Integration tests for streaming agent turn (coach.stream_agent_turn).

Uses a fake WebSocket (records send_json calls) and injects a fake
stream_fn / tts_fn to keep tests hermetic. Also covers the
SPEAKAGENT_STREAMING=off branch via the FastAPI WS endpoint.
"""
import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server import coach


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


async def _fake_stream(messages, **kwargs):
    for delta in ["Hi there. ", "How are you? ", "Tell me more."]:
        yield delta


async def _fake_tts(text: str, voice: str) -> bytes:
    await asyncio.sleep(0.001)
    return b"\x00\x01" + text.encode()


async def _failing_tts_on_sentence_2(text: str, voice: str) -> bytes:
    if "How are you" in text:
        raise RuntimeError("boom")
    return b"\x00" + text.encode()


@pytest.mark.asyncio
async def test_streaming_emits_partials_and_audio_in_order():
    ws = FakeWS()
    full = await coach.stream_agent_turn(
        ws, [{"role": "user", "content": "x"}], voice="en-US-AriaNeural",
        stream_fn=_fake_stream, tts_fn=_fake_tts,
    )

    types = [m["type"] for m in ws.sent]
    assert types.count("agent_partial_text") == 3
    assert types.count("agent_audio") == 3
    assert types.count("agent_done") == 1
    assert types[-1] == "agent_done"

    partials = [m for m in ws.sent if m["type"] == "agent_partial_text"]
    audios = [m for m in ws.sent if m["type"] == "agent_audio"]
    assert [p["index"] for p in partials] == [0, 1, 2]
    assert [a["index"] for a in audios] == [0, 1, 2]

    # audio[i] must come after partial_text[i]
    for i in range(3):
        pi = next(j for j, m in enumerate(ws.sent) if m["type"] == "agent_partial_text" and m["index"] == i)
        ai = next(j for j, m in enumerate(ws.sent) if m["type"] == "agent_audio" and m["index"] == i)
        assert pi < ai

    assert "Hi there." in full and "Tell me more." in full


@pytest.mark.asyncio
async def test_tts_error_emits_agent_error_and_continues():
    ws = FakeWS()
    await coach.stream_agent_turn(
        ws, [{"role": "user", "content": "x"}], voice="en-US-AriaNeural",
        stream_fn=_fake_stream, tts_fn=_failing_tts_on_sentence_2,
    )
    errors = [m for m in ws.sent if m["type"] == "agent_error"]
    assert len(errors) == 1
    assert errors[0]["index"] == 1
    # Still got 3 partials and a final done
    assert sum(1 for m in ws.sent if m["type"] == "agent_partial_text") == 3
    assert ws.sent[-1]["type"] == "agent_done"


@pytest.mark.asyncio
async def test_first_audio_is_faster_than_blocking_equivalent():
    """Streaming first-audio latency <= 50% of blocking 3-sentence path
    when each TTS call costs 200ms."""
    import time

    async def slow_tts(text: str, voice: str) -> bytes:
        await asyncio.sleep(0.2)
        return b"x"

    ws = FakeWS()
    t0 = time.perf_counter()
    task = asyncio.create_task(coach.stream_agent_turn(
        ws, [{"role": "user", "content": "x"}], voice="v",
        stream_fn=_fake_stream, tts_fn=slow_tts,
    ))
    # Spin until first agent_audio appears
    while not any(m["type"] == "agent_audio" for m in ws.sent):
        await asyncio.sleep(0.005)
    first_audio_t = time.perf_counter() - t0
    await task
    blocking_equiv = 0.2 * 3
    assert first_audio_t <= 0.5 * blocking_equiv, (
        f"first_audio took {first_audio_t:.3f}s; budget {0.5*blocking_equiv:.3f}s"
    )


def test_streaming_off_falls_back_to_phase2_no_partials(monkeypatch):
    """With SPEAKAGENT_STREAMING=off the WS endpoint emits no agent_partial_text."""
    async def empty_stream(text, voice):
        if False:
            yield b""

    monkeypatch.setenv("SPEAKAGENT_STREAMING", "off")
    from server.main import app

    with patch("server.main.synthesize_stream", empty_stream), TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            seen_types: list[str] = []
            for _ in range(3):
                msg = ws.receive_json()
                seen_types.append(msg["type"])
                if msg["type"] == "agent_done":
                    break
            assert "agent_partial_text" not in seen_types
            assert "agent_done" in seen_types
