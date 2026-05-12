"""Tests for the GET /config endpoint exposing the VAD feature flag."""
from fastapi.testclient import TestClient


def _get(path: str):
    from server.main import app
    with TestClient(app) as c:
        return c.get(path)


def test_config_returns_vad_off_by_default(monkeypatch):
    monkeypatch.delenv("SPEAKAGENT_VAD", raising=False)
    resp = _get("/config")
    assert resp.status_code == 200
    assert resp.json().get("vad") == "off"


def test_config_returns_vad_on_when_env_set(monkeypatch):
    monkeypatch.setenv("SPEAKAGENT_VAD", "on")
    resp = _get("/config")
    assert resp.status_code == 200
    assert resp.json().get("vad") == "on"
