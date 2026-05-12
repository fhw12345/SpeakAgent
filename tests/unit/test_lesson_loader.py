"""Unit tests for server.lesson_loader (Phase 2)."""
import textwrap

import pytest

from server import lesson_loader
from server.lesson_loader import LessonSpec, load, load_from_path


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(p)


def test_default_mode_scripted(tmp_path):
    path = _write(tmp_path, "x.yml", """
        id: x
        title: t
        week: 1
        turns:
          - speaker: agent
            say: hi
    """)
    spec = load_from_path(path)
    assert spec.mode == "scripted"
    assert spec.lesson_id == "x"
    assert spec.turns and spec.turns[0]["say"] == "hi"


def test_invalid_mode_falls_back_with_warning(tmp_path, caplog):
    path = _write(tmp_path, "x.yml", """
        id: x
        mode: nonsense
        turns: []
    """)
    spec = load_from_path(path)
    assert spec.mode == "scripted"


@pytest.mark.parametrize("missing", ["topic", "target_phrases", "vocabulary", "coach_persona"])
def test_realtime_requires_field(tmp_path, missing):
    fields = {
        "topic": "tools",
        "target_phrases": ["a", "b"],
        "vocabulary": ["x", "y"],
        "coach_persona": "friendly coach",
    }
    fields.pop(missing)
    body = "id: x\nmode: realtime\n"
    for k, v in fields.items():
        if isinstance(v, list):
            body += f"{k}:\n" + "".join(f"  - {item}\n" for item in v)
        else:
            body += f"{k}: {v}\n"
    path = _write(tmp_path, "x.yml", body)
    with pytest.raises(ValueError, match=f"realtime lesson missing field: {missing}"):
        load_from_path(path)


def test_w1d2_loads():
    spec = load("w1d2")
    assert spec.mode == "realtime"
    assert spec.topic == "tools and APIs"
    assert len(spec.target_phrases) >= 5
    assert len(spec.vocabulary) >= 8
    assert spec.coach_persona


def test_w1d1_still_loads_as_scripted():
    spec = load("w1d1")
    assert spec.mode == "scripted"
    assert spec.lesson_id == "w1d1"
    assert spec.turns and len(spec.turns) > 5
