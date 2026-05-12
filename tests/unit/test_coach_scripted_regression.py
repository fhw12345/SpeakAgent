"""W1D1 scripted regression: ensure agent turn text is byte-identical to the YAML.

This pins the scripted-mode behavior so future edits to the loader / coach can't
silently change W1D1's content. Per PRD AC #2 + #7.
"""
from pathlib import Path

from server.lesson import load_lesson


REPO = Path(__file__).resolve().parents[2]
W1D1_PATH = REPO / "curriculum" / "week1" / "day1.yml"


EXPECTED_AGENT_OPENING = (
    "Welcome to your first day of speaking practice. Today we focus on "
    "listening and repeating short sentences about AI agents."
)

EXPECTED_FIRST_USER_PROMPT = "Repeat: An agent uses tools to get things done."
EXPECTED_FIRST_USER_IDEAL = "An agent uses tools to get things done."


def test_w1d1_loads_in_scripted_mode():
    lp = load_lesson(str(W1D1_PATH))
    assert lp.mode == "scripted"
    assert lp.id == "w1d1"
    assert lp.week == 1
    assert len(lp.turns) > 0


def test_w1d1_turn_sequence_unchanged():
    lp = load_lesson(str(W1D1_PATH))
    assert lp.turns[0]["speaker"] == "agent"
    assert lp.turns[0]["say"] == EXPECTED_AGENT_OPENING
    user_turns = [t for t in lp.turns if t["speaker"] == "user"]
    assert user_turns[0]["prompt"] == EXPECTED_FIRST_USER_PROMPT
    assert user_turns[0]["ideal"] == EXPECTED_FIRST_USER_IDEAL


def test_w1d1_realtime_fields_empty():
    lp = load_lesson(str(W1D1_PATH))
    assert lp.topic is None
    assert lp.coach_persona is None
    assert lp.target_phrases == []
    assert lp.vocabulary == []
