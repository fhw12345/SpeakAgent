"""Streaming Claude client over Anthropic SSE via the local gateway.

Yields text deltas as they arrive. Designed for the same gateway as
server/llm.py (default http://localhost:23333/api/anthropic/v1/messages).

Test injection: if SPEAKAGENT_FAKE_LLM is set, yields chunks from
SPEAKAGENT_FAKE_LLM_TEXT (default: a short canned reply) instead of
calling the network. Used only by integration/e2e tests.
"""
import json
import os
from typing import AsyncIterator, List, Optional

import httpx

from server.logging_setup import get_logger

_log = get_logger("llm_stream")

DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4.7-1m-internal")
DEFAULT_GATEWAY = os.environ.get(
    "CLAUDE_API_ENDPOINT",
    "http://localhost:23333/api/anthropic/v1/messages",
)


async def _fake_stream() -> AsyncIterator[str]:
    text = os.environ.get(
        "SPEAKAGENT_FAKE_LLM_TEXT",
        "Hi there. How are you today? Tell me a little about yourself.",
    )
    # Emit in small chunks to exercise the splitter.
    chunk_size = 6
    for i in range(0, len(text), chunk_size):
        yield text[i : i + chunk_size]


async def stream_claude(
    messages: List[dict],
    model: Optional[str] = None,
    gateway_url: Optional[str] = None,
    system: str = "You are a friendly English-speaking coach. Keep replies under 3 short sentences.",
    max_tokens: int = 512,
) -> AsyncIterator[str]:
    """Yield text deltas from a Claude streaming completion."""
    if os.environ.get("SPEAKAGENT_FAKE_LLM"):
        async for c in _fake_stream():
            yield c
        return

    url = gateway_url or DEFAULT_GATEWAY
    body = {
        "model": model or DEFAULT_MODEL,
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
        async with client.stream("POST", url, headers=headers, content=json.dumps(body)) as resp:
            if resp.status_code != 200:
                detail = (await resp.aread())[:200]
                raise RuntimeError(f"claude_stream_http_{resp.status_code}: {detail!r}")
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    evt = json.loads(payload)
                except json.JSONDecodeError:
                    _log.warning("sse_bad_json", line=payload[:120])
                    continue
                if evt.get("type") == "content_block_delta":
                    delta = evt.get("delta") or {}
                    text = delta.get("text")
                    if text:
                        yield text
