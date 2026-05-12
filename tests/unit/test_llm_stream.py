"""Unit tests for server.llm_stream — SSE parsing + stream_claude (mocked)."""
import pytest

from server.llm_stream import _iter_sse_events, parse_delta, stream_claude


def test_iter_sse_events_groups_by_blank_line():
    lines = [
        "event: content_block_delta",
        'data: {"delta":{"type":"text_delta","text":"Hi"}}',
        "",
        "event: content_block_delta",
        'data: {"delta":{"type":"text_delta","text":" there"}}',
        "",
    ]
    events = list(_iter_sse_events(lines))
    assert len(events) == 2
    assert events[0][0] == "content_block_delta"
    assert "text_delta" in events[0][1]


def test_parse_delta_returns_text():
    text = parse_delta(
        "content_block_delta",
        '{"delta":{"type":"text_delta","text":"hello"}}',
    )
    assert text == "hello"


def test_parse_delta_ignores_done():
    assert parse_delta(None, "[DONE]") is None


def test_parse_delta_handles_malformed_json():
    assert parse_delta("content_block_delta", "not-json") is None


def test_parse_delta_ignores_non_text_events():
    assert parse_delta("message_start", '{"foo":1}') is None


class _FakeResponse:
    def __init__(self, lines: list[str], status: int = 200):
        self.status_code = status
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return b""


class _FakeClient:
    def __init__(self, lines: list[str], status: int = 200):
        self._lines = lines
        self._status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url, **kwargs):
        return _FakeResponse(self._lines, self._status)


@pytest.mark.asyncio
async def test_stream_claude_yields_deltas_in_order(monkeypatch):
    sse = [
        "event: content_block_delta",
        'data: {"delta":{"type":"text_delta","text":"Hi "}}',
        "",
        "event: content_block_delta",
        'data: {"delta":{"type":"text_delta","text":"there."}}',
        "",
        "event: message_stop",
        'data: {"type":"message_stop"}',
        "",
    ]
    monkeypatch.setattr(
        "server.llm_stream.httpx.AsyncClient",
        lambda **kw: _FakeClient(sse),
    )
    out = []
    async for delta in stream_claude([{"role": "user", "content": "hi"}]):
        out.append(delta)
    assert out == ["Hi ", "there."]


@pytest.mark.asyncio
async def test_stream_claude_handles_malformed_lines(monkeypatch):
    sse = [
        "event: content_block_delta",
        "data: not-json",
        "",
        "event: content_block_delta",
        'data: {"delta":{"type":"text_delta","text":"ok"}}',
        "",
    ]
    monkeypatch.setattr(
        "server.llm_stream.httpx.AsyncClient",
        lambda **kw: _FakeClient(sse),
    )
    out = [d async for d in stream_claude([{"role": "user", "content": "x"}])]
    assert out == ["ok"]


@pytest.mark.asyncio
async def test_stream_claude_raises_on_non_200(monkeypatch):
    monkeypatch.setattr(
        "server.llm_stream.httpx.AsyncClient",
        lambda **kw: _FakeClient([], status=500),
    )
    with pytest.raises(RuntimeError):
        async for _ in stream_claude([{"role": "user", "content": "x"}]):
            pass
