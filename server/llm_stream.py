"""Async SSE client for Claude messages via the local Agent Maestro gateway.

Yields text deltas one at a time. Implements the Anthropic streaming
protocol: lines of ``event: <name>`` followed by ``data: <json>``. We only
care about ``content_block_delta`` events whose ``delta.type`` is
``text_delta``. ``message_stop`` and the literal ``[DONE]`` sentinel both
end the stream cleanly. Malformed lines are skipped silently.
"""
from __future__ import annotations

import json
import os
from typing import AsyncIterator, Optional

import httpx

from server.logging_setup import get_logger

_log = get_logger("llm_stream")

_DEFAULT_GATEWAY = "http://localhost:23333/api/anthropic/v1/messages"
_DEFAULT_MODEL = "claude-opus-4.7-1m-internal"


async def stream_claude(
    messages: list[dict],
    model: str = _DEFAULT_MODEL,
    gateway_url: Optional[str] = None,
    system: str = "You are a helpful English speaking coach.",
    max_tokens: int = 1024,
    timeout: float = 60.0,
) -> AsyncIterator[str]:
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
        "Accept": "text/event-stream",
        "anthropic-version": "2023-06-01",
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=body, headers=headers) as resp:
            resp.raise_for_status()
            async for raw in resp.aiter_lines():
                line = raw.strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if not payload or payload == "[DONE]":
                    if payload == "[DONE]":
                        return
                    continue
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    _log.warning("sse_malformed_line", line=payload[:120])
                    continue
                kind = obj.get("type")
                if kind == "content_block_delta":
                    delta = obj.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        text = delta.get("text") or ""
                        if text:
                            yield text
                elif kind == "message_stop":
                    return
