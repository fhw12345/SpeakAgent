"""Drives a full WS session with mocked STT and TTS so it runs in CI without a mic."""
import json
from unittest.mock import patch
import numpy as np

from fastapi.testclient import TestClient
from server.main import app
from server.stt import TranscriptionResult


async def _empty_stream(text, voice):
    if False:
        yield b""


def _fake_transcribe(self, pcm):
    return TranscriptionResult(
        text="Hello and welcome to the interview.",
        confidence=0.92,
        words=[{"w": w, "start": i*0.3, "end": i*0.3+0.25, "prob": 0.95}
               for i, w in enumerate("Hello and welcome to the interview".split())],
        language="en",
    )


def test_full_session_round_trip():
    fake_judge = '{"content_score": 5, "rewrite": "Hello and welcome to the interview.", "issues": []}'
    with patch("server.main.synthesize_stream", _empty_stream), \
         patch("server.stt.SttEngine.transcribe", _fake_transcribe), \
         patch("server.scorer.call_with_fallback", return_value=fake_judge), \
         TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            saw_session_start = False
            saw_session_end = False
            scores_seen = 0
            for _ in range(40):
                msg = ws.receive()
                if "text" in msg and msg["text"]:
                    data = json.loads(msg["text"])
                    if data["type"] == "session_start":
                        saw_session_start = True
                    elif data["type"] == "user_prompt":
                        ws.send_bytes(b"\x00\x00" * 16000)
                        ws.send_text(json.dumps({"type": "user_audio_end"}))
                    elif data["type"] == "score":
                        scores_seen += 1
                        assert data["score"]["content_score"] == 5
                    elif data["type"] == "session_end":
                        saw_session_end = True
                        break
            assert saw_session_start
            assert saw_session_end
            assert scores_seen >= 1
