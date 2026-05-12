"""Regression: Phase 2 must not change W1D1 scripted text or turn order."""
from __future__ import annotations

from pathlib import Path

from server.lesson import load_lesson
from server import lesson_loader


REPO = Path(__file__).resolve().parents[2]
W1D1 = REPO / "curriculum" / "week1" / "day1.yml"


def _agent_says(turns):
    return [t.get("say", "") for t in turns if t.get("speaker") == "agent"]


def _user_ideals(turns):
    return [t.get("ideal", "") for t in turns if t.get("speaker") == "user"]


def test_w1d1_loads_through_legacy_loader():
    plan = load_lesson(str(W1D1))
    assert plan.id == "w1d1"
    assert plan.week == 1
    assert len(plan.turns) > 10


def test_w1d1_loads_through_new_loader_with_identical_turns():
    legacy = load_lesson(str(W1D1))
    new = lesson_loader.load_from_path(str(W1D1))
    assert new.mode == "scripted"
    assert new.lesson_id == legacy.id
    assert new.turns == legacy.turns


def test_w1d1_turn_sequence_unchanged():
    """Snapshot of the agent and user-ideal lines for W1D1."""
    plan = load_lesson(str(W1D1))
    agent_lines = _agent_says(plan.turns)
    ideals = _user_ideals(plan.turns)

    expected_first_three_agent = [
        "Welcome to your first day of speaking practice. Today we focus on listening and repeating short sentences about AI agents.",
        "I will say each sentence twice. Then you repeat it. Hold the spacebar to talk.",
        "Let's start with simple words. An agent is a program that makes decisions and takes actions.",
    ]
    assert agent_lines[:3] == expected_first_three_agent

    expected_ideals_subset = [
        "An agent uses tools to get things done.",
        "The model decides which tool to call.",
        "Each step, the agent reads the result and chooses the next action.",
        "We use a loop to let the agent keep working until the task is done.",
        "Memory lets the agent remember what happened earlier.",
        "A prompt is the instruction we give to the model.",
        "When the model is unsure, it should ask the user instead of guessing.",
        "A good agent stops cleanly when the goal is reached.",
    ]
    for s in expected_ideals_subset:
        assert s in ideals, f"missing ideal: {s}"
