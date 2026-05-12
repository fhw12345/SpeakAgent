"""Integration tests for the streaming agent-turn path.

Mocks `stream_claude` and `synthesize_bytes` so the test runs entirely in
process. Exercises the flag branch: streaming on, streaming off, and a
TTS error on a single sentence.
"""
from __future__ import annotations

import os
from typing import AsyncIterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def _drain_until_done(ws):
    """Receive messages until we see agent_done. Returns list of all received frames.

    Each frame is a tuple (kind, payload) where kind ∈ {'json', 'bytes'}.
    """
    frames: list[tuple[str, object]] = []
    while True:
        msg = ws.receive()
        if "text" in msg and msg["text"] is not None:
            import json
            payload = json.loads(msg["text"])
            frames.append(("json", payload))
            if payload.get("type") == "agent_done":
                return frames
        elif "bytes" in msg and msg["bytes"] is not None:
            frames.append(("bytes", msg["bytes"]))


async def _fake_stream_claude_three(messages, **kwargs):
    for chunk in ["Hi there. ", "How are you", "? Tell me", " more."]:
        yield chunk


async def _fake_stream_claude_one(messages, **kwargs):
    yield "Just one sentence here."


async def _fake_synth_ok(text: str, voice: str) -> bytes:
    return b"AUDIO:" + text.encode("utf-8")[:8]


_call_count = {"n": 0}


async def _fake_synth_fail_second(text: str, voice: str) -> bytes:
    _call_count["n"] += 1
    if _call_count["n"] == 2:
        raise RuntimeError("simulated_tts_failure")
    return b"AUDIO:" + text.encode("utf-8")[:8]


def _build_client():
    from server.main import app
    return TestClient(app)


def test_streaming_on_emits_partial_text_and_audio_per_sentence(monkeypatch):
    monkeypatch.setenv("SPEAKAGENT_STREAMING", "on")
    with patch("server.coach.stream_claude", _fake_stream_claude_three), \
         patch("server.coach.synthesize_bytes", _fake_synth_ok), \
         _build_client() as client:
        with client.websocket_connect("/ws/session") as ws:
            assert ws.receive_json()["type"] == "session_start"
            assert ws.receive_json()["type"] == "agent_caption"
            frames = _drain_until_done(ws)

    partials = [p for k, p in frames if k == "json" and p.get("type") == "agent_partial_text"]
    audios = [b for k, b in frames if k == "bytes"]
    dones = [p for k, p in frames if k == "json" and p.get("type") == "agent_done"]

    assert len(partials) == 3, f"expected 3 partials, got {len(partials)}: {partials}"
    assert [p["text"] for p in partials] == ["Hi there.", "How are you?", "Tell me more."]
    assert [p["index"] for p in partials] == [0, 1, 2]
    assert len(audios) == 3, f"expected 3 audio frames, got {len(audios)}"
    assert len(dones) == 1

    json_only = [(k, p) for k, p in frames if k == "json"]
    for i, (_, p) in enumerate(json_only):
        if p.get("type") == "agent_partial_text" and p["index"] < 2:
            next_audio_seen = False
            for j in range(frames.index((_, p)) + 1, len(frames)):
                kind, payload = frames[j]
                if kind == "bytes":
                    next_audio_seen = True
                    break
                if kind == "json" and payload.get("type") == "agent_partial_text":
                    break
            assert next_audio_seen, f"no audio between partial {p['index']} and next partial"


def test_streaming_off_no_partial_text(monkeypatch):
    monkeypatch.setenv("SPEAKAGENT_STREAMING", "off")

    async def _stream(text, voice):
        yield b"FALLBACK_AUDIO"

    with patch("server.main.synthesize_stream", _stream), \
         _build_client() as client:
        with client.websocket_connect("/ws/session") as ws:
            assert ws.receive_json()["type"] == "session_start"
            assert ws.receive_json()["type"] == "agent_caption"
            frames = _drain_until_done(ws)

    partials = [p for k, p in frames if k == "json" and p.get("type") == "agent_partial_text"]
    audios = [b for k, b in frames if k == "bytes"]
    dones = [p for k, p in frames if k == "json" and p.get("type") == "agent_done"]

    assert partials == []
    assert audios == [b"FALLBACK_AUDIO"]
    assert len(dones) == 1
    assert "full_text" not in dones[0] or dones[0].get("full_text") in ("", None)


def test_streaming_tts_error_on_one_sentence_continues(monkeypatch):
    monkeypatch.setenv("SPEAKAGENT_STREAMING", "on")
    _call_count["n"] = 0
    with patch("server.coach.stream_claude", _fake_stream_claude_three), \
         patch("server.coach.synthesize_bytes", _fake_synth_fail_second), \
         _build_client() as client:
        with client.websocket_connect("/ws/session") as ws:
            assert ws.receive_json()["type"] == "session_start"
            assert ws.receive_json()["type"] == "agent_caption"
            frames = _drain_until_done(ws)

    errors = [p for k, p in frames if k == "json" and p.get("type") == "agent_error"]
    partials = [p for k, p in frames if k == "json" and p.get("type") == "agent_partial_text"]
    dones = [p for k, p in frames if k == "json" and p.get("type") == "agent_done"]

    assert len(partials) == 3
    assert len(errors) == 1
    assert errors[0]["index"] == 1
    assert "tts_failed" in errors[0]["detail"]
    assert len(dones) == 1
