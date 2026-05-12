"""Tests for the /api/lessons endpoint and lesson_catalog module."""
from fastapi.testclient import TestClient

from server.lesson_catalog import build_catalog, load_lesson_title
from server.main import app


client = TestClient(app)


def test_get_lessons_returns_56():
    resp = client.get("/api/lessons")
    assert resp.status_code == 200
    body = resp.json()
    assert "lessons" in body
    assert len(body["lessons"]) == 56


def test_lesson_ids_format():
    resp = client.get("/api/lessons")
    lessons = resp.json()["lessons"]
    ids = {l["id"] for l in lessons}
    expected = {f"W{w}D{d}" for w in range(1, 9) for d in range(1, 8)}
    assert ids == expected
    assert len(ids) == 56


def test_only_w1d1_available():
    resp = client.get("/api/lessons")
    lessons = resp.json()["lessons"]
    available = [l for l in lessons if l["available"]]
    assert len(available) == 1
    assert available[0]["id"] == "W1D1"


def test_w1d1_title_from_yaml():
    catalog = build_catalog()
    w1d1 = next(l for l in catalog if l["id"] == "W1D1")
    expected_title = load_lesson_title("W1D1")
    assert expected_title is not None
    assert w1d1["title"] == expected_title


def test_unavailable_titles_are_coming_soon():
    resp = client.get("/api/lessons")
    lessons = resp.json()["lessons"]
    unavailable = [l for l in lessons if not l["available"]]
    assert len(unavailable) == 55
    for l in unavailable:
        assert l["title"] == "Coming soon"


def test_order_field_sequential():
    resp = client.get("/api/lessons")
    lessons = resp.json()["lessons"]
    for idx, l in enumerate(lessons, start=1):
        assert l["order"] == idx


def test_week_and_day_match_id():
    resp = client.get("/api/lessons")
    lessons = resp.json()["lessons"]
    for l in lessons:
        assert l["id"] == f"W{l['week']}D{l['day']}"
        assert 1 <= l["week"] <= 8
        assert 1 <= l["day"] <= 7
