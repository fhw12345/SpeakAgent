"""Claude SSE streaming via local Agent Maestro gateway (httpx-based)."""
import json
import os
from typing import AsyncIterator, Optional

import httpx

from server.logging_setup import get_logger

_log = get_logger("llm_stream")

_DEFAULT_ENDPOINT = "http://localhost:23333/api/anthropic/v1/messages"
_DEFAULT_MODEL = "claude-opus-4.7-1m-internal"


async def stream_claude(
    messages: list[dict],
    model: Optional[str] = None,
    system: str = "You are a helpful English speaking coach.",
    gateway_url: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
    max_tokens: int = 1024,
) -> AsyncIterator[str]:
    """Yield text deltas from Claude's SSE messages stream.

    Parses `event: content_block_delta` frames and yields `delta.text`.
    Skips malformed individual `data:` lines. Raises RuntimeError on HTTP/transport
    failure so the caller can emit `agent_error` and continue gracefully.
    """
    url = gateway_url or os.environ.get("CLAUDE_API_ENDPOINT", _DEFAULT_ENDPOINT)
    model_name = model or os.environ.get("CLAUDE_MODEL", _DEFAULT_MODEL)
    payload = {
        "model": model_name,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "stream": True,
    }
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        "accept": "text/event-stream",
    }

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=60.0)
    try:
        try:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread())[:200]
                    raise RuntimeError(
                        f"llm_stream_failed:http_{resp.status_code}:{body!r}"
                    )
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        _log.warning("sse_malformed_line", line=raw[:120])
                        continue
                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta") or {}
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                yield text
        except httpx.HTTPError as e:
            raise RuntimeError(f"llm_stream_failed:transport:{e}") from e
    finally:
        if owns_client:
            await client.aclose()
