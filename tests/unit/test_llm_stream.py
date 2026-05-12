"""Unit tests for stream_claude SSE parsing."""
import json
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, List

import pytest

from server import llm_stream


class _FakeResp:
    def __init__(self, lines: List[str], status_code: int = 200):
        self._lines = lines
        self.status_code = status_code

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return b"".join(line.encode() for line in self._lines)


class _FakeClient:
    def __init__(self, lines: List[str], status_code: int = 200):
        self._lines = lines
        self._status = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    @asynccontextmanager
    async def stream(self, method, url, headers=None, content=None):
        yield _FakeResp(self._lines, self._status)


def _make_delta_line(text: str) -> str:
    payload = {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": text},
    }
    return f"data: {json.dumps(payload)}"


@pytest.mark.asyncio
async def test_parses_text_deltas_in_order(monkeypatch):
    lines = [
        "event: message_start",
        'data: {"type":"message_start"}',
        "",
        "event: content_block_delta",
        _make_delta_line("Hello "),
        "",
        _make_delta_line("there. "),
        _make_delta_line("How are you?"),
        "data: [DONE]",
    ]
    monkeypatch.setattr(llm_stream.httpx, "AsyncClient", lambda **kw: _FakeClient(lines))
    monkeypatch.delenv("SPEAKAGENT_FAKE_LLM", raising=False)
    deltas = []
    async for d in llm_stream.stream_claude([{"role": "user", "content": "hi"}]):
        deltas.append(d)
    assert deltas == ["Hello ", "there. ", "How are you?"]


@pytest.mark.asyncio
async def test_ignores_malformed_lines(monkeypatch):
    lines = [
        "data: not-json{",
        _make_delta_line("ok"),
        "data: [DONE]",
    ]
    monkeypatch.setattr(llm_stream.httpx, "AsyncClient", lambda **kw: _FakeClient(lines))
    monkeypatch.delenv("SPEAKAGENT_FAKE_LLM", raising=False)
    deltas = [d async for d in llm_stream.stream_claude([{"role": "user", "content": "hi"}])]
    assert deltas == ["ok"]


@pytest.mark.asyncio
async def test_ignores_non_text_events(monkeypatch):
    lines = [
        'data: {"type":"ping"}',
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}',
        _make_delta_line("only this"),
        "data: [DONE]",
    ]
    monkeypatch.setattr(llm_stream.httpx, "AsyncClient", lambda **kw: _FakeClient(lines))
    monkeypatch.delenv("SPEAKAGENT_FAKE_LLM", raising=False)
    deltas = [d async for d in llm_stream.stream_claude([{"role": "user", "content": "hi"}])]
    assert deltas == ["only this"]


@pytest.mark.asyncio
async def test_http_error_raises(monkeypatch):
    monkeypatch.setattr(
        llm_stream.httpx, "AsyncClient", lambda **kw: _FakeClient(["nope"], status_code=500)
    )
    monkeypatch.delenv("SPEAKAGENT_FAKE_LLM", raising=False)
    with pytest.raises(RuntimeError, match="claude_stream_http_500"):
        async for _ in llm_stream.stream_claude([{"role": "user", "content": "hi"}]):
            pass


@pytest.mark.asyncio
async def test_fake_llm_env_uses_canned_text(monkeypatch):
    monkeypatch.setenv("SPEAKAGENT_FAKE_LLM", "1")
    monkeypatch.setenv("SPEAKAGENT_FAKE_LLM_TEXT", "One. Two. Three.")
    out = "".join([d async for d in llm_stream.stream_claude([{"role": "user", "content": "hi"}])])
    assert out == "One. Two. Three."
