"""Unit tests for server.coach_realtime."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from server import coach_realtime
from server.lesson_loader import LessonSpec


def _spec() -> LessonSpec:
    return LessonSpec(
        mode="realtime",
        lesson_id="w1d2",
        title="t",
        week=1,
        topic="tools and APIs",
        target_phrases=["An agent calls a tool."],
        vocabulary=["tool", "API"],
        coach_persona="friendly coach",
    )


@pytest.fixture(autouse=True)
def _reset():
    coach_realtime.reset_sessions()
    yield
    coach_realtime.reset_sessions()


def test_start_session_calls_llm_and_returns_utterance():
    with patch("server.coach_realtime.generate", return_value="Hello! What's an API?") as g:
        sid, first = coach_realtime.start_session(_spec())
    assert sid and isinstance(sid, str)
    assert first == "Hello! What's an API?"
    g.assert_called_once()
    msgs = g.call_args[0][0]
    assert msgs[0]["role"] == "system"
    assert "tools and APIs" in msgs[0]["content"]


def test_handle_turn_appends_history():
    with patch("server.coach_realtime.generate", side_effect=["Hi.", "Cool, tell me more."]):
        sid, _ = coach_realtime.start_session(_spec())
        out = coach_realtime.handle_turn(sid, "An API is endpoints.")
    assert out["agent_utterance"] == "Cool, tell me more."
    assert out["turn_index"] == 1
    assert out["done"] is False
    sess = coach_realtime.get_session(sid)
    roles = [m["role"] for m in sess.history]
    assert roles == ["assistant", "user", "assistant"]


def test_done_after_max_user_turns():
    replies = ["start"] + [f"reply{i}" for i in range(coach_realtime.MAX_USER_TURNS)]
    with patch("server.coach_realtime.generate", side_effect=replies):
        sid, _ = coach_realtime.start_session(_spec())
        result = None
        for i in range(coach_realtime.MAX_USER_TURNS):
            result = coach_realtime.handle_turn(sid, f"user {i}")
    assert result["done"] is True
    assert result["turn_index"] == coach_realtime.MAX_USER_TURNS


def test_done_on_end_sentinel():
    with patch("server.coach_realtime.generate", side_effect=["start", f"Goodbye. {coach_realtime.END_SENTINEL}"]):
        sid, _ = coach_realtime.start_session(_spec())
        out = coach_realtime.handle_turn(sid, "anything")
    assert out["done"] is True
    assert coach_realtime.END_SENTINEL not in out["agent_utterance"]
    assert out["agent_utterance"] == "Goodbye."


def test_unknown_session_raises_keyerror():
    with pytest.raises(KeyError):
        coach_realtime.handle_turn("nope", "hi")


def test_start_rejects_scripted_lesson():
    scripted = LessonSpec(mode="scripted", lesson_id="w1d1", turns=[])
    with pytest.raises(ValueError):
        coach_realtime.start_session(scripted)


def test_system_prompt_includes_persona_and_phrases():
    spec = _spec()
    sys_text = coach_realtime._build_system(spec)
    assert "friendly coach" in sys_text
    assert "An agent calls a tool." in sys_text
    assert "tool" in sys_text and "API" in sys_text
    assert coach_realtime.END_SENTINEL in sys_text
