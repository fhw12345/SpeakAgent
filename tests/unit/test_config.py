import os
from server.config import load_config, voices_for_week, _load_dotenv

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


def test_dotenv_loads_keys_when_unset(monkeypatch, tmp_path):
    """`.env` populates env when var is unset."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        'TESTONLY_KEY_FROM_DOTENV="from-dotenv"\n'
        '# this is a comment\n'
        '\n'
        "QUOTED='single-quoted'\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("TESTONLY_KEY_FROM_DOTENV", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)

    # Patch the module's __file__ so _load_dotenv looks at our tmp_path
    from server import config as cfgmod
    orig = cfgmod.__file__
    monkeypatch.setattr(cfgmod, "__file__",
                        str(tmp_path / "server" / "config.py"))
    try:
        _load_dotenv()
    finally:
        monkeypatch.setattr(cfgmod, "__file__", orig)
    assert os.environ.get("TESTONLY_KEY_FROM_DOTENV") == "from-dotenv"
    assert os.environ.get("QUOTED") == "single-quoted"


def test_dotenv_does_not_override_existing_env(monkeypatch, tmp_path):
    """Real env wins over .env so inline `KEY=v python ...` always works."""
    env_file = tmp_path / ".env"
    env_file.write_text("TESTONLY_PRIORITY=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("TESTONLY_PRIORITY", "from-real-env")

    from server import config as cfgmod
    orig = cfgmod.__file__
    monkeypatch.setattr(cfgmod, "__file__",
                        str(tmp_path / "server" / "config.py"))
    try:
        _load_dotenv()
    finally:
        monkeypatch.setattr(cfgmod, "__file__", orig)
    assert os.environ.get("TESTONLY_PRIORITY") == "from-real-env"


def test_dotenv_missing_file_is_silent(tmp_path, monkeypatch):
    from server import config as cfgmod
    orig = cfgmod.__file__
    monkeypatch.setattr(cfgmod, "__file__",
                        str(tmp_path / "nowhere" / "config.py"))
    try:
        _load_dotenv()  # should not raise
    finally:
        monkeypatch.setattr(cfgmod, "__file__", orig)


def test_vad_default_off(monkeypatch):
    monkeypatch.delenv("SPEAKAGENT_VAD", raising=False)
    cfg = load_config()
    assert cfg.vad == "off"


def test_vad_env_on(monkeypatch):
    for val in ("on", "true", "1", "yes", "ON", "True", "YES"):
        monkeypatch.setenv("SPEAKAGENT_VAD", val)
        assert load_config().vad == "on", f"expected 'on' for {val!r}"


def test_vad_env_other_values_off(monkeypatch):
    for val in ("anythingelse", "no", "0", "false", "off", ""):
        monkeypatch.setenv("SPEAKAGENT_VAD", val)
        assert load_config().vad == "off", f"expected 'off' for {val!r}"
