"""Regression: W1D1 scripted turn sequence is byte-identical to the YAML."""
import yaml
from pathlib import Path

from server.lesson_loader import load


def test_w1d1_turn_sequence_unchanged():
    spec = load("w1d1")
    raw_path = Path(__file__).resolve().parents[2] / "curriculum" / "week1" / "day1.yml"
    raw = yaml.safe_load(raw_path.read_text(encoding="utf-8"))
    raw_turns = raw["turns"]

    assert spec.mode == "scripted"
    assert spec.turns is not None
    assert len(spec.turns) == len(raw_turns)
    for loaded, original in zip(spec.turns, raw_turns):
        assert loaded == original


def test_w1d1_agent_says_unchanged():
    """Snapshot: the ordered list of agent 'say' strings is fixed."""
    spec = load("w1d1")
    says = [t["say"] for t in spec.turns if t["speaker"] == "agent"]
    assert says[0].startswith("Welcome to your first day")
    assert says[-1].startswith("Great work today")
    assert "An agent uses tools to get things done." in says
    assert "Memory lets the agent remember what happened earlier." in says
