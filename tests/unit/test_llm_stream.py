"""Unit tests for stream_claude SSE parser."""
import pytest
import httpx

from server.llm_stream import stream_claude


def _sse_bytes(events: list[str]) -> bytes:
    # Each "event" is a full SSE line block already including newlines.
    return ("\n".join(events) + "\n").encode("utf-8")


def _make_handler(body: bytes, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, headers={"content-type": "text/event-stream"})
    return handler


@pytest.mark.asyncio
async def test_yields_text_deltas_in_order():
    body = _sse_bytes([
        'event: message_start',
        'data: {"type":"message_start"}',
        '',
        'event: content_block_delta',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello "}}',
        '',
        'event: content_block_delta',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"world."}}',
        '',
        'data: [DONE]',
    ])
    transport = httpx.MockTransport(_make_handler(body))
    async with httpx.AsyncClient(transport=transport) as client:
        out = []
        async for d in stream_claude([{"role": "user", "content": "hi"}], client=client, gateway_url="http://x/"):
            out.append(d)
    assert out == ["Hello ", "world."]


@pytest.mark.asyncio
async def test_skips_non_text_events_and_done():
    body = _sse_bytes([
        'data: {"type":"ping"}',
        '',
        'data: {"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{}"}}',
        '',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"only"}}',
        '',
        'data: [DONE]',
    ])
    transport = httpx.MockTransport(_make_handler(body))
    async with httpx.AsyncClient(transport=transport) as client:
        out = []
        async for d in stream_claude([{"role": "user", "content": "hi"}], client=client, gateway_url="http://x/"):
            out.append(d)
    assert out == ["only"]


@pytest.mark.asyncio
async def test_malformed_line_skipped():
    body = _sse_bytes([
        'data: not-json-here',
        '',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}',
        '',
    ])
    transport = httpx.MockTransport(_make_handler(body))
    async with httpx.AsyncClient(transport=transport) as client:
        out = []
        async for d in stream_claude([{"role": "user", "content": "hi"}], client=client, gateway_url="http://x/"):
            out.append(d)
    assert out == ["ok"]


@pytest.mark.asyncio
async def test_http_error_raises_runtimeerror():
    transport = httpx.MockTransport(_make_handler(b"server boom", status=500))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RuntimeError) as ei:
            async for _ in stream_claude([{"role": "user", "content": "hi"}], client=client, gateway_url="http://x/"):
                pass
        assert "llm_stream_failed" in str(ei.value)


@pytest.mark.asyncio
async def test_empty_text_delta_skipped():
    body = _sse_bytes([
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":""}}',
        '',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"x"}}',
        '',
    ])
    transport = httpx.MockTransport(_make_handler(body))
    async with httpx.AsyncClient(transport=transport) as client:
        out = [d async for d in stream_claude(
            [{"role": "user", "content": "hi"}], client=client, gateway_url="http://x/"
        )]
    assert out == ["x"]
