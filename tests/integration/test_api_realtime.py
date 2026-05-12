"""Integration tests for /api/lesson/start and /api/lesson/turn (Phase 2)."""
import os

os.environ["LLM_MOCK"] = "1"

from fastapi.testclient import TestClient

from server import coach as coach_dispatch
from server import llm_client
from server.main import app


def _setup():
    coach_dispatch.reset_rest_sessions_for_test()
    llm_client.clear_mock_responses()


def test_start_w1d2_returns_realtime_mode():
    _setup()
    llm_client.set_mock_responses(["Welcome! What tool did you use today?"])
    with TestClient(app) as client:
        r = client.post("/api/lesson/start", json={"lesson_id": "w1d2"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "realtime"
    assert body["session_id"]
    assert body["first_agent_utterance"] == "Welcome! What tool did you use today?"


def test_start_w1d1_returns_scripted_mode():
    _setup()
    with TestClient(app) as client:
        r = client.post("/api/lesson/start", json={"lesson_id": "w1d1"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "scripted"
    assert "Welcome to your first day" in body["first_agent_utterance"]


def test_three_turn_flow_with_mock_llm():
    _setup()
    llm_client.set_mock_responses([
        "Hi! Tell me about a tool.",
        "Nice — and how does it return data?",
        "Got it. What about APIs?",
        "Great, can you say that as a sentence?",
    ])
    with TestClient(app) as client:
        start = client.post("/api/lesson/start", json={"lesson_id": "w1d2"}).json()
        sid = start["session_id"]
        utterances = [start["first_agent_utterance"]]
        for user_text in ["I use grep.", "It prints lines.", "An API returns JSON."]:
            r = client.post("/api/lesson/turn", json={"session_id": sid, "user_text": user_text})
            assert r.status_code == 200
            body = r.json()
            assert body["done"] is False
            utterances.append(body["agent_utterance"])
    assert len(utterances) == 4
    assert len(set(utterances)) == 4


def test_turn_unknown_session_returns_404():
    _setup()
    with TestClient(app) as client:
        r = client.post("/api/lesson/turn", json={"session_id": "nope", "user_text": "hi"})
    assert r.status_code == 404


def test_get_today_still_works():
    """Regression: existing scripted endpoint untouched."""
    with TestClient(app) as client:
        r = client.get("/api/today")
    assert r.status_code == 200
    assert r.json()["id"] == "w1d1"
