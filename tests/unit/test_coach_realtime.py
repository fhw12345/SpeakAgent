"""Unit tests for server.coach_realtime."""
from pathlib import Path
from unittest.mock import patch

import pytest

from server import coach_realtime
from server.lesson import load_lesson


REPO = Path(__file__).resolve().parents[2]
W1D2_PATH = REPO / "curriculum" / "week1" / "day2.yml"


@pytest.fixture(autouse=True)
def _clean_sessions():
    coach_realtime._reset_sessions_for_test()
    yield
    coach_realtime._reset_sessions_for_test()


@pytest.fixture
def lesson():
    return load_lesson(str(W1D2_PATH))


def test_start_session_calls_llm_and_returns_utterance(lesson):
    with patch("server.coach_realtime.call_with_fallback", return_value="Hello, learner!") as m:
        sid, first = coach_realtime.start_session(lesson)
    assert isinstance(sid, str) and len(sid) > 0
    assert first == "Hello, learner!"
    assert m.call_count == 1
    args, kwargs = m.call_args
    assert "tools and APIs" in kwargs["system"]
    assert "Begin the lesson" in kwargs["prompt"]


def test_handle_turn_appends_history(lesson):
    with patch("server.coach_realtime.call_with_fallback") as m:
        m.side_effect = ["Coach hi.", "Coach reply 1."]
        sid, _ = coach_realtime.start_session(lesson)
        out = coach_realtime.handle_turn(sid, "Tools help.")
    assert out["agent_utterance"] == "Coach reply 1."
    assert out["turn_index"] == 1
    assert out["done"] is False
    state = coach_realtime._SESSIONS[sid]
    roles = [m["role"] for m in state["history"]]
    assert roles == ["assistant", "user", "assistant"]
    assert state["history"][1]["content"] == "Tools help."


def test_done_after_max_user_turns(lesson):
    with patch("server.coach_realtime.call_with_fallback", return_value="ok."):
        sid, _ = coach_realtime.start_session(lesson)
        for i in range(coach_realtime.MAX_USER_TURNS - 1):
            out = coach_realtime.handle_turn(sid, f"u{i}")
            assert out["done"] is False
        out = coach_realtime.handle_turn(sid, "final")
    assert out["turn_index"] == coach_realtime.MAX_USER_TURNS
    assert out["done"] is True


def test_done_on_end_sentinel(lesson):
    with patch("server.coach_realtime.call_with_fallback") as m:
        m.side_effect = ["start", f"goodbye {coach_realtime.END_SENTINEL}"]
        sid, _ = coach_realtime.start_session(lesson)
        out = coach_realtime.handle_turn(sid, "ok")
    assert out["done"] is True
    assert coach_realtime.END_SENTINEL in out["agent_utterance"]


def test_unknown_session_raises_keyerror():
    with pytest.raises(KeyError):
        coach_realtime.handle_turn("does-not-exist", "hi")


def test_start_session_rejects_scripted_lesson():
    from server.lesson import LessonPlan
    plan = LessonPlan(id="x", title="t", week=1, turns=[], mode="scripted")
    with pytest.raises(ValueError, match="realtime"):
        coach_realtime.start_session(plan)


def test_system_prompt_contains_persona_topic_phrases_vocab(lesson):
    sys_prompt = coach_realtime._build_system_prompt(lesson)
    assert "tools and APIs" in sys_prompt
    assert "warm" in sys_prompt.lower() or "coach" in sys_prompt.lower()
    assert "API is how two programs talk" in sys_prompt
    assert "endpoint" in sys_prompt
    assert coach_realtime.END_SENTINEL in sys_prompt


def test_llm_mock_env_returns_canned_sequence(lesson, monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "1")
    sid, first = coach_realtime.start_session(lesson)
    assert "tools and APIs" in first
    seen = {first}
    for i in range(3):
        out = coach_realtime.handle_turn(sid, f"u{i}")
        seen.add(out["agent_utterance"])
    assert len(seen) == 4
