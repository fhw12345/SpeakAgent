import json

import httpx
import pytest

from server.llm_stream import stream_claude


def _sse(events: list[tuple[str, dict]]) -> bytes:
    """Build a fake SSE byte body from (event, data-dict) tuples."""
    out = []
    for ev, data in events:
        out.append(f"event: {ev}\ndata: {json.dumps(data)}\n\n")
    return "".join(out).encode("utf-8")


def _sse_raw(lines: list[str]) -> bytes:
    return ("\n".join(lines) + "\n\n").encode("utf-8")


@pytest.mark.asyncio
async def test_stream_yields_text_deltas_in_order():
    body = _sse([
        ("content_block_delta", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"}}),
        ("content_block_delta", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": " world"}}),
        ("content_block_delta", {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "."}}),
        ("message_stop", {"type": "message_stop"}),
    ])
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))

    # Patch the AsyncClient used inside stream_claude.
    import server.llm_stream as mod

    orig = mod.httpx.AsyncClient

    def _factory(*a, **kw):
        return orig(transport=transport, timeout=kw.get("timeout"))

    mod.httpx.AsyncClient = _factory  # type: ignore[assignment]
    try:
        out = []
        async for chunk in stream_claude([{"role": "user", "content": "hi"}], gateway_url="http://x/y"):
            out.append(chunk)
    finally:
        mod.httpx.AsyncClient = orig  # type: ignore[assignment]

    assert out == ["Hello", " world", "."]


@pytest.mark.asyncio
async def test_stream_handles_done_marker_and_malformed_lines():
    body = _sse_raw([
        ": ping comment line",
        "event: content_block_delta",
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"A"}}',
        "",
        "data: not-json",
        "",
        "event: content_block_delta",
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"B"}}',
        "",
        "data: [DONE]",
    ])
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))

    import server.llm_stream as mod

    orig = mod.httpx.AsyncClient

    def _factory(*a, **kw):
        return orig(transport=transport, timeout=kw.get("timeout"))

    mod.httpx.AsyncClient = _factory  # type: ignore[assignment]
    try:
        out = []
        async for chunk in stream_claude([{"role": "user", "content": "hi"}], gateway_url="http://x/y"):
            out.append(chunk)
    finally:
        mod.httpx.AsyncClient = orig  # type: ignore[assignment]

    assert out == ["A", "B"]


@pytest.mark.asyncio
async def test_stream_raises_on_http_error():
    transport = httpx.MockTransport(lambda req: httpx.Response(500, content=b"server err"))
    import server.llm_stream as mod

    orig = mod.httpx.AsyncClient

    def _factory(*a, **kw):
        return orig(transport=transport, timeout=kw.get("timeout"))

    mod.httpx.AsyncClient = _factory  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeError, match="claude_sse_http_500"):
            async for _ in stream_claude([{"role": "user", "content": "hi"}], gateway_url="http://x/y"):
                pass
    finally:
        mod.httpx.AsyncClient = orig  # type: ignore[assignment]
