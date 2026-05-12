"""Unit tests for stream_claude SSE parsing.

We monkeypatch urllib.request.urlopen to return a canned SSE byte stream and
verify deltas are yielded in order, [DONE] / message_stop terminate cleanly,
and malformed lines are skipped.
"""
from __future__ import annotations

import io
from typing import Iterable

import pytest

from server import llm_stream


class _FakeResponse:
    def __init__(self, lines: Iterable[bytes]):
        # Each "line" must end with \n so iteration matches what urllib gives us.
        self._buf = io.BytesIO(b"".join(l if l.endswith(b"\n") else l + b"\n" for l in lines))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._buf.readlines())

    def read(self):  # not used, but harmless
        return self._buf.read()


def _patch_urlopen(monkeypatch, lines):
    def fake_urlopen(req, timeout=60):
        return _FakeResponse(lines)
    monkeypatch.setattr(llm_stream.urllib.request, "urlopen", fake_urlopen)


@pytest.mark.asyncio
async def test_yields_deltas_in_order(monkeypatch):
    sse = [
        b"event: content_block_delta",
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi "}}',
        b"",
        b"event: content_block_delta",
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"there."}}',
        b"",
        b"event: message_stop",
        b"data: {}",
    ]
    _patch_urlopen(monkeypatch, sse)

    out: list[str] = []
    async for delta in llm_stream.stream_claude(messages=[{"role": "user", "content": "x"}]):
        out.append(delta)
    assert out == ["Hi ", "there."]


@pytest.mark.asyncio
async def test_handles_done_sentinel(monkeypatch):
    sse = [
        b"event: content_block_delta",
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"only."}}',
        b"",
        b"data: [DONE]",
    ]
    _patch_urlopen(monkeypatch, sse)
    out = [d async for d in llm_stream.stream_claude(messages=[{"role": "user", "content": "x"}])]
    assert out == ["only."]


@pytest.mark.asyncio
async def test_skips_malformed_lines(monkeypatch):
    sse = [
        b": comment",
        b"data: not-json-at-all",
        b"event: content_block_delta",
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}',
        b"",
        b"event: message_stop",
        b"data: {}",
    ]
    _patch_urlopen(monkeypatch, sse)
    out = [d async for d in llm_stream.stream_claude(messages=[{"role": "user", "content": "x"}])]
    assert out == ["ok"]
