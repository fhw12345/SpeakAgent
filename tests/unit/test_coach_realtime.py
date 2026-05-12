"""Unit tests for server.coach_realtime (Phase 2)."""
import os

import pytest

os.environ["LLM_MOCK"] = "1"

from server import coach_realtime, llm_client
from server.lesson_loader import LessonSpec, load


@pytest.fixture(autouse=True)
def _reset():
    coach_realtime.reset_sessions_for_test()
    llm_client.clear_mock_responses()
    yield
    coach_realtime.reset_sessions_for_test()
    llm_client.clear_mock_responses()


def _spec() -> LessonSpec:
    return load("w1d2")


def test_start_session_calls_llm_and_returns_utterance():
    llm_client.set_mock_responses(["Hi! Tell me about a tool you use."])
    sid, first = coach_realtime.start_session(_spec())
    assert sid and isinstance(sid, str)
    assert first == "Hi! Tell me about a tool you use."


def test_handle_turn_appends_history():
    llm_client.set_mock_responses(["intro?", "good — and what about APIs?"])
    sid, _ = coach_realtime.start_session(_spec())
    out = coach_realtime.handle_turn(sid, "I use grep every day.")
    assert out["agent_utterance"] == "good — and what about APIs?"
    assert out["turn_index"] == 1
    assert out["done"] is False
    sess = coach_realtime._SESSIONS[sid]
    roles = [m["role"] for m in sess.history]
    assert roles == ["assistant", "user", "assistant"]


def test_done_after_max_user_turns():
    canned = ["start"] + [f"reply {i}" for i in range(coach_realtime.MAX_USER_TURNS)]
    llm_client.set_mock_responses(canned)
    sid, _ = coach_realtime.start_session(_spec())
    out = None
    for i in range(coach_realtime.MAX_USER_TURNS):
        out = coach_realtime.handle_turn(sid, f"user msg {i}")
    assert out is not None
    assert out["turn_index"] == coach_realtime.MAX_USER_TURNS
    assert out["done"] is True


def test_done_on_end_sentinel():
    llm_client.set_mock_responses(["start", f"good job {coach_realtime.END_SENTINEL}"])
    sid, _ = coach_realtime.start_session(_spec())
    out = coach_realtime.handle_turn(sid, "any user text")
    assert out["done"] is True
    assert coach_realtime.END_SENTINEL not in out["agent_utterance"]
    assert "good job" in out["agent_utterance"]


def test_unknown_session_raises_keyerror():
    with pytest.raises(KeyError):
        coach_realtime.handle_turn("does-not-exist", "hello")


def test_start_session_rejects_scripted_lesson():
    spec = load("w1d1")
    with pytest.raises(ValueError):
        coach_realtime.start_session(spec)
