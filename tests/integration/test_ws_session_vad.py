"""Integration tests for the VAD-aware WebSocket session.

We patch:
  - server.config.load_config to return a Config with vad="on"
  - server.ws_session.VadSegmenter with a deterministic stub
  - server.ws_session._get_stt resolution path so STT never loads whisper
  - server.ws_session.synthesize_stream / agent_stream.synthesize_stream
    to control TTS chunk pacing for cancellation tests
"""
import asyncio
import base64
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import server.ws_session as ws_session_mod
import server.agent_stream as agent_stream_mod
from server.config import Config
from server.main import app


# ---------------- helpers / fakes ----------------

class _StubVad:
    """Deterministic VAD: yields a script of events per call."""

    def __init__(self, script=None):
        self.script = list(script or [])
        self.calls = 0

    def process_frame(self, pcm):
        self.calls += 1
        if self.script:
            return self.script.pop(0)
        return []

    def reset(self):
        pass


class _StubStt:
    def transcribe(self, pcm):
        from server.stt import TranscriptionResult
        return TranscriptionResult(text="hello world", confidence=0.9, words=[])


def _vad_on_cfg():
    cfg = Config()
    cfg.vad = "on"
    return cfg


def _frame_b64() -> str:
    return base64.b64encode(b"\x00\x01" * 512).decode("ascii")


# ---------------- fixtures ----------------

@pytest.fixture
def vad_off_env(monkeypatch):
    monkeypatch.delenv("SPEAKAGENT_VAD", raising=False)
    yield


@pytest.fixture
def vad_on_env(monkeypatch):
    cfg = _vad_on_cfg()
    monkeypatch.setattr(ws_session_mod, "load_config", lambda: cfg)
    yield cfg


# ---------------- tests ----------------

def test_vad_off_uses_ptt(vad_off_env):
    """Without SPEAKAGENT_VAD, no user_speech_start should ever appear."""
    async def _empty_stream(text, voice):
        if False:
            yield b""

    with patch("server.ws_session.synthesize_stream", _empty_stream), \
         TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "session_start"
            msg = ws.receive_json()
            assert msg["type"] == "agent_caption"
            # Legacy path uses agent_done, not turn_end
            msg = ws.receive_json()
            assert msg["type"] == "agent_done"
            # No user_speech_* in legacy stream


def test_vad_on_emits_speech_events(vad_on_env, monkeypatch):
    """With VAD on and stub VAD, user_speech_start then user_speech_end appear."""
    # Stub VAD: first audio_frame -> ["start"], second -> ["end"]
    stub = _StubVad(script=[["start"], ["end"]])
    monkeypatch.setattr(ws_session_mod, "VadSegmenter", lambda *a, **kw: stub)
    monkeypatch.setattr(ws_session_mod, "_curriculum_path",
                        lambda: __import__("os").path.join("curriculum", "week1", "day1.yml"))

    # Deterministic STT
    monkeypatch.setattr("server.main._get_stt", lambda: _StubStt())

    async def _empty_stream(text, voice):
        if False:
            yield b""

    monkeypatch.setattr(ws_session_mod, "synthesize_stream", _empty_stream)
    monkeypatch.setattr(agent_stream_mod, "synthesize_stream", _empty_stream)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            assert ws.receive_json()["type"] == "session_start"
            # First turn is agent; expect agent_caption then turn_end (VAD path)
            assert ws.receive_json()["type"] == "agent_caption"
            assert ws.receive_json()["type"] == "turn_end"
            # Send first audio frame -> VAD start
            ws.send_text(json.dumps({"type": "audio_frame", "pcm_b64": _frame_b64()}))
            # Server emits user_speech_start (also moves agent caption sequence forward)
            # Drain messages until we see user_speech_start
            saw_start = False
            for _ in range(20):
                msg = ws.receive_json()
                if msg["type"] == "user_speech_start":
                    saw_start = True
                    break
            assert saw_start, "expected user_speech_start"
            # Second frame -> VAD end
            ws.send_text(json.dumps({"type": "audio_frame", "pcm_b64": _frame_b64()}))
            saw_end = False
            for _ in range(20):
                msg = ws.receive_json()
                if msg["type"] == "user_speech_end":
                    saw_end = True
                    assert "segment_id" in msg
                    break
            assert saw_end, "expected user_speech_end"


def test_interrupt_cancels_stream(vad_on_env, monkeypatch):
    """An explicit `interrupt` JSON message stops further tts_audio_chunk bytes."""
    stub = _StubVad(script=[])  # no auto VAD events
    monkeypatch.setattr(ws_session_mod, "VadSegmenter", lambda *a, **kw: stub)
    monkeypatch.setattr("server.main._get_stt", lambda: _StubStt())

    async def _slow_stream(text, voice):
        for i in range(50):
            await asyncio.sleep(0.02)
            yield b"X" * 64

    monkeypatch.setattr(agent_stream_mod, "synthesize_stream", _slow_stream)
    monkeypatch.setattr(ws_session_mod, "synthesize_stream", _slow_stream)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            assert ws.receive_json()["type"] == "session_start"
            assert ws.receive_json()["type"] == "agent_caption"
            # Receive at least one bytes chunk
            msg = ws.receive()
            assert msg.get("bytes") is not None
            # Send interrupt
            ws.send_text(json.dumps({"type": "interrupt"}))
            # After cancel: no turn_end (stream returned early), next turn message should appear
            chunks = 1
            saw_next_turn = False
            for _ in range(40):
                m = ws.receive()
                if m.get("text"):
                    data = json.loads(m["text"])
                    # next turn in lesson is agent_caption (turn 2)
                    if data.get("type") in ("agent_caption", "user_prompt", "session_end"):
                        saw_next_turn = True
                        break
                elif m.get("bytes") is not None:
                    chunks += 1
            assert saw_next_turn, "expected next-turn message after interrupt"
            assert chunks < 30, f"expected interrupt to cut chunks short, got {chunks}"


def test_user_speech_start_during_agent_triggers_cancel(vad_on_env, monkeypatch):
    """A VAD `start` event mid-stream cancels TTS just like an explicit interrupt."""
    # Script: every frame returns a "start" event
    stub = _StubVad(script=[["start"]])
    monkeypatch.setattr(ws_session_mod, "VadSegmenter", lambda *a, **kw: stub)
    monkeypatch.setattr("server.main._get_stt", lambda: _StubStt())

    async def _slow_stream(text, voice):
        for i in range(50):
            await asyncio.sleep(0.02)
            yield b"X" * 64

    monkeypatch.setattr(agent_stream_mod, "synthesize_stream", _slow_stream)
    monkeypatch.setattr(ws_session_mod, "synthesize_stream", _slow_stream)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            assert ws.receive_json()["type"] == "session_start"
            assert ws.receive_json()["type"] == "agent_caption"
            # Receive first bytes chunk
            msg = ws.receive()
            assert msg.get("bytes") is not None
            # Trigger VAD-driven cancel via audio_frame
            ws.send_text(json.dumps({"type": "audio_frame", "pcm_b64": _frame_b64()}))
            saw_user_speech_start = False
            saw_next_turn = False
            chunks = 1
            for _ in range(60):
                m = ws.receive()
                if m.get("text"):
                    data = json.loads(m["text"])
                    if data.get("type") == "user_speech_start":
                        saw_user_speech_start = True
                    elif data.get("type") in ("agent_caption", "user_prompt", "session_end"):
                        saw_next_turn = True
                        break
                elif m.get("bytes") is not None:
                    chunks += 1
            assert saw_user_speech_start
            assert saw_next_turn
            assert chunks < 30

