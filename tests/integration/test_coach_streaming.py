"""Integration tests for the streaming agent-turn path (Phase 3)."""
import asyncio
import json
import os
import time
from typing import AsyncIterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server.stt import TranscriptionResult


def _fake_transcribe(self, pcm):
    return TranscriptionResult(
        text="Hello and welcome to the interview.",
        confidence=0.92,
        words=[{"w": w, "start": i*0.3, "end": i*0.3+0.25, "prob": 0.95}
               for i, w in enumerate("Hello and welcome to the interview".split())],
        language="en",
    )


_FAKE_JUDGE = '{"content_score": 5, "rewrite": "Hello and welcome to the interview.", "issues": []}'


def _make_streamer(deltas: list[str], delay: float = 0.0):
    async def _gen(messages, model=None, system="", gateway_url=None) -> AsyncIterator[str]:
        for d in deltas:
            if delay:
                await asyncio.sleep(delay)
            yield d
    return _gen


def _make_synth(latency: float = 0.0, fail_indices: set[int] | None = None):
    fail_indices = fail_indices or set()
    state = {"calls": 0}

    async def _synth(text: str, voice: str) -> bytes:
        idx = state["calls"]
        state["calls"] += 1
        if latency:
            await asyncio.sleep(latency)
        if idx in fail_indices:
            raise RuntimeError("fake_tts_boom")
        return b"\x00" * 32

    return _synth


def _drive_ws_to_completion(ws, max_msgs: int = 400) -> list[dict]:
    """Pull JSON + binary messages until session_end. Replies to user_prompt with stub audio."""
    received: list[dict] = []
    for _ in range(max_msgs):
        msg = ws.receive()
        if "text" in msg and msg["text"]:
            data = json.loads(msg["text"])
            received.append({"kind": "json", **data})
            if data["type"] == "user_prompt":
                ws.send_bytes(b"\x00\x00" * 16000)
                ws.send_text(json.dumps({"type": "user_audio_end"}))
            elif data["type"] == "session_end":
                return received
        elif "bytes" in msg and msg["bytes"] is not None:
            received.append({"kind": "bytes", "len": len(msg["bytes"])})
    return received


@pytest.fixture
def app_with_env():
    """Yield (app_factory) so each test sets env BEFORE app import order matters."""
    # server.main is already imported by sibling tests; we mutate env which is read at request time.
    yield


def _open_ws(env: dict, **patches):
    os.environ.update(env)
    from server.main import app  # imported here to ensure env reads at request time
    pset = [
        patch("server.stt.SttEngine.transcribe", _fake_transcribe),
        patch("server.scorer.call_with_fallback", return_value=_FAKE_JUDGE),
    ]
    for k, v in patches.items():
        pset.append(patch(k, v))
    ctx = []
    for p in pset:
        ctx.append(p)
        p.start()
    client = TestClient(app)
    return client, ctx


def _stop_patches(ctx):
    for p in ctx:
        p.stop()


def test_streaming_on_emits_partials_and_audio(monkeypatch):
    monkeypatch.setenv("SPEAKAGENT_STREAMING", "on")
    deltas = ["Hi there. ", "How are you? ", "Tell me more."]
    monkeypatch.setattr("server.agent_turn.stream_claude", _make_streamer(deltas))
    monkeypatch.setattr("server.agent_turn.synthesize_bytes", _make_synth())

    client, ctx = _open_ws({})
    try:
        with client.websocket_connect("/ws/session") as ws:
            received = _drive_ws_to_completion(ws)
    finally:
        _stop_patches(ctx)

    # First agent turn block: collect indices for partials and JSON audio frames before
    # the first session_end.
    partials = [m for m in received if m.get("type") == "agent_partial_text"]
    json_audio = [m for m in received if m.get("type") == "agent_audio"]
    dones = [m for m in received if m.get("type") == "agent_done"]
    assert len(partials) >= 3, f"expected >=3 partials, got {len(partials)}: {partials}"
    assert len(json_audio) >= 3
    # `agent_done` count should equal number of agent turns; at least 1.
    assert len(dones) >= 1

    # Ordering: each partial[i] precedes json_audio[i] within the same turn.
    # Reduce check to first 3 partials and first 3 audios:
    partial_idxs = [received.index(p) for p in partials[:3]]
    audio_idxs = [received.index(a) for a in json_audio[:3]]
    for pi, ai in zip(partial_idxs, audio_idxs):
        assert pi < ai


def test_streaming_off_byte_identical(monkeypatch):
    monkeypatch.setenv("SPEAKAGENT_STREAMING", "off")

    async def _empty_stream(text, voice):
        if False:
            yield b""

    monkeypatch.setattr("server.main.synthesize_stream", _empty_stream)
    client, ctx = _open_ws({})
    try:
        with client.websocket_connect("/ws/session") as ws:
            received = _drive_ws_to_completion(ws)
    finally:
        _stop_patches(ctx)

    partials = [m for m in received if m.get("type") == "agent_partial_text"]
    json_audio = [m for m in received if m.get("type") == "agent_audio"]
    assert partials == []
    assert json_audio == []
    # Still saw at least one agent_done and agent_caption.
    assert any(m.get("type") == "agent_done" for m in received)
    assert any(m.get("type") == "agent_caption" for m in received)


def test_tts_error_per_sentence_continues(monkeypatch):
    monkeypatch.setenv("SPEAKAGENT_STREAMING", "on")
    deltas = ["A short one. ", "Second sentence here. ", "Third one."]
    monkeypatch.setattr("server.agent_turn.stream_claude", _make_streamer(deltas))
    # Fail TTS on the second call (index 1) of the first agent turn only.
    state = {"call": 0}

    async def _selective_synth(text, voice):
        idx = state["call"]
        state["call"] += 1
        if idx == 1:
            raise RuntimeError("boom")
        return b"\x00" * 16

    monkeypatch.setattr("server.agent_turn.synthesize_bytes", _selective_synth)
    client, ctx = _open_ws({})
    try:
        with client.websocket_connect("/ws/session") as ws:
            received = _drive_ws_to_completion(ws)
    finally:
        _stop_patches(ctx)

    errors = [m for m in received if m.get("type") == "agent_error"]
    partials = [m for m in received if m.get("type") == "agent_partial_text"]
    json_audio = [m for m in received if m.get("type") == "agent_audio"]
    assert any(e.get("index") == 1 for e in errors), f"errors={errors}"
    # Still got 3 partials (one per sentence) and 2 audio frames (failed one omitted).
    assert len(partials) >= 3
    assert len(json_audio) >= 2
    assert any(m.get("type") == "agent_done" for m in received)


def test_first_audio_under_half_baseline(monkeypatch):
    """Streaming first-audio latency should be < 0.5x of the OFF baseline.

    Baseline: synthesize_bytes called once per turn with ~600ms latency.
    Streaming: synthesize_bytes called per sentence (3x) with 200ms latency,
    so first audio arrives after ~200ms vs ~600ms baseline.
    """
    deltas = ["First. ", "Second. ", "Third."]

    # Baseline: OFF mode using synthesize_stream that takes 600ms.
    async def _slow_stream(text, voice):
        await asyncio.sleep(0.6)
        yield b"\x00" * 32

    monkeypatch.setenv("SPEAKAGENT_STREAMING", "off")
    monkeypatch.setattr("server.main.synthesize_stream", _slow_stream)
    client, ctx = _open_ws({})
    baseline_first_audio = None
    t0 = time.perf_counter()
    try:
        with client.websocket_connect("/ws/session") as ws:
            for _ in range(40):
                msg = ws.receive()
                if "bytes" in msg and msg["bytes"] is not None:
                    baseline_first_audio = time.perf_counter() - t0
                    break
                if "text" in msg and msg["text"]:
                    data = json.loads(msg["text"])
                    if data.get("type") == "user_prompt":
                        ws.send_text(json.dumps({"type": "user_audio_end"}))
    finally:
        _stop_patches(ctx)
    assert baseline_first_audio is not None and baseline_first_audio >= 0.5

    # Streaming path: 3 sentences with 200ms TTS each.
    monkeypatch.setenv("SPEAKAGENT_STREAMING", "on")
    monkeypatch.setattr("server.agent_turn.stream_claude", _make_streamer(deltas))
    monkeypatch.setattr("server.agent_turn.synthesize_bytes", _make_synth(latency=0.2))
    client2, ctx2 = _open_ws({})
    streaming_first_audio = None
    t0 = time.perf_counter()
    try:
        with client2.websocket_connect("/ws/session") as ws:
            for _ in range(40):
                msg = ws.receive()
                if "text" in msg and msg["text"]:
                    data = json.loads(msg["text"])
                    if data.get("type") == "agent_audio":
                        streaming_first_audio = time.perf_counter() - t0
                        break
                    if data.get("type") == "user_prompt":
                        ws.send_text(json.dumps({"type": "user_audio_end"}))
    finally:
        _stop_patches(ctx2)
    assert streaming_first_audio is not None
    assert streaming_first_audio < 0.5 * baseline_first_audio, (
        f"streaming={streaming_first_audio:.3f}s baseline={baseline_first_audio:.3f}s"
    )
