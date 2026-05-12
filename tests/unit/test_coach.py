from unittest.mock import patch
from server.coach import Coach, CoachState
from server.lesson import LessonPlan


def _plan():
    return LessonPlan(
        id="w1d1", title="t", week=1,
        turns=[
            {"speaker": "agent", "say": "Hello and welcome."},
            {"speaker": "user", "prompt": "Repeat.", "ideal": "Hello and welcome."},
        ],
    )


def test_coach_starts_idle():
    c = Coach(_plan())
    assert c.state == CoachState.IDLE


def test_advance_from_idle_to_speak_prompt():
    c = Coach(_plan())
    turn = c.next_turn()
    assert c.state == CoachState.SPEAK_PROMPT
    assert turn["speaker"] == "agent"
    assert turn["say"] == "Hello and welcome."


def test_user_turn_transitions_to_listen_then_score():
    c = Coach(_plan())
    c.next_turn()  # agent
    user_turn = c.next_turn()
    assert c.state == CoachState.LISTEN_USER
    assert user_turn["speaker"] == "user"


def test_submit_user_response_returns_score_and_advances():
    c = Coach(_plan())
    c.next_turn()  # agent
    c.next_turn()  # user prompt
    fake = {"pronunciation": 0.9, "fluency": {}, "content_score": 4, "issues": [], "rewrite": ""}
    with patch("server.coach.score_turn") as mock_score:
        from server.scorer import TurnScore
        mock_score.return_value = TurnScore(
            pronunciation=0.9, fluency={}, content_score=4, issues=[], rewrite=""
        )
        score = c.submit_user_response(text="Hello and welcome.", words=[], confidence=0.9)
    assert score.content_score == 4
    assert c.state == CoachState.SESSION_END
