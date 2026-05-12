import pytest
from unittest.mock import patch, AsyncMock
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
async def test_synthesize_stream_yields_audio_chunks():
    async def fake_stream(self):
        yield {"type": "audio", "data": b"\x01\x02"}
        yield {"type": "audio", "data": b"\x03\x04"}
        yield {"type": "WordBoundary"}

    with patch("edge_tts.Communicate.stream", new=fake_stream):
        chunks = []
        async for c in synthesize_stream("hi", voice="en-US-AriaNeural"):
            chunks.append(c)
    assert chunks == [b"\x01\x02", b"\x03\x04"]
