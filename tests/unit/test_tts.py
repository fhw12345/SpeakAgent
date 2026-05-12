import pytest
from unittest.mock import patch
from server.tts import pick_voice, synthesize_stream


def test_pick_voice_week1_us_only():
    v = pick_voice(week=1, turn_index=0)
    assert v.startswith("en-US-")


def test_pick_voice_week5_cycles_four_families():
    seen = set()
    for i in range(20):
        v = pick_voice(week=5, turn_index=i)
        seen.add(v.split("-")[1])
    assert {"US", "GB", "IN", "CN"}.issubset(seen)


@pytest.mark.asyncio
async def test_synthesize_stream_uses_azure_when_configured(monkeypatch):
    monkeypatch.setenv("AZURE_SPEECH_KEY", "k")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "eastasia")

    async def fake_azure(text, voice):
        yield b"\xAA\xBB"
        yield b"\xCC\xDD"

    with patch("server.tts._azure_stream", fake_azure):
        out = [c async for c in synthesize_stream("hi", voice="en-US-AriaNeural")]
    assert out == [b"\xAA\xBB", b"\xCC\xDD"]


@pytest.mark.asyncio
async def test_synthesize_stream_falls_back_to_edge_when_azure_fails(monkeypatch):
    monkeypatch.setenv("AZURE_SPEECH_KEY", "k")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "eastasia")

    async def broken_azure(text, voice):
        if False:
            yield b""
        raise RuntimeError("azure down")

    async def fake_edge(text, voice):
        yield b"\x01\x02"

    with patch("server.tts._azure_stream", broken_azure), \
         patch("server.tts._edge_stream", fake_edge):
        out = [c async for c in synthesize_stream("hi", voice="en-US-AriaNeural")]
    assert out == [b"\x01\x02"]


@pytest.mark.asyncio
async def test_synthesize_stream_edge_only_when_azure_not_configured(monkeypatch):
    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    monkeypatch.delenv("AZURE_SPEECH_REGION", raising=False)

    async def fake_edge(text, voice):
        yield b"\x99"

    with patch("server.tts._edge_stream", fake_edge):
        out = [c async for c in synthesize_stream("hi", voice="en-US-AriaNeural")]
    assert out == [b"\x99"]
