"""Async Claude SSE client over the local Agent Maestro gateway.

Yields incremental text deltas from `event: content_block_delta` SSE frames.
Uses stdlib only (urllib + threads) to avoid adding a dep; the network read
runs in a thread and feeds an asyncio queue.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import urllib.request
from typing import AsyncIterator

from server.logging_setup import get_logger

_log = get_logger("llm_stream")

DEFAULT_ENDPOINT = "http://localhost:23333/api/anthropic/v1/messages"
DEFAULT_MODEL = "claude-3-5-sonnet"


def _parse_sse_data(line: str) -> tuple[str | None, dict | None]:
    """Return (event_type, data_obj) for one decoded SSE line, or (None, None)."""
    if not line or line.startswith(":"):
        return (None, None)
    if line.startswith("event:"):
        return (line[6:].strip(), None)
    if line.startswith("data:"):
        payload = line[5:].strip()
        if payload == "[DONE]":
            return ("__done__", None)
        try:
            return (None, json.loads(payload))
        except Exception:
            return (None, None)
    return (None, None)


def _delta_text(obj: dict) -> str:
    """Extract text from a content_block_delta payload."""
    delta = obj.get("delta") or {}
    t = delta.get("type")
    if t == "text_delta":
        return delta.get("text", "") or ""
    if t == "input_json_delta":
        return ""
    # Some gateways nest under content
    return delta.get("text", "") or ""


async def stream_claude(
    messages: list[dict],
    model: str = DEFAULT_MODEL,
    gateway_url: str | None = None,
    system: str = "You are a helpful English speaking coach.",
    max_tokens: int = 512,
) -> AsyncIterator[str]:
    """Stream text deltas from Claude via the local SSE gateway.

    Yields plain string fragments. Closes cleanly on `[DONE]`, `message_stop`,
    or stream end. On HTTP / parse error, logs and yields nothing further.
    """
    endpoint = gateway_url or os.environ.get("CLAUDE_API_ENDPOINT", DEFAULT_ENDPOINT)
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "stream": True,
    }).encode("utf-8")

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _put(item):
        try:
            fut = asyncio.run_coroutine_threadsafe(queue.put(item), loop)
            fut.add_done_callback(lambda f: f.exception())  # surface, don't raise
        except RuntimeError:
            # Loop closed; nothing we can do.
            pass

    def _worker() -> None:
        req = urllib.request.Request(
            endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                pending_event: str | None = None
                for raw in resp:
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    evt, obj = _parse_sse_data(line)
                    if evt == "__done__":
                        break
                    if evt is not None:
                        pending_event = evt
                        if evt == "message_stop":
                            break
                        continue
                    if obj is None:
                        continue
                    if pending_event in (None, "content_block_delta", "message_delta"):
                        text = _delta_text(obj)
                        if text:
                            _put(text)
        except Exception as e:
            _log.warning("stream_claude_error", error=str(e)[:200])
        finally:
            _put(None)

    threading.Thread(target=_worker, daemon=True).start()

    while True:
        item = await queue.get()
        if item is None:
            return
        yield item
