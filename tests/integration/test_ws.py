from unittest.mock import patch
from fastapi.testclient import TestClient
from server.main import app


async def _empty_stream(text, voice):
    if False:
        yield b""


def test_ws_session_emits_session_start_and_agent_caption(monkeypatch):
    # This test exercises the Phase 2 (non-streaming) caption path which sends
    # the lesson 'say' text up front. Force streaming off so the assertion on
    # caption text content holds regardless of the global default.
    monkeypatch.setenv("SPEAKAGENT_STREAMING", "off")
    with patch("server.main.synthesize_stream", _empty_stream), \
         TestClient(app) as client:
        with client.websocket_connect("/ws/session") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "session_start"
            msg = ws.receive_json()
            assert msg["type"] == "agent_caption"
            assert "welcome" in msg["text"].lower() or "Welcome" in msg["text"]
