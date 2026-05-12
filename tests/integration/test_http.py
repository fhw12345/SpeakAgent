from fastapi.testclient import TestClient
from server.main import app


def test_get_today_returns_lesson_id():
    with TestClient(app) as client:
        r = client.get("/api/today")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "w1d1"
    assert body["week"] == 1


def test_get_progress_empty_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEAKAGENT_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        r = client.get("/api/progress")
    assert r.status_code == 200
    assert "due_words" in r.json()
