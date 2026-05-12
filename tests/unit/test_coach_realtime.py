"""Unit tests for server.coach_realtime — LLM mocked."""
from unittest.mock import patch

import pytest

from server import coach_realtime
from server.lesson_loader import LessonSpec
from server import llm_client


def _spec() -> LessonSpec:
    return LessonSpec(
        mode="realtime",
        lesson_id="w1d2",
        title="rt",
        week=1,
        topic="tools and APIs",
        target_phrases=["An API is an interface."],
        vocabulary=["API", "endpoint"],
        coach_persona="a friendly coach",
    )


@pytest.fixture(autouse=True)
def _clear_sessions():
    coach_realtime._reset_for_tests()
    llm_client._reset_mock()
    yield
    coach_realtime._reset_for_tests()
    llm_client._reset_mock()


def test_start_session_calls_llm_and_returns_utterance():
    with patch("server.coach_realtime.generate", return_value="Hi! What is an API?") as gen:
        sid, first = coach_realtime.start_session(_spec())
    assert isinstance(sid, str) and len(sid) > 0
    assert first == "Hi! What is an API?"
    assert gen.call_count == 1
    msgs = gen.call_args[0][0]
    assert msgs[0]["role"] == "system"
    assert "tools and APIs" in msgs[0]["content"]


def test_handle_turn_appends_history():
    replies = iter(["Hello, what's an API?", "Good. Why use authentication?"])
    with patch("server.coach_realtime.generate", side_effect=lambda *a, **kw: next(replies)):
        sid, _ = coach_realtime.start_session(_spec())
        out = coach_realtime.handle_turn(sid, "An API is an interface.")
    assert out["agent_utterance"] == "Good. Why use authentication?"
    assert out["turn_index"] == 1
    assert out["done"] is False
    sess = coach_realtime._SESSIONS[sid]
    user_msgs = [m for m in sess.history if m["role"] == "user"]
    assert any(m["content"] == "An API is an interface." for m in user_msgs)


def test_done_after_max_user_turns():
    with patch("server.coach_realtime.generate", return_value="ok next?"):
        sid, _ = coach_realtime.start_session(_spec())
        result = None
        for i in range(coach_realtime.MAX_USER_TURNS):
            result = coach_realtime.handle_turn(sid, f"answer {i}")
    assert result is not None
    assert result["turn_index"] == coach_realtime.MAX_USER_TURNS
    assert result["done"] is True


def test_done_on_end_sentinel():
    replies = iter([
        "Hi! What is an API?",
        f"Great work. {coach_realtime.END_SENTINEL}",
    ])
    with patch("server.coach_realtime.generate", side_effect=lambda *a, **kw: next(replies)):
        sid, _ = coach_realtime.start_session(_spec())
        out = coach_realtime.handle_turn(sid, "An API is an interface.")
    assert out["done"] is True
    assert coach_realtime.END_SENTINEL not in out["agent_utterance"]
    assert "Great work" in out["agent_utterance"]


def test_unknown_session_raises_keyerror():
    with pytest.raises(KeyError):
        coach_realtime.handle_turn("nonexistent", "hi")


def test_start_session_rejects_scripted():
    bad = LessonSpec(mode="scripted", lesson_id="w1d1", turns=[])
    with pytest.raises(ValueError):
        coach_realtime.start_session(bad)


def test_kickoff_sentinel_does_not_end_session():
    """If the LLM emits the end sentinel on the very first utterance, the
    session must NOT be marked done — otherwise no learner turn could ever land."""
    replies = iter([
        f"Welcome! [[END_LESSON]]",
        "What is an API?",
    ])
    with patch("server.coach_realtime.generate", side_effect=lambda *a, **kw: next(replies)):
        sid, first = coach_realtime.start_session(_spec())
        assert "[[END_LESSON]]" not in first
        assert coach_realtime._SESSIONS[sid].done is False
        out = coach_realtime.handle_turn(sid, "hi")
    assert out["agent_utterance"] == "What is an API?"
    assert out["done"] is False


def test_system_prompt_contains_persona_and_phrases():
    spec = _spec()
    p = coach_realtime._build_system_prompt(spec)
    assert "friendly coach" in p
    assert "tools and APIs" in p
    assert "An API is an interface." in p
    assert "API" in p and "endpoint" in p
    assert coach_realtime.END_SENTINEL in p
