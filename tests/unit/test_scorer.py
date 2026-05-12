from unittest.mock import patch
from server.scorer import score_turn, TurnScore, _wer, _fluency


def test_wer_identical_is_zero():
    assert _wer("hello world", "hello world") == 0.0


def test_wer_one_substitution():
    assert _wer("hello world", "hello there") == 0.5


def test_fluency_counts_fillers_and_wpm():
    words = [
        {"w": "um", "start": 0.0, "end": 0.2, "prob": 0.9},
        {"w": "i", "start": 0.3, "end": 0.4, "prob": 0.9},
        {"w": "think", "start": 0.4, "end": 0.7, "prob": 0.9},
        {"w": "uh", "start": 1.7, "end": 1.9, "prob": 0.9},
        {"w": "yes", "start": 1.9, "end": 2.1, "prob": 0.9},
    ]
    f = _fluency(words)
    assert f["fillers"] == 2
    assert f["pauses_over_800ms"] == 1
    assert f["wpm"] > 0


def test_score_turn_aggregates_three_dims():
    words = [{"w": "ok", "start": 0.0, "end": 0.3, "prob": 0.95}]
    with patch("server.scorer.call_with_fallback", return_value='{"content_score": 4, "rewrite": "Sure.", "issues": ["short"]}'):
        s = score_turn(
            user_text="ok",
            user_words=words,
            user_confidence=0.9,
            ideal_text="ok",
            llm_system="judge",
        )
    assert isinstance(s, TurnScore)
    assert 0.0 <= s.pronunciation <= 1.0
    assert s.content_score == 4
    assert s.rewrite == "Sure."


def test_score_turn_handles_invalid_llm_json():
    words = [{"w": "ok", "start": 0.0, "end": 0.3, "prob": 0.95}]
    with patch("server.scorer.call_with_fallback", return_value="not json"):
        s = score_turn(
            user_text="ok", user_words=words, user_confidence=0.9,
            ideal_text="ok", llm_system="judge",
        )
    assert s.content_score == 3
    assert "rewrite" in s.__dict__
