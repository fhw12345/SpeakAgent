import os
from server.config import load_config, voices_for_week

def test_default_port_is_8765(monkeypatch):
    monkeypatch.delenv("SPEAKAGENT_PORT", raising=False)
    cfg = load_config()
    assert cfg.port == 8765

def test_port_env_override(monkeypatch):
    monkeypatch.setenv("SPEAKAGENT_PORT", "9000")
    cfg = load_config()
    assert cfg.port == 9000

def test_seven_voices_total():
    cfg = load_config()
    assert len(cfg.voices) == 7
    assert "en-US-AriaNeural" in cfg.voices
    assert "zh-CN-XiaoxiaoNeural" in cfg.voices

def test_week1_us_only():
    weights = voices_for_week(1)
    assert all(v.startswith("en-US-") for v in weights)

def test_week3_us_uk_mix():
    weights = voices_for_week(3)
    families = {v.split("-")[1] for v in weights}
    assert families == {"US", "GB"}

def test_week5_four_families():
    weights = voices_for_week(5)
    families = {v.split("-")[1] for v in weights}
    assert families == {"US", "GB", "IN", "CN"}

def test_week7_all_voices_eligible():
    weights = voices_for_week(7)
    assert len(weights) >= 4
