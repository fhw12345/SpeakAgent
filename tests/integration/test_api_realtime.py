"""Integration tests for the realtime lesson REST endpoints."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server import coach_realtime
from server.main import app


@pytest.fixture(autouse=True)
def _reset():
    coach_realtime.reset_sessions()
    yield
    coach_realtime.reset_sessions()


@pytest.fixture
def client():
    return TestClient(app)


def test_start_w1d2_returns_realtime_mode(client):
    with patch("server.coach_realtime.generate", return_value="Hello, what's an API?"):
        r = client.post("/api/lesson/start", json={"lesson_id": "w1d2"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "realtime"
    assert body["session_id"]
    assert body["first_agent_utterance"] == "Hello, what's an API?"


def test_start_unknown_lesson_returns_404(client):
    r = client.post("/api/lesson/start", json={"lesson_id": "wXdY"})
    assert r.status_code == 404


def test_start_scripted_w1d1(client):
    r = client.post("/api/lesson/start", json={"lesson_id": "w1d1"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "scripted"
    assert body["first_agent_utterance"].startswith("Welcome to your first day")


def test_three_turn_flow_with_mock_llm(client):
    canned = [
        "Hello! What's an API?",
        "Good. What's a tool?",
        "Nice. How does the agent decide?",
        "Great explanation.",
    ]
    with patch("server.coach_realtime.generate", side_effect=canned):
        start = client.post("/api/lesson/start", json={"lesson_id": "w1d2"}).json()
        sid = start["session_id"]
        replies = []
        for u in ["An API is a set of endpoints.", "A tool is a callable function.", "Based on the user's request."]:
            r = client.post("/api/lesson/turn", json={"session_id": sid, "user_text": u})
            assert r.status_code == 200, r.text
            replies.append(r.json())
    assert [x["agent_utterance"] for x in replies] == canned[1:]
    assert [x["turn_index"] for x in replies] == [1, 2, 3]
    assert all(x["done"] is False for x in replies)


def test_turn_unknown_session_404(client):
    r = client.post("/api/lesson/turn", json={"session_id": "missing", "user_text": "hi"})
    assert r.status_code == 404


def test_turn_done_after_max(client):
    canned = ["start"] + [f"r{i}" for i in range(coach_realtime.MAX_USER_TURNS)]
    with patch("server.coach_realtime.generate", side_effect=canned):
        start = client.post("/api/lesson/start", json={"lesson_id": "w1d2"}).json()
        sid = start["session_id"]
        last = None
        for i in range(coach_realtime.MAX_USER_TURNS):
            last = client.post("/api/lesson/turn", json={"session_id": sid, "user_text": f"u{i}"}).json()
    assert last["done"] is True
    assert last["turn_index"] == coach_realtime.MAX_USER_TURNS
