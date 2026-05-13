"""Unit tests for agent_stream.stream_turn cancellation semantics."""
import asyncio

import pytest

from server import agent_stream


def _make_fake_synth(chunks, sleep_per_chunk=0.0):
    async def fake(text, voice):
        for c in chunks:
            if sleep_per_chunk > 0:
                await asyncio.sleep(sleep_per_chunk)
            yield c
    return fake


@pytest.mark.asyncio
async def test_completes_when_not_cancelled(monkeypatch):
    monkeypatch.setattr(
        agent_stream, "synthesize_stream",
        _make_fake_synth([b"a", b"b", b"c"]),
    )
    cancel = asyncio.Event()
    msgs = []
    async for m in agent_stream.stream_turn("hi", "v", cancel):
        msgs.append(m)
    types = [m["type"] for m in msgs]
    assert types == ["tts_audio_chunk", "tts_audio_chunk", "tts_audio_chunk", "turn_end"]
    assert [m["data"] for m in msgs[:3]] == [b"a", b"b", b"c"]


@pytest.mark.asyncio
async def test_stops_within_one_chunk_after_cancel(monkeypatch):
    monkeypatch.setattr(
        agent_stream, "synthesize_stream",
        _make_fake_synth([b"a", b"b", b"c", b"d", b"e"], sleep_per_chunk=0.01),
    )
    cancel = asyncio.Event()
    received = []
    async for m in agent_stream.stream_turn("hi", "v", cancel):
        received.append(m)
        if len(received) == 1:
            cancel.set()
    types = [m["type"] for m in received]
    assert "turn_end" not in types
    # Allow at most one in-flight chunk after cancel.
    assert len(received) <= 2


@pytest.mark.asyncio
async def test_cancel_before_start(monkeypatch):
    monkeypatch.setattr(
        agent_stream, "synthesize_stream",
        _make_fake_synth([b"a", b"b", b"c"]),
    )
    cancel = asyncio.Event()
    cancel.set()
    msgs = [m async for m in agent_stream.stream_turn("hi", "v", cancel)]
    assert msgs == []
