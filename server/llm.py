"""LLM access — copied from NBAVedio (urllib + factory + 3-retry).

Default backend: Claude via local Agent Maestro gateway.
Fallback chain (call_with_fallback): Claude -> GPT -> graceful spoken error.
"""
import json
import os
import time
import urllib.request
from typing import Optional

from server.logging_setup import get_logger

_log = get_logger("llm")


class ClaudeAssistant:
    """Claude backend via local Agent Maestro endpoint."""

    DEFAULT_MODEL = "claude-opus-4.7-1m-internal"

    def __init__(self):
        self._endpoint = os.environ.get(
            "CLAUDE_API_ENDPOINT",
            "http://localhost:23333/api/anthropic/v1/messages",
        )
        self._model = os.environ.get("CLAUDE_MODEL", self.DEFAULT_MODEL)

    def _call(self, prompt: str, system: str = "You are a helpful English speaking coach.") -> str:
        body = json.dumps({
            "model": self._model,
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")

        for attempt in range(3):
            req = urllib.request.Request(
                self._endpoint,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "anthropic-version": "2023-06-01",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        return block["text"].strip()
                return ""
            except Exception as e:
                wait = (attempt + 1) * 10
                _log.warning("claude_retry", attempt=attempt + 1, error=str(e), wait_s=wait)
                if attempt < 2:
                    time.sleep(wait)
        _log.error("claude_failed_all_retries")
        return ""


class GptAssistant:
    """Azure OpenAI GPT backend (fallback)."""

    def __init__(self):
        self.endpoint = os.environ.get(
            "AZURE_OPENAI_ENDPOINT",
            "https://ravensai.openai.azure.com/openai/responses",
        )
        self.api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")
        self.api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
        self.model = os.environ.get("AZURE_OPENAI_MODEL", "gpt-5.4-mini")
        if not self.api_key:
            raise RuntimeError(
                "AZURE_OPENAI_API_KEY not set; cannot use GPT backend."
            )

    def _call(self, prompt: str, system: str = "You are a helpful English speaking coach.") -> str:
        url = f"{self.endpoint}?api-version={self.api_version}"
        body = json.dumps({
            "model": self.model,
            "input": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "api-key": self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            _log.error("gpt_failed", error=str(e))
            return ""

        for item in data.get("output", []):
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") == "output_text":
                        return c["text"]
        return ""


_DEFAULT_BACKEND = os.environ.get("AI_BACKEND", "claude").lower()


def get_assistant(backend: Optional[str] = None):
    choice = (backend or os.environ.get("AI_BACKEND", "claude")).lower()
    if choice == "gpt":
        return GptAssistant()
    return ClaudeAssistant()


GRACEFUL_ERROR = (
    "I'm having trouble reaching my brain right now. "
    "Let's pause this turn and try again in a moment."
)


def call_with_fallback(prompt: str, system: str = "You are a helpful English speaking coach.") -> str:
    """Claude -> GPT -> graceful spoken error. Always returns a non-empty string."""
    try:
        out = ClaudeAssistant()._call(prompt, system=system)
        if out:
            return out
    except Exception as e:
        _log.error("claude_unexpected", error=str(e))
    try:
        out = GptAssistant()._call(prompt, system=system)
        if out:
            return out
    except Exception as e:
        _log.error("gpt_unexpected", error=str(e))
    _log.error("llm_all_backends_failed")
    return GRACEFUL_ERROR
