"""Integration tests for VAD WS flow + interrupt cancellation.

Stubs out silero-vad by patching the lazy detector factory so we don't
need the model in CI. Stubs out STT with a fixed transcription, and TTS
with a slow stream so we can observe cancellation.
"""
import asyncio
import json
import os
import time
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from server.stt import TranscriptionResult


def _stub_detector_factory():
    def _detect(frame):
        return 1.0 if float(np.max(np.abs(frame))) > 0.1 else 0.0
    return _detect


async def _slow_tts_stream(text, voice):
    # Yield 20 chunks slowly so we have time to cancel.
    for _ in range(20):
        await asyncio.sleep(0.05)
        yield b"\x00" * 256


async def _empty_tts_stream(text, voice):
    if False:
        yield b""


def _fake_transcribe(self, pcm):
    return TranscriptionResult(text="hello", confidence=0.9, words=[], language="en")


def _speech_bytes(n_frames=8, value=20000):
    return np.full(512 * n_frames, value, dtype=np.int16).tobytes()


def _silence_bytes(n_frames=20):
    return np.zeros(512 * n_frames, dtype=np.int16).tobytes()


@pytest.fixture(autouse=True)
def _patch_vad():
    with patch("server.vad._silero_detector_factory", _stub_detector_factory):
        yield


@pytest.fixture
def vad_on(monkeypatch):
    monkeypatch.setenv("SPEAKAGENT_VAD", "on")


@pytest.fixture
def vad_off(monkeypatch):
    monkeypatch.setenv("SPEAKAGENT_VAD", "off")


def test_config_endpoint_reflects_vad(monkeypatch):
    from server.main import app
    monkeypatch.setenv("SPEAKAGENT_VAD", "on")
    with TestClient(app) as client:
        assert client.get("/api/config").json() == {"vad": "on"}
    monkeypatch.setenv("SPEAKAGENT_VAD", "off")
    with TestClient(app) as client:
        assert client.get("/api/config").json() == {"vad": "off"}


def test_vad_off_uses_ptt(vad_off):
    from server.main import app
    fake_judge = '{"content_score": 5, "rewrite": "hello", "issues": []}'
    with patch("server.main.synthesize_stream", _empty_tts_stream), \
         patch("server.stt.SttEngine.transcribe", _fake_transcribe), \
         patch("server.scorer.call_with_fallback", return_value=fake_judge), \
         TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            speech_seen = False
            for _ in range(40):
                msg = ws.receive()
                if "text" in msg and msg["text"]:
                    data = json.loads(msg["text"])
                    if data["type"] == "user_speech_start":
                        speech_seen = True
                    elif data["type"] == "user_prompt":
                        ws.send_bytes(b"\x00\x00" * 16000)
                        ws.send_text(json.dumps({"type": "user_audio_end"}))
                    elif data["type"] == "session_end":
                        break
            assert speech_seen is False


def test_vad_on_emits_speech_events(vad_on):
    from server.main import app
    fake_judge = '{"content_score": 5, "rewrite": "hello", "issues": []}'
    with patch("server.main.synthesize_stream", _empty_tts_stream), \
         patch("server.stt.SttEngine.transcribe", _fake_transcribe), \
         patch("server.scorer.call_with_fallback", return_value=fake_judge), \
         TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            saw_start = saw_end = False
            sent_speech = False
            for _ in range(80):
                msg = ws.receive()
                if "text" in msg and msg["text"]:
                    data = json.loads(msg["text"])
                    if data["type"] == "user_prompt" and not sent_speech:
                        ws.send_bytes(_speech_bytes(8))
                        ws.send_bytes(_silence_bytes(20))
                        sent_speech = True
                    elif data["type"] == "user_speech_start":
                        saw_start = True
                    elif data["type"] == "user_speech_end":
                        saw_end = True
                    elif data["type"] == "session_end":
                        break
                    elif data["type"] == "score" and saw_start and saw_end:
                        break
            assert saw_start
            assert saw_end


def test_interrupt_cancels_agent_stream(vad_on):
    from server.main import app
    fake_judge = '{"content_score": 5, "rewrite": "hello", "issues": []}'
    with patch("server.main.synthesize_stream", _slow_tts_stream), \
         patch("server.stt.SttEngine.transcribe", _fake_transcribe), \
         patch("server.scorer.call_with_fallback", return_value=fake_judge), \
         TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            cancelled = None
            for _ in range(200):
                msg = ws.receive()
                if "text" in msg and msg["text"]:
                    data = json.loads(msg["text"])
                    if data["type"] == "agent_caption":
                        # Send interrupt right after the first caption.
                        ws.send_text(json.dumps({"type": "interrupt"}))
                    elif data["type"] == "agent_done":
                        cancelled = data.get("cancelled")
                        break
                    elif data["type"] == "session_end":
                        break
            assert cancelled is True


def test_speech_start_during_agent_triggers_cancel(vad_on):
    from server.main import app
    fake_judge = '{"content_score": 5, "rewrite": "hello", "issues": []}'
    with patch("server.main.synthesize_stream", _slow_tts_stream), \
         patch("server.stt.SttEngine.transcribe", _fake_transcribe), \
         patch("server.scorer.call_with_fallback", return_value=fake_judge), \
         TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            cancelled = None
            sent = False
            for _ in range(200):
                msg = ws.receive()
                if "text" in msg and msg["text"]:
                    data = json.loads(msg["text"])
                    if data["type"] == "agent_caption" and not sent:
                        ws.send_bytes(_speech_bytes(8))
                        sent = True
                    elif data["type"] == "agent_done":
                        cancelled = data.get("cancelled")
                        break
                    elif data["type"] == "session_end":
                        break
            assert cancelled is True
