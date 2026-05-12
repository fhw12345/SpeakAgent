"""Claude SSE streaming client.

Talks to the local Anthropic-compatible gateway (default
http://localhost:23333/api/anthropic/v1/messages) with `stream: true`
and yields text deltas as they arrive.

Parses Anthropic streaming events (event: content_block_delta with
delta.type == 'text_delta'). Unknown / malformed lines are skipped.
"""
from __future__ import annotations

import json
import os
from typing import AsyncIterator

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


async def stream_claude(
    messages: list[dict],
    model: str | None = None,
    gateway_url: str | None = None,
    system: str = "You are a helpful English speaking coach.",
    max_tokens: int = 1024,
    timeout_s: float = 60.0,
) -> AsyncIterator[str]:
    """Stream text deltas from Claude SSE.

    Yields each delta string in order. Stops on `message_stop` or when the
    server closes the stream. Malformed/unknown SSE frames are ignored.
    """
    url = gateway_url or _default_endpoint()
    body = {
        "model": model or _default_model(),
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "stream": True,
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "anthropic-version": "2023-06-01",
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        async with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code != 200:
                detail = (await resp.aread())[:300]
                raise RuntimeError(f"claude_sse_http_{resp.status_code}: {detail!r}")
            event_name: str | None = None
            async for line in resp.aiter_lines():
                if not line:
                    event_name = None
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    _log.debug("llm_stream_bad_json", line=data[:80])
                    continue
                ev = event_name or payload.get("type")
                if ev == "content_block_delta":
                    delta = payload.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text:
                            yield text
                elif ev == "message_stop":
                    return
