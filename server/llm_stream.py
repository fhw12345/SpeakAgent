"""Claude SSE streaming client.

Connects to the local Claude gateway (Anthropic SSE protocol) and yields
text deltas as they arrive. Used by the streaming agent-turn path.

The gateway is the same `CLAUDE_API_ENDPOINT` used by `server/llm.py`.
We send `"stream": true` and parse `event: content_block_delta` frames.
"""
from __future__ import annotations

import json
import os
from typing import AsyncIterator, Iterable

import httpx

from server.logging_setup import get_logger

_log = get_logger("llm_stream")


def _default_endpoint() -> str:
    return os.environ.get(
        "CLAUDE_API_ENDPOINT",
        "http://localhost:23333/api/anthropic/v1/messages",
    )


def _default_model() -> str:
    return os.environ.get("CLAUDE_MODEL", "claude-opus-4.7-1m-internal")


def _iter_sse_events(lines: Iterable[str]) -> Iterable[tuple[str | None, str]]:
    """Group SSE text lines into (event, data) pairs.

    `data:` lines are concatenated until a blank line terminates the event.
    """
    event: str | None = None
    data_parts: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r")
        if line == "":
            if data_parts:
                yield event, "\n".join(data_parts)
            event = None
            data_parts = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_parts.append(line[5:].lstrip())
    if data_parts:
        yield event, "\n".join(data_parts)


def parse_delta(event: str | None, data: str) -> str | None:
    """Extract a text delta from an SSE event. Returns None if not a text delta."""
    if data == "[DONE]":
        return None
    try:
        obj = json.loads(data)
    except (ValueError, TypeError):
        return None
    if event and event != "content_block_delta":
        return None
    delta = obj.get("delta") or {}
    if delta.get("type") == "text_delta":
        return delta.get("text") or None
    if isinstance(obj.get("text"), str) and not event:
        return obj["text"] or None
    return None


async def stream_claude(
    messages: list[dict],
    model: str | None = None,
    gateway_url: str | None = None,
    system: str = "You are a helpful English speaking coach.",
    max_tokens: int = 1024,
    timeout: float = 60.0,
) -> AsyncIterator[str]:
    """Yield text deltas from a streaming Claude completion."""
    url = gateway_url or _default_endpoint()
    body = {
        "model": model or _default_model(),
        "max_tokens": max_tokens,
        "system": system,
        "stream": True,
        "messages": messages,
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "anthropic-version": "2023-06-01",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code != 200:
                preview = (await resp.aread())[:200]
                raise RuntimeError(f"claude_stream_http_{resp.status_code}: {preview!r}")
            line_buf: list[str] = []
            async for raw in resp.aiter_lines():
                line_buf.append(raw)
                if raw == "":
                    for event, data in _iter_sse_events(line_buf):
                        text = parse_delta(event, data)
                        if text:
                            yield text
                    line_buf = []
            if line_buf:
                for event, data in _iter_sse_events(line_buf + [""]):
                    text = parse_delta(event, data)
                    if text:
                        yield text
