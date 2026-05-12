"""Integration tests for Phase 3 streaming agent path over WebSocket."""
import os
from typing import AsyncIterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def _streaming_env(monkeypatch, on: bool):
    monkeypatch.setenv("SPEAKAGENT_STREAMING", "on" if on else "off")


async def _fake_stream_claude_three(messages, **kwargs) -> AsyncIterator[str]:
    for delta in ["Hi there. ", "How are ", "you? Tell ", "me more."]:
        yield delta


async def _fake_tts_stream(text, voice) -> AsyncIterator[bytes]:
    yield b"\x00\x01\x02\x03"


def _drain_until_done(ws, max_msgs: int = 50) -> list:
    """Receive WS messages until agent_done arrives. Records text frames only."""
    out = []
    for _ in range(max_msgs):
        msg = ws.receive_json()
        out.append(msg)
        if msg.get("type") == "agent_done":
            return out
    raise AssertionError(f"agent_done not received in {max_msgs} messages: {out}")


def test_streaming_on_emits_partial_text_audio_and_done(monkeypatch):
    _streaming_env(monkeypatch, True)
    from server.main import app

    with patch("server.coach.stream_claude", _fake_stream_claude_three), \
         patch("server.coach.synthesize_stream", _fake_tts_stream), \
         TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            assert ws.receive_json()["type"] == "session_start"
            msgs = _drain_until_done(ws)

    types = [m["type"] for m in msgs]
    partials = [m for m in msgs if m["type"] == "agent_partial_text"]
    audios = [m for m in msgs if m["type"] == "agent_audio"]
    dones = [m for m in msgs if m["type"] == "agent_done"]

    assert len(dones) == 1
    assert len(partials) >= 2, f"expected >=2 partials, got {len(partials)} in {types}"
    assert len(audios) >= len(partials), "every sentence should produce audio"

    for i, p in enumerate(partials):
        idx_partial = types.index("agent_partial_text", types.index("agent_partial_text") if i == 0 else 0)  # noqa
        assert p["index"] == i

    for i, a in enumerate(audios):
        assert "b64" in a
        assert isinstance(a["b64"], str) and len(a["b64"]) > 0


def test_streaming_off_is_phase2_compatible(monkeypatch):
    _streaming_env(monkeypatch, False)
    from server.main import app

    async def _empty_tts(text, voice):
        if False:
            yield b""

    with patch("server.main.synthesize_stream", _empty_tts), \
         TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            assert ws.receive_json()["type"] == "session_start"
            second = ws.receive_json()
            assert second["type"] == "agent_caption"
            third = ws.receive_json()
            assert third["type"] == "agent_done"


def test_tts_error_emits_agent_error_and_continues(monkeypatch):
    _streaming_env(monkeypatch, True)
    from server.main import app

    state = {"calls": 0}

    async def _flaky_tts(text, voice) -> AsyncIterator[bytes]:
        state["calls"] += 1
        if state["calls"] == 2:
            raise RuntimeError("simulated tts failure")
        yield b"\x10\x20"

    with patch("server.coach.stream_claude", _fake_stream_claude_three), \
         patch("server.coach.synthesize_stream", _flaky_tts), \
         TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            assert ws.receive_json()["type"] == "session_start"
            msgs = _drain_until_done(ws)

    errors = [m for m in msgs if m["type"] == "agent_error"]
    dones = [m for m in msgs if m["type"] == "agent_done"]
    partials = [m for m in msgs if m["type"] == "agent_partial_text"]

    assert len(dones) == 1
    assert len(errors) == 1
    assert errors[0].get("index") == 1
    assert len(partials) >= 2
