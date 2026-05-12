"""Integration tests for the streaming agent WS path.

Asserts:
- With SPEAKAGENT_STREAMING=on and stream_claude mocked, the WS receives
  multiple agent_partial_text frames before agent_done, with audio bytes
  interleaved per sentence.
- With SPEAKAGENT_STREAMING=off, no agent_partial_text frames are emitted.
- A TTS error on one sentence yields agent_error and the turn still
  completes with agent_done.
"""
import json
import os
from typing import AsyncIterator
from unittest.mock import patch

from fastapi.testclient import TestClient

from server.main import app
from server.stt import TranscriptionResult


async def _empty_tts(text, voice):
    if False:
        yield b""


async def _three_chunk_tts(text, voice):
    yield b"\xff\xfb"
    yield b"\x00\x00"
    yield b"AUDIO"


async def _fake_stream(messages, **kw) -> AsyncIterator[str]:
    for piece in ["Hi there", ". ", "How ", "are ", "you", "? ", "Tell me more."]:
        yield piece


def _fake_transcribe(self, pcm):
    return TranscriptionResult(
        text="ok", confidence=0.9,
        words=[{"w": "ok", "start": 0, "end": 0.2, "prob": 0.9}],
        language="en",
    )


def _drive_one_agent_turn(client, env_overrides):
    """Connect, advance through the first agent turn, return the frames seen."""
    saved_env = {k: os.environ.get(k) for k in env_overrides}
    os.environ.update(env_overrides)
    try:
        with client.websocket_connect("/ws/session") as ws:
            frames = []
            for _ in range(200):
                msg = ws.receive()
                if "text" in msg and msg["text"]:
                    data = json.loads(msg["text"])
                    frames.append(("text", data))
                    if data.get("type") == "agent_done":
                        return frames
                    if data.get("type") == "user_prompt":
                        # If we somehow advance to user turn without seeing
                        # agent_done, we want the test to fail loudly.
                        return frames
                elif "bytes" in msg and msg["bytes"] is not None:
                    frames.append(("bytes", msg["bytes"]))
            return frames
    finally:
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_streaming_on_emits_partial_text_then_audio_then_done():
    with patch("server.main.synthesize_stream", _three_chunk_tts), \
         patch("server.main.stream_claude", _fake_stream), \
         patch("server.stt.SttEngine.transcribe", _fake_transcribe), \
         TestClient(app) as client:
        frames = _drive_one_agent_turn(client, {"SPEAKAGENT_STREAMING": "on"})

    text_frames = [f for kind, f in frames if kind == "text"]
    types = [f["type"] for f in text_frames]
    partials = [f for f in text_frames if f["type"] == "agent_partial_text"]
    assert types[-1] == "agent_done", f"expected agent_done last, got {types}"
    assert len(partials) >= 2, f"expected >=2 agent_partial_text, got {types}"

    # Indices are 0,1,2,... in order
    assert [p["index"] for p in partials] == list(range(len(partials)))

    # Audio bytes appear interleaved with sentences (at least one bytes frame
    # follows each partial_text before the final agent_done).
    seen_partial_indices_with_audio = set()
    last_partial_idx = None
    for kind, f in frames:
        if kind == "text" and f.get("type") == "agent_partial_text":
            last_partial_idx = f["index"]
        elif kind == "bytes" and last_partial_idx is not None:
            seen_partial_indices_with_audio.add(last_partial_idx)
    assert len(seen_partial_indices_with_audio) >= 2, \
        f"expected audio after >=2 partials, saw {seen_partial_indices_with_audio}"

    # Exactly one agent_done with full_text containing concatenated sentences.
    done = [f for f in text_frames if f["type"] == "agent_done"]
    assert len(done) == 1
    assert "Hi there" in done[0].get("full_text", "")


def test_streaming_off_emits_no_partial_text():
    with patch("server.main.synthesize_stream", _empty_tts), \
         patch("server.main.stream_claude", _fake_stream), \
         patch("server.stt.SttEngine.transcribe", _fake_transcribe), \
         TestClient(app) as client:
        frames = _drive_one_agent_turn(client, {"SPEAKAGENT_STREAMING": "off"})

    text_frames = [f for kind, f in frames if kind == "text"]
    types = [f["type"] for f in text_frames]
    assert "agent_partial_text" not in types, f"unexpected partial in {types}"
    assert "agent_caption" in types
    assert types[-1] == "agent_done"


def test_streaming_tts_error_emits_agent_error_and_continues():
    call_count = {"n": 0}

    async def _tts_fail_on_second(text, voice):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated tts failure")
        yield b"AUDIO"

    with patch("server.main.synthesize_stream", _tts_fail_on_second), \
         patch("server.main.stream_claude", _fake_stream), \
         patch("server.stt.SttEngine.transcribe", _fake_transcribe), \
         TestClient(app) as client:
        frames = _drive_one_agent_turn(client, {"SPEAKAGENT_STREAMING": "on"})

    text_frames = [f for kind, f in frames if kind == "text"]
    types = [f["type"] for f in text_frames]
    errors = [f for f in text_frames if f["type"] == "agent_error"]
    assert errors, f"expected agent_error in {types}"
    assert types[-1] == "agent_done"
