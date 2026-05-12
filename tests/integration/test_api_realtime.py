"""Integration tests for /api/lesson/start and /api/lesson/turn (realtime mode)."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from server import coach_realtime
from server.main import app


client = TestClient(app)


def setup_function(_):
    coach_realtime._reset_sessions_for_test()


def test_start_w1d2_returns_realtime_mode():
    with patch("server.coach_realtime.call_with_fallback", return_value="Welcome to W1D2."):
        resp = client.post("/api/lesson/start", json={"lesson_id": "w1d2"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "realtime"
    assert body["session_id"]
    assert body["first_agent_utterance"] == "Welcome to W1D2."


def test_start_w1d1_returns_scripted_mode():
    resp = client.post("/api/lesson/start", json={"lesson_id": "w1d1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "scripted"
    assert "Welcome to your first day" in body["first_agent_utterance"]


def test_three_turn_flow_with_mock_llm():
    replies = ["opener", "r1", "r2", "r3"]
    with patch("server.coach_realtime.call_with_fallback", side_effect=replies):
        start = client.post("/api/lesson/start", json={"lesson_id": "w1d2"}).json()
        sid = start["session_id"]
        out1 = client.post("/api/lesson/turn", json={"session_id": sid, "user_text": "u1"}).json()
        out2 = client.post("/api/lesson/turn", json={"session_id": sid, "user_text": "u2"}).json()
        out3 = client.post("/api/lesson/turn", json={"session_id": sid, "user_text": "u3"}).json()
    assert [out1["agent_utterance"], out2["agent_utterance"], out3["agent_utterance"]] == ["r1", "r2", "r3"]
    assert [out1["turn_index"], out2["turn_index"], out3["turn_index"]] == [1, 2, 3]
    assert out3["done"] is False


def test_unknown_session_returns_404():
    resp = client.post("/api/lesson/turn", json={"session_id": "nope", "user_text": "hi"})
    assert resp.status_code == 404


def test_unknown_lesson_returns_404():
    resp = client.post("/api/lesson/start", json={"lesson_id": "W9D9"})
    assert resp.status_code == 404
