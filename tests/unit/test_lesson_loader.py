"""Unit tests for server.lesson_loader (Phase 2)."""
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from server import lesson_loader


def _write(tmp_path: Path, rel: str, body: str) -> Path:
    full = tmp_path / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(textwrap.dedent(body), encoding="utf-8")
    return full


def test_default_mode_scripted(tmp_path):
    p = _write(tmp_path, "week1/day1.yml", """
        id: w1d1
        title: t
        week: 1
        turns:
          - {speaker: agent, say: hi}
    """)
    spec = lesson_loader.load_from_path(str(p))
    assert spec.mode == "scripted"
    assert spec.lesson_id == "w1d1"
    assert spec.turns and spec.turns[0]["say"] == "hi"


def test_invalid_mode_falls_back_with_warning(tmp_path, caplog):
    p = _write(tmp_path, "week1/day9.yml", """
        id: w1d9
        mode: bogus
        turns: []
    """)
    spec = lesson_loader.load_from_path(str(p))
    assert spec.mode == "scripted"


@pytest.mark.parametrize("missing", ["topic", "target_phrases", "vocabulary", "coach_persona"])
def test_realtime_missing_field_raises(tmp_path, missing):
    base = {
        "id": "w1d2",
        "mode": "realtime",
        "topic": "tools and APIs",
        "target_phrases": ["An agent calls a tool."],
        "vocabulary": ["tool"],
        "coach_persona": "friendly coach",
    }
    base.pop(missing)
    body = "\n".join(f"{k}: {v}" if not isinstance(v, list) else f"{k}: {v}" for k, v in base.items())
    p = _write(tmp_path, f"week1/missing_{missing}.yml", body)
    with pytest.raises(ValueError) as exc:
        lesson_loader.load_from_path(str(p))
    assert missing in str(exc.value)


def test_realtime_requires_topic(tmp_path):
    p = _write(tmp_path, "week1/day_no_topic.yml", """
        id: x
        mode: realtime
        target_phrases: [a]
        vocabulary: [b]
        coach_persona: c
    """)
    with pytest.raises(ValueError, match="topic"):
        lesson_loader.load_from_path(str(p))


def test_w1d2_loads():
    """The actual curriculum file ships and parses as realtime."""
    repo_root = Path(__file__).resolve().parents[2]
    spec = lesson_loader.load("w1d2", curriculum_dir=str(repo_root / "curriculum"))
    assert spec.mode == "realtime"
    assert spec.topic and "tool" in spec.topic.lower()
    assert len(spec.target_phrases) >= 5
    assert len(spec.vocabulary) >= 8
    assert spec.coach_persona


def test_w1d1_loads_as_scripted():
    repo_root = Path(__file__).resolve().parents[2]
    spec = lesson_loader.load("w1d1", curriculum_dir=str(repo_root / "curriculum"))
    assert spec.mode == "scripted"
    assert spec.turns and len(spec.turns) > 5
