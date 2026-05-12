from unittest.mock import patch, MagicMock
import json
import io
from server.llm import ClaudeAssistant, GptAssistant, get_assistant, call_with_fallback


def _fake_resp(payload: dict):
    raw = json.dumps(payload).encode("utf-8")
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = raw
    cm.__exit__.return_value = False
    return cm


def test_claude_happy_path():
    payload = {"content": [{"type": "text", "text": "  hello  "}]}
    with patch("urllib.request.urlopen", return_value=_fake_resp(payload)):
        a = ClaudeAssistant()
        assert a._call("hi", system="sys") == "hello"


def test_claude_retries_three_times_then_returns_empty():
    with patch("urllib.request.urlopen", side_effect=Exception("boom")), \
         patch("time.sleep"):
        a = ClaudeAssistant()
        assert a._call("hi") == ""


def test_factory_returns_claude_by_default(monkeypatch):
    monkeypatch.setenv("AI_BACKEND", "claude")
    inst = get_assistant()
    assert isinstance(inst, ClaudeAssistant)


def test_factory_returns_gpt_when_requested(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    inst = get_assistant("gpt")
    assert isinstance(inst, GptAssistant)


def test_call_with_fallback_uses_gpt_when_claude_empty(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    with patch.object(ClaudeAssistant, "_call", return_value=""), \
         patch.object(GptAssistant, "_call", return_value="gpt-said-this"):
        out = call_with_fallback("prompt", system="sys")
    assert out == "gpt-said-this"


def test_call_with_fallback_returns_graceful_error_when_both_fail(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    with patch.object(ClaudeAssistant, "_call", return_value=""), \
         patch.object(GptAssistant, "_call", return_value=""):
        out = call_with_fallback("prompt")
    assert "trouble" in out.lower() or "error" in out.lower()
