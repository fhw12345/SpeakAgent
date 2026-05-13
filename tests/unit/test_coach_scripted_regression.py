"""Regression: W1D1 scripted lesson agent-turn text must remain byte-identical
to the snapshot below. If this test fails after intentionally rewording
W1D1, regenerate the snapshot manually after confirming the change is wanted.
"""
from server.lesson_loader import load


_W1D1_AGENT_TURNS = [
    "Welcome to your first day of speaking practice. Today we focus on listening and repeating short sentences about AI agents.",
    "I will say each sentence twice. Then you repeat it. Hold the spacebar to talk.",
    "Let's start with simple words. An agent is a program that makes decisions and takes actions.",
    "An agent uses tools to get things done.",
    "The model decides which tool to call.",
    "Each step, the agent reads the result and chooses the next action.",
    "We use a loop to let the agent keep working until the task is done.",
    "Memory lets the agent remember what happened earlier.",
    "A prompt is the instruction we give to the model.",
    "When the model is unsure, it should ask the user instead of guessing.",
    "A good agent stops cleanly when the goal is reached.",
    "Now let's practice answering. What does an agent use to get things done?",
    "Why does the agent need memory?",
    "What should the model do when it is unsure?",
    "Great work today. Tomorrow we will add more vocabulary about tools and APIs. See you then.",
]


def test_w1d1_loads_as_scripted_with_18_turns():
    spec = load("w1d1")
    assert spec.mode == "scripted"
    assert spec.turns is not None
    assert len(spec.turns) == 26


def test_w1d1_turn_sequence_unchanged():
    spec = load("w1d1")
    agent_says = [t["say"] for t in (spec.turns or []) if t.get("speaker") == "agent"]
    assert agent_says == _W1D1_AGENT_TURNS
