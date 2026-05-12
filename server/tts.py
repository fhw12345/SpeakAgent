"""TTS: Azure Speech (preferred) + edge-tts fallback + per-week voice rotation."""
import asyncio
import os
from typing import AsyncIterator
import httpx
import edge_tts

from server.config import voices_for_week
from server.logging_setup import get_logger

_log = get_logger("tts")


def pick_voice(week: int, turn_index: int) -> str:
    pool = voices_for_week(week)
    return pool[turn_index % len(pool)]


def _proxy() -> str | None:
    return (
        os.environ.get("SPEAKAGENT_TTS_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or None
    )


async def _azure_stream(text: str, voice: str) -> AsyncIterator[bytes]:
    key = os.environ.get("AZURE_SPEECH_KEY", "")
    region = os.environ.get("AZURE_SPEECH_REGION", "")
    if not key or not region:
        raise RuntimeError("azure_speech_not_configured")
    lang = "-".join(voice.split("-")[:2])
    ssml = (
        f"<speak version='1.0' xml:lang='{lang}'>"
        f"<voice name='{voice}'>{text}</voice></speak>"
    )
    url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
        "User-Agent": "speakAgent",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        async with client.stream("POST", url, headers=headers, content=ssml.encode("utf-8")) as resp:
            if resp.status_code != 200:
                body = (await resp.aread())[:200]
                raise RuntimeError(f"azure_tts_http_{resp.status_code}: {body!r}")
            async for chunk in resp.aiter_bytes(chunk_size=4096):
                if chunk:
                    yield chunk


async def _edge_stream(text: str, voice: str) -> AsyncIterator[bytes]:
    proxy = _proxy()
    comm = edge_tts.Communicate(text, voice, proxy=proxy) if proxy else edge_tts.Communicate(text, voice)
    async for chunk in comm.stream():
        if chunk.get("type") == "audio":
            yield chunk["data"]


async def synthesize_bytes(text: str, voice: str) -> bytes:
    """Accumulate the full TTS stream into a single MP3 byte blob.

    Used by the streaming coach path to send one `agent_audio` frame per
    sentence. Errors propagate from `synthesize_stream`.
    """
    out = bytearray()
    async for chunk in synthesize_stream(text, voice=voice):
        out.extend(chunk)
    return bytes(out)


async def synthesize_stream(text: str, voice: str) -> AsyncIterator[bytes]:
    """Yield raw MP3 chunks. Tries Azure Speech first, falls back to edge-tts."""
    try:
        first_chunk = None
        gen = _azure_stream(text, voice)
        async for chunk in gen:
            if first_chunk is None:
                first_chunk = chunk
                _log.info("tts_azure_ok", voice=voice, bytes=len(chunk))
            yield chunk
        return
    except Exception as e:
        _log.warning("tts_azure_failed", voice=voice, error=str(e)[:200])

    try:
        async for chunk in _edge_stream(text, voice):
            yield chunk
        _log.info("tts_edge_ok", voice=voice)
    except Exception as e:
        _log.error("tts_all_backends_failed", voice=voice, error=str(e)[:200])
        raise
