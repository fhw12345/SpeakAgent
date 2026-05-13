"""Integration tests for POST /api/lesson/start and /api/lesson/turn."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server import coach_realtime, llm_client
from server.main import app


@pytest.fixture(autouse=True)
def _clear_sessions():
    coach_realtime._reset_for_tests()
    llm_client._reset_mock()
    yield
    coach_realtime._reset_for_tests()
    llm_client._reset_mock()


def test_start_w1d2_returns_realtime_mode():
    with patch("server.coach_realtime.generate", return_value="Hi! What is an API?"):
        client = TestClient(app)
        r = client.post("/api/lesson/start", json={"lesson_id": "w1d2"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "realtime"
    assert body["session_id"]
    assert body["first_agent_utterance"] == "Hi! What is an API?"


def test_start_w1d1_returns_scripted_first_say():
    client = TestClient(app)
    r = client.post("/api/lesson/start", json={"lesson_id": "w1d1"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "scripted"
    assert "Welcome to your first day" in body["first_agent_utterance"]


def test_three_turn_flow_with_mock_llm():
    replies = iter([
        "Hi! What is an API?",
        "Good. Why use authentication?",
        "Right. What is a webhook?",
        "Nice. When would you use one?",
    ])
    with patch("server.coach_realtime.generate", side_effect=lambda *a, **kw: next(replies)):
        client = TestClient(app)
        r = client.post("/api/lesson/start", json={"lesson_id": "w1d2"})
        sid = r.json()["session_id"]

        utterances = []
        for i, user_text in enumerate(["An API is an interface.", "To verify identity.", "An HTTP callback."]):
            tr = client.post("/api/lesson/turn", json={"session_id": sid, "user_text": user_text})
            assert tr.status_code == 200
            d = tr.json()
            utterances.append(d["agent_utterance"])
            assert d["turn_index"] == i + 1
            assert d["done"] is False

    assert len(set(utterances)) == 3, f"expected 3 distinct utterances, got {utterances}"


def test_turn_unknown_session_returns_404():
    client = TestClient(app)
    r = client.post("/api/lesson/turn", json={"session_id": "missing", "user_text": "hi"})
    assert r.status_code == 404
