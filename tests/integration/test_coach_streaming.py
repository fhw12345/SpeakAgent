"""Integration tests for the streaming agent-turn WS flow (Phase 3)."""
from __future__ import annotations

import os
from typing import AsyncIterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server import coach as coach_mod
from server.main import app


def _gen(text: str):
    async def _stream(turn) -> AsyncIterator[str]:
        # Yield a few small chunks so the splitter sees deltas accumulate.
        for piece in [text[i : i + 6] for i in range(0, len(text), 6)]:
            yield piece
    return _stream


async def _fake_tts(text: str, voice: str) -> bytes:
    return b"\x00\x01" + text.encode("utf-8")[:4]


def _set_env(monkeypatch, value: str):
    monkeypatch.setenv("SPEAKAGENT_STREAMING", value)


def _drain_until(ws, target_type: str, max_msgs: int = 200):
    """Consume messages until we see one of `target_type`. Return the list of
    every JSON message seen (in order)."""
    seen: list[dict] = []
    for _ in range(max_msgs):
        m = ws.receive()
        if "text" in m and m["text"] is not None:
            import json
            obj = json.loads(m["text"])
            seen.append(obj)
            if obj.get("type") == target_type:
                return seen
        # ignore binary frames in streaming mode (none expected)
    raise AssertionError(f"never saw {target_type}; got types={[s.get('type') for s in seen]}")


def test_streaming_emits_partial_text_then_audio_then_done(monkeypatch):
    _set_env(monkeypatch, "on")
    text = "Hi there. How are you? Tell me more."
    monkeypatch.setattr(coach_mod, "stream_source", _gen(text))
    monkeypatch.setattr(coach_mod, "tts_bytes", _fake_tts)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            assert ws.receive_json()["type"] == "session_start"
            # First agent turn
            assert ws.receive_json()["type"] == "agent_caption"
            seen = _drain_until(ws, "agent_done")

    types = [s["type"] for s in seen]
    partials = [s for s in seen if s["type"] == "agent_partial_text"]
    audios = [s for s in seen if s["type"] == "agent_audio"]
    done = [s for s in seen if s["type"] == "agent_done"]

    assert len(partials) == 3, f"expected 3 partials, got {types}"
    assert len(audios) == 3, f"expected 3 audios, got {types}"
    assert len(done) == 1
    # Ordering: partial_text[i] precedes audio[i]
    for i, p in enumerate(partials):
        p_pos = seen.index(p)
        a_pos = next(j for j, m in enumerate(seen) if m["type"] == "agent_audio" and m["index"] == i)
        assert p_pos < a_pos, f"audio[{i}] not after partial[{i}]"


def test_non_streaming_emits_no_partial_text(monkeypatch):
    _set_env(monkeypatch, "off")

    async def _empty_stream(text, voice):
        if False:
            yield b""

    with patch("server.main.synthesize_stream", _empty_stream), TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            assert ws.receive_json()["type"] == "session_start"
            assert ws.receive_json()["type"] == "agent_caption"
            # Drain until agent_done; should see zero agent_partial_text.
            saw_partial = False
            for _ in range(50):
                m = ws.receive()
                if "text" in m and m["text"] is not None:
                    import json
                    obj = json.loads(m["text"])
                    if obj.get("type") == "agent_partial_text":
                        saw_partial = True
                    if obj.get("type") == "agent_done":
                        break
            assert not saw_partial


def test_tts_error_emits_agent_error_and_continues(monkeypatch):
    _set_env(monkeypatch, "on")
    text = "Sentence one. Sentence two. Sentence three."
    monkeypatch.setattr(coach_mod, "stream_source", _gen(text))

    calls = {"n": 0}

    async def _flaky_tts(text: str, voice: str) -> bytes:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("synthetic-tts-failure")
        return b"\x00"
    monkeypatch.setattr(coach_mod, "tts_bytes", _flaky_tts)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            assert ws.receive_json()["type"] == "session_start"
            assert ws.receive_json()["type"] == "agent_caption"
            seen = _drain_until(ws, "agent_done")

    errors = [s for s in seen if s["type"] == "agent_error"]
    assert len(errors) == 1
    assert errors[0]["index"] == 1
    # Turn still ends with agent_done.
    assert seen[-1]["type"] == "agent_done"
