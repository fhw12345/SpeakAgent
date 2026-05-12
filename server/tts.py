"""edge-tts streaming wrapper + per-week voice rotation."""
from typing import AsyncIterator
import edge_tts

from server.config import voices_for_week


def pick_voice(week: int, turn_index: int) -> str:
    pool = voices_for_week(week)
    return pool[turn_index % len(pool)]


async def synthesize_stream(text: str, voice: str) -> AsyncIterator[bytes]:
    """Yield raw MP3 chunks as they arrive from edge-tts."""
    comm = edge_tts.Communicate(text, voice)
    async for chunk in comm.stream():
        if chunk.get("type") == "audio":
            yield chunk["data"]
