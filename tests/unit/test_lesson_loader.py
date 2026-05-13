"""Phase 2 lesson loader: mode parsing, realtime validation, fallback."""
import pytest

from server.lesson_loader import LessonSpec, _build_spec, load


def test_default_mode_scripted():
    data = {"id": "x", "title": "X", "week": 1, "turns": [{"speaker": "agent", "say": "hi"}]}
    spec = _build_spec(data, fallback_id="x")
    assert spec.mode == "scripted"
    assert spec.lesson_id == "x"
    assert spec.turns and spec.turns[0]["say"] == "hi"


def test_invalid_mode_falls_back_with_warning(caplog):
    data = {"id": "x", "mode": "wibble", "turns": []}
    with caplog.at_level("WARNING"):
        spec = _build_spec(data, fallback_id="x")
    assert spec.mode == "scripted"


def _realtime_data(**overrides) -> dict:
    base = {
        "id": "w1d2",
        "title": "Realtime",
        "week": 1,
        "mode": "realtime",
        "topic": "tools and APIs",
        "target_phrases": ["An API is an interface."],
        "vocabulary": ["API", "endpoint"],
        "coach_persona": "a friendly coach",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize("missing", ["topic", "target_phrases", "vocabulary", "coach_persona"])
def test_realtime_requires_field(missing):
    data = _realtime_data()
    data.pop(missing)
    with pytest.raises(ValueError, match=f"realtime lesson missing field: {missing}"):
        _build_spec(data, fallback_id="w1d2")


def test_realtime_happy_path():
    spec = _build_spec(_realtime_data(), fallback_id="w1d2")
    assert spec.mode == "realtime"
    assert spec.topic == "tools and APIs"
    assert len(spec.target_phrases) == 1
    assert "API" in spec.vocabulary


def test_w1d2_loads():
    spec = load("w1d2")
    assert spec.mode == "realtime"
    assert spec.topic == "tools and APIs"
    assert len(spec.target_phrases) >= 5
    assert len(spec.vocabulary) >= 8
    assert spec.coach_persona and spec.coach_persona.strip()


def test_w1d1_loads_as_scripted():
    spec = load("w1d1")
    assert spec.mode == "scripted"
    assert spec.turns is not None
    assert len(spec.turns) > 0
