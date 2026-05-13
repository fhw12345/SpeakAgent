"""Claude SSE streaming client. Talks to the local Anthropic-compatible gateway.

Uses httpx (already a dep) and parses Anthropic streaming events:
  event: content_block_delta
  data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"..."}}
  ...
  event: message_stop
  data: {"type":"message_stop"}

Yields text deltas in order. Tolerates `[DONE]` markers and malformed lines.
"""
import json
import os
from typing import AsyncIterator

import httpx

from server.logging_setup import get_logger

_log = get_logger("llm_stream")

_DEFAULT_GATEWAY = "http://localhost:23333/api/anthropic/v1/messages"
_DEFAULT_MODEL = "claude-opus-4.7-1m-internal"


async def stream_claude(
    messages: list[dict],
    model: str = _DEFAULT_MODEL,
    gateway_url: str | None = None,
    system: str = "You are a helpful English speaking coach.",
    max_tokens: int = 1024,
) -> AsyncIterator[str]:
    """Stream a Claude completion via SSE. Yields text deltas as they arrive."""
    url = gateway_url or os.environ.get("CLAUDE_API_ENDPOINT", _DEFAULT_GATEWAY)
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "stream": True,
    }
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        "Accept": "text/event-stream",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, json=body, headers=headers) as resp:
            if resp.status_code != 200:
                snippet = (await resp.aread())[:200]
                raise RuntimeError(f"claude_sse_http_{resp.status_code}: {snippet!r}")
            async for raw in resp.aiter_lines():
                if not raw or not raw.startswith("data:"):
                    continue
                payload = raw[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    evt = json.loads(payload)
                except json.JSONDecodeError:
                    _log.warning("sse_malformed_line", payload=payload[:120])
                    continue
                if evt.get("type") == "content_block_delta":
                    delta = evt.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        text = delta.get("text") or ""
                        if text:
                            yield text
                elif evt.get("type") == "message_stop":
                    return
