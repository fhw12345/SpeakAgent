"""B16: lesson catalog + ws_session lesson_id dispatch + load_lesson_mode."""
from unittest.mock import patch

import pytest

from server import lesson_catalog
from server.ws_session import _curriculum_path


def _stub_cfg(tmp_path):
    return type("C", (), {"curriculum_dir": str(tmp_path)})()


def test_load_lesson_mode_returns_scripted_when_field_missing(tmp_path):
    week_dir = tmp_path / "week1"
    week_dir.mkdir()
    (week_dir / "day1.yml").write_text("title: Hi\n", encoding="utf-8")
    with patch("server.lesson_catalog.load_config", return_value=_stub_cfg(tmp_path)):
        assert lesson_catalog.load_lesson_mode("W1D1") == "scripted"


def test_load_lesson_mode_reads_realtime(tmp_path):
    week_dir = tmp_path / "week1"
    week_dir.mkdir()
    (week_dir / "day2.yml").write_text("mode: realtime\ntitle: Hi\n", encoding="utf-8")
    with patch("server.lesson_catalog.load_config", return_value=_stub_cfg(tmp_path)):
        assert lesson_catalog.load_lesson_mode("W1D2") == "realtime"


def test_load_lesson_mode_invalid_falls_back_to_scripted(tmp_path):
    week_dir = tmp_path / "week1"
    week_dir.mkdir()
    (week_dir / "day3.yml").write_text("mode: chaos\n", encoding="utf-8")
    with patch("server.lesson_catalog.load_config", return_value=_stub_cfg(tmp_path)):
        assert lesson_catalog.load_lesson_mode("W1D3") == "scripted"


def test_load_lesson_mode_missing_yaml_returns_scripted(tmp_path):
    with patch("server.lesson_catalog.load_config", return_value=_stub_cfg(tmp_path)):
        assert lesson_catalog.load_lesson_mode("W9D9") == "scripted"


def test_build_catalog_includes_mode_field(tmp_path):
    week_dir = tmp_path / "week1"
    week_dir.mkdir()
    (week_dir / "day1.yml").write_text("title: D1\n", encoding="utf-8")
    (week_dir / "day2.yml").write_text("mode: realtime\ntitle: D2\n", encoding="utf-8")
    with patch("server.lesson_catalog.load_config", return_value=_stub_cfg(tmp_path)):
        catalog = lesson_catalog.build_catalog()
    by_id = {row["id"]: row for row in catalog}
    assert by_id["W1D1"]["mode"] == "scripted"
    assert by_id["W1D1"]["available"] is True
    assert by_id["W1D2"]["mode"] == "realtime"
    assert by_id["W1D2"]["available"] is True
    # Unavailable lessons default to scripted (no YAML to inspect)
    assert by_id["W8D7"]["mode"] == "scripted"
    assert by_id["W8D7"]["available"] is False


def test_curriculum_path_resolves_lesson_id(tmp_path):
    with patch("server.ws_session.load_config", return_value=_stub_cfg(tmp_path)):
        path = _curriculum_path("W2D5")
    assert path.endswith("week2/day5.yml") or path.endswith("week2\\day5.yml")


def test_curriculum_path_falls_back_on_invalid_id(tmp_path):
    with patch("server.ws_session.load_config", return_value=_stub_cfg(tmp_path)):
        path = _curriculum_path("garbage")
    # Falls back to W1D1 (week1/day1.yml) so legacy callers don't break
    assert path.endswith("week1/day1.yml") or path.endswith("week1\\day1.yml")


def test_curriculum_path_default_is_w1d1(tmp_path):
    with patch("server.ws_session.load_config", return_value=_stub_cfg(tmp_path)):
        path = _curriculum_path()
    assert path.endswith("week1/day1.yml") or path.endswith("week1\\day1.yml")
