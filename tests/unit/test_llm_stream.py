"""Unit tests for server.llm_stream.stream_claude — Anthropic SSE parsing."""
from __future__ import annotations

from typing import AsyncIterator
from unittest.mock import patch

import pytest

from server import llm_stream


class _FakeResponse:
    def __init__(self, lines: list[str]):
        self._lines = lines

    def raise_for_status(self) -> None:
        return

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self._lines:
            yield line


class _FakeStreamCM:
    def __init__(self, lines: list[str]):
        self._lines = lines

    async def __aenter__(self):
        return _FakeResponse(self._lines)

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeAsyncClient:
    def __init__(self, lines: list[str], **_kwargs):
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method: str, url: str, **_kwargs):
        return _FakeStreamCM(self._lines)


def _make_lines(deltas: list[str], end_with: str = "message_stop") -> list[str]:
    out: list[str] = ["event: message_start", 'data: {"type":"message_start"}', ""]
    for d in deltas:
        payload = (
            '{"type":"content_block_delta",'
            '"index":0,'
            '"delta":{"type":"text_delta","text":' + _json_str(d) + "}}"
        )
        out.append("event: content_block_delta")
        out.append("data: " + payload)
        out.append("")
    if end_with == "message_stop":
        out.append("event: message_stop")
        out.append('data: {"type":"message_stop"}')
    elif end_with == "DONE":
        out.append("data: [DONE]")
    return out


def _json_str(s: str) -> str:
    import json as _json
    return _json.dumps(s)


@pytest.mark.asyncio
async def test_stream_claude_yields_deltas_in_order():
    lines = _make_lines(["Hi ", "there", "."])
    with patch.object(llm_stream.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(lines, **kw)):
        out: list[str] = []
        async for chunk in llm_stream.stream_claude([{"role": "user", "content": "hi"}]):
            out.append(chunk)
    assert out == ["Hi ", "there", "."]


@pytest.mark.asyncio
async def test_stream_claude_handles_done_sentinel():
    lines = _make_lines(["A", "B"], end_with="DONE")
    with patch.object(llm_stream.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(lines, **kw)):
        out = [c async for c in llm_stream.stream_claude([{"role": "user", "content": "x"}])]
    assert out == ["A", "B"]


@pytest.mark.asyncio
async def test_stream_claude_skips_malformed_and_comments():
    lines = [
        ": keepalive",
        "",
        "data: not json at all",
        "event: content_block_delta",
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}',
        "data: [DONE]",
    ]
    with patch.object(llm_stream.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(lines, **kw)):
        out = [c async for c in llm_stream.stream_claude([{"role": "user", "content": "x"}])]
    assert out == ["ok"]


@pytest.mark.asyncio
async def test_stream_claude_ignores_non_text_delta_types():
    lines = [
        "event: content_block_start",
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
        "event: ping",
        'data: {"type":"ping"}',
        "event: content_block_delta",
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"hello"}}',
        "event: message_stop",
        'data: {"type":"message_stop"}',
    ]
    with patch.object(llm_stream.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(lines, **kw)):
        out = [c async for c in llm_stream.stream_claude([{"role": "user", "content": "x"}])]
    assert out == ["hello"]
