"""Unit tests for stream_claude SSE parsing — pytest-asyncio + httpx mock."""
import json

import httpx
import pytest

from server import llm_stream


def _sse(events: list[tuple[str, dict]]) -> bytes:
    parts = []
    for evt_name, payload in events:
        parts.append(f"event: {evt_name}\n".encode())
        parts.append(f"data: {json.dumps(payload)}\n\n".encode())
    return b"".join(parts)


def _make_transport(body: bytes, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, headers={"content-type": "text/event-stream"})
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_yields_text_deltas_in_order(monkeypatch):
    body = _sse([
        ("content_block_delta", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello "}}),
        ("content_block_delta", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "world."}}),
        ("message_stop", {"type": "message_stop"}),
    ])
    transport = _make_transport(body)

    real_client = httpx.AsyncClient
    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)
    monkeypatch.setattr(llm_stream.httpx, "AsyncClient", patched)

    out = []
    async for delta in llm_stream.stream_claude([{"role": "user", "content": "hi"}]):
        out.append(delta)
    assert out == ["Hello ", "world."]


@pytest.mark.asyncio
async def test_handles_done_marker_and_malformed_lines(monkeypatch):
    body = (
        b"data: not-json\n\n"
        b"data: [DONE]\n\n"
        b'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"x"}}\n\n'
        b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
    )
    transport = _make_transport(body)
    real_client = httpx.AsyncClient
    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)
    monkeypatch.setattr(llm_stream.httpx, "AsyncClient", patched)

    out = [d async for d in llm_stream.stream_claude([{"role": "user", "content": "hi"}])]
    assert out == ["x"]


@pytest.mark.asyncio
async def test_http_error_raises(monkeypatch):
    transport = _make_transport(b"oops", status=500)
    real_client = httpx.AsyncClient
    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)
    monkeypatch.setattr(llm_stream.httpx, "AsyncClient", patched)

    with pytest.raises(RuntimeError, match="claude_sse_http_500"):
        async for _ in llm_stream.stream_claude([{"role": "user", "content": "hi"}]):
            pass
