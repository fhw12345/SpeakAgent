"""Integration: GET /config returns vad feature flag."""
from fastapi.testclient import TestClient

from server.main import app


def test_config_route_returns_vad_field_default_off(monkeypatch):
    monkeypatch.delenv("SPEAKAGENT_VAD", raising=False)
    with TestClient(app) as client:
        r = client.get("/config")
        assert r.status_code == 200
        body = r.json()
        assert body == {"vad": "off"}


def test_config_route_reflects_env_on(monkeypatch):
    monkeypatch.setenv("SPEAKAGENT_VAD", "on")
    with TestClient(app) as client:
        r = client.get("/config")
        assert r.status_code == 200
        assert r.json() == {"vad": "on"}
