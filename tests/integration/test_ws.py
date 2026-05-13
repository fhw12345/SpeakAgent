from unittest.mock import patch
from fastapi.testclient import TestClient
from server.main import app


async def _empty_stream(text, voice):
    if False:
        yield b""


def test_ws_session_emits_session_start_and_agent_caption(monkeypatch):
    # Phase-2 behavior: explicit non-streaming mode + VAD off.
    monkeypatch.setenv("SPEAKAGENT_STREAMING", "off")
    monkeypatch.setenv("SPEAKAGENT_VAD", "off")
    with patch("server.ws_session.synthesize_stream", _empty_stream), \
         TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "session_start"
            msg = ws.receive_json()
            assert msg["type"] == "agent_caption"
            assert "welcome" in msg["text"].lower() or "Welcome" in msg["text"]
