"""Tests for lesson loader: mode parsing + realtime field validation.

Existing test_lesson.py covers basic scripted YAML; this file covers the new
mode dispatch and realtime requirements introduced in Phase 2.
"""
import os
from pathlib import Path

import pytest

from server.lesson import load_lesson, LessonPlan


REPO = Path(__file__).resolve().parents[2]
W1D2_PATH = REPO / "curriculum" / "week1" / "day2.yml"


def _write(tmp_path, body: str) -> str:
    p = tmp_path / "lesson.yml"
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_default_mode_scripted(tmp_path):
    path = _write(tmp_path,
        "id: x\ntitle: t\nweek: 1\nturns:\n  - speaker: agent\n    say: Hi.\n",
    )
    lp = load_lesson(path)
    assert lp.mode == "scripted"
    assert lp.turns and lp.turns[0]["say"] == "Hi."


def test_invalid_mode_falls_back_with_warning(tmp_path, caplog):
    path = _write(tmp_path,
        "id: x\ntitle: t\nweek: 1\nmode: blorp\nturns:\n  - speaker: agent\n    say: Hi.\n",
    )
    lp = load_lesson(path)
    assert lp.mode == "scripted"


@pytest.mark.parametrize("missing_field", ["topic", "target_phrases", "vocabulary", "coach_persona"])
def test_realtime_requires_all_fields(tmp_path, missing_field):
    fields = {
        "topic": "tools",
        "target_phrases": ["A is B."],
        "vocabulary": ["tool"],
        "coach_persona": "warm coach",
    }
    fields.pop(missing_field)
    body_lines = ["id: x", "title: t", "week: 1", "mode: realtime"]
    for k, v in fields.items():
        if isinstance(v, list):
            body_lines.append(f"{k}:")
            for item in v:
                body_lines.append(f"  - {item}")
        else:
            body_lines.append(f"{k}: {v}")
    path = _write(tmp_path, "\n".join(body_lines) + "\n")
    with pytest.raises(ValueError, match=f"realtime lesson missing field: {missing_field}"):
        load_lesson(path)


def test_realtime_requires_topic_when_empty_string(tmp_path):
    path = _write(tmp_path,
        'id: x\ntitle: t\nweek: 1\nmode: realtime\n'
        'topic: ""\ncoach_persona: "c"\n'
        'target_phrases:\n  - "p"\nvocabulary:\n  - "v"\n',
    )
    with pytest.raises(ValueError, match="topic"):
        load_lesson(path)


def test_w1d2_loads():
    lp = load_lesson(str(W1D2_PATH))
    assert lp.id == "w1d2"
    assert lp.mode == "realtime"
    assert lp.topic == "tools and APIs"
    assert len(lp.target_phrases) >= 5
    assert len(lp.vocabulary) >= 8
    assert lp.coach_persona and lp.coach_persona.strip()
    assert lp.turns == []
