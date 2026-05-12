"""Integration tests for the Phase 3 streaming agent-turn path."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


class FakeWS:
    def __init__(self) -> None:
        self.sent: list = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(("json", payload))

    async def send_bytes(self, data: bytes) -> None:
        self.sent.append(("bytes", data))


@pytest.mark.asyncio
async def test_stream_agent_turn_emits_partial_text_then_audio_per_sentence():
    from server.coach import stream_agent_turn

    text = "Hi there. How are you? Tell me more."

    async def fake_synth(t: str, voice: str) -> bytes:
        return ("AUDIO[" + t + "]").encode()

    ws = FakeWS()
    with patch("server.coach.synthesize_bytes", fake_synth):
        full = await stream_agent_turn(ws, text, voice="en-US-AriaNeural", use_llm=False)

    types = [(kind, p["type"]) for kind, p in ws.sent]
    json_msgs = [p for kind, p in ws.sent if kind == "json"]

    partials = [p for p in json_msgs if p["type"] == "agent_partial_text"]
    audios = [p for p in json_msgs if p["type"] == "agent_audio"]

    assert len(partials) == 3
    assert len(audios) == 3
    assert [p["text"] for p in partials] == ["Hi there.", "How are you?", "Tell me more."]
    assert [p["index"] for p in partials] == [0, 1, 2]
    assert [a["index"] for a in audios] == [0, 1, 2]

    # Each audio[i] follows partial_text[i].
    seq = [t for t in types if t[1] in ("agent_partial_text", "agent_audio")]
    assert seq == [
        ("json", "agent_partial_text"),
        ("json", "agent_audio"),
        ("json", "agent_partial_text"),
        ("json", "agent_audio"),
        ("json", "agent_partial_text"),
        ("json", "agent_audio"),
    ]
    assert "Hi there." in full and "Tell me more." in full


@pytest.mark.asyncio
async def test_stream_agent_turn_tts_error_on_sentence_continues():
    from server.coach import stream_agent_turn

    text = "First one. Second one. Third one."
    calls = {"n": 0}

    async def flaky_synth(t: str, voice: str) -> bytes:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return b"AUDIO"

    ws = FakeWS()
    with patch("server.coach.synthesize_bytes", flaky_synth):
        await stream_agent_turn(ws, text, voice="v", use_llm=False)

    json_msgs = [p for kind, p in ws.sent if kind == "json"]
    errors = [p for p in json_msgs if p["type"] == "agent_error"]
    audios = [p for p in json_msgs if p["type"] == "agent_audio"]
    partials = [p for p in json_msgs if p["type"] == "agent_partial_text"]

    assert len(partials) == 3
    assert len(errors) == 1
    assert errors[0]["index"] == 1
    # Sentences 0 and 2 produced audio; sentence 1 produced an error.
    assert sorted(a["index"] for a in audios) == [0, 2]


@pytest.mark.asyncio
async def test_stream_agent_turn_with_llm_streams_deltas():
    from server.coach import stream_agent_turn

    async def fake_stream(messages, **kw):
        for delta in ["Hello", " world", ". Next", " sentence."]:
            yield delta

    async def fake_synth(t: str, voice: str) -> bytes:
        return b"A"

    ws = FakeWS()
    with patch("server.coach.synthesize_bytes", fake_synth), \
         patch("server.coach.stream_claude", fake_stream):
        await stream_agent_turn(ws, "irrelevant", voice="v", use_llm=True)

    partials = [p["text"] for kind, p in ws.sent if kind == "json" and p["type"] == "agent_partial_text"]
    assert partials == ["Hello world.", "Next sentence."]


def test_streaming_enabled_default_on(monkeypatch):
    from server import coach
    monkeypatch.delenv("SPEAKAGENT_STREAMING", raising=False)
    assert coach.streaming_enabled() is True


def test_streaming_enabled_off(monkeypatch):
    from server import coach
    monkeypatch.setenv("SPEAKAGENT_STREAMING", "off")
    assert coach.streaming_enabled() is False


def test_ws_session_streaming_on_emits_partial_text(monkeypatch):
    """End-to-end via TestClient: with streaming on, first agent turn produces ≥1 agent_partial_text."""
    monkeypatch.setenv("SPEAKAGENT_STREAMING", "on")

    async def fake_synth(text: str, voice: str) -> bytes:
        return b"FAKEMP3"

    # Patch in the place the coach uses it.
    with patch("server.coach.synthesize_bytes", fake_synth):
        # Re-import app fresh so module-level env reads (none here, but safe).
        from server.main import app
        with TestClient(app) as client:
            with client.websocket_connect("/ws/session") as ws:
                seen = []
                # Drain until we see agent_done or hit a hard limit.
                for _ in range(30):
                    msg = ws.receive_json()
                    seen.append(msg["type"])
                    if msg["type"] == "agent_done":
                        break
                    if msg["type"] in ("session_end", "user_prompt"):
                        break
                assert "agent_caption" in seen
                assert "agent_partial_text" in seen
                assert "agent_audio" in seen
                assert "agent_done" in seen


def test_ws_session_streaming_off_emits_no_partial_text(monkeypatch):
    """With streaming off, behavior matches Phase 2 (no agent_partial_text)."""
    monkeypatch.setenv("SPEAKAGENT_STREAMING", "off")

    async def empty_stream(text, voice):
        if False:
            yield b""

    with patch("server.main.synthesize_stream", empty_stream):
        from server.main import app
        with TestClient(app) as client:
            with client.websocket_connect("/ws/session") as ws:
                seen_types = []
                for _ in range(20):
                    msg = ws.receive()
                    if "text" in msg and msg["text"]:
                        import json as _json
                        seen_types.append(_json.loads(msg["text"]).get("type"))
                        if seen_types[-1] in ("agent_done", "user_prompt", "session_end"):
                            break
                assert "agent_partial_text" not in seen_types
                assert "agent_caption" in seen_types
                assert "agent_done" in seen_types
