"""Cancellable agent turn streamer.

Wraps `tts.synthesize_stream` and emits structured stream messages so the
caller can forward to a WebSocket. A shared `asyncio.Event` lets the
caller signal cancellation; the stream stops yielding within one chunk.

This shape leaves room to add `agent_token` events (Claude streaming) in
a future phase without breaking callers.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from fastapi import WebSocket

from server.tts import synthesize_stream


async def stream_turn(
    text: str,
    voice: str,
    cancel_event: asyncio.Event,
) -> AsyncIterator[dict]:
    if cancel_event.is_set():
        return
    async for chunk in synthesize_stream(text, voice):
        if cancel_event.is_set():
            return
        yield {"type": "tts_audio_chunk", "data": chunk}
        await asyncio.sleep(0)
        if cancel_event.is_set():
            return
    yield {"type": "turn_end"}


async def run_to_ws(
    ws: WebSocket,
    text: str,
    voice: str,
    cancel_event: asyncio.Event,
) -> None:
    async for msg in stream_turn(text, voice, cancel_event):
        if msg["type"] == "tts_audio_chunk":
            await ws.send_bytes(msg["data"])
        elif msg["type"] == "turn_end":
            await ws.send_json({"type": "turn_end"})
