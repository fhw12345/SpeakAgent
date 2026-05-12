"""WebSocket session handler. Branches on cfg.vad between the legacy
push-to-talk loop and the realtime VAD-driven loop.

handle_legacy is a verbatim port of the pre-Phase-4 main.py body so the
existing PTT integration tests pass unchanged.

handle_vad runs two cooperating tasks per session:
  - _recv_loop: parses JSON `audio_frame` / `interrupt` messages, drives
    a per-session VadSegmenter, emits user_speech_start / user_speech_end,
    buffers PCM between start and end, and posts the transcribed segment
    onto a per-session queue.
  - _turn_loop: walks `coach.next_turn()`. For agent turns it streams TTS
    via agent_stream.run_to_ws under a fresh cancel_event; the recv loop
    sets that event on `interrupt` or VAD `start`. For user turns it
    awaits the next segment from the queue.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from typing import Optional

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from server import agent_stream
from server.config import load_config
from server.lesson import load_lesson
from server.logging_setup import get_logger
from server.session import new_session
from server.tts import pick_voice, synthesize_stream  # noqa: F401  (re-exported for legacy test patch parity)
from server.vad import VadSegmenter

_log = get_logger("ws_session")

_FRAME_BYTES = 1024  # 512 int16 samples @ 16 kHz
_MAX_SEGMENT_BYTES = 32000 * 2 * 30  # ~30 s of int16 mono @ 16 kHz


def _curriculum_path() -> str:
    cfg = load_config()
    return os.path.join(cfg.curriculum_dir, "week1", "day1.yml")


async def _receive_user_audio(ws: WebSocket, sess) -> np.ndarray:
    """Receive a user_audio_start ... user_audio_end window. Audio frames arrive as bytes."""
    sess.audio_buffer.clear()
    while True:
        msg = await ws.receive()
        if "bytes" in msg and msg["bytes"] is not None:
            sess.audio_buffer.extend(msg["bytes"])
        elif "text" in msg and msg["text"] is not None:
            data = json.loads(msg["text"])
            if data.get("type") == "user_audio_end":
                break
    pcm = np.frombuffer(bytes(sess.audio_buffer), dtype=np.int16).astype(np.float32) / 32768.0
    return pcm


async def handle_legacy(ws: WebSocket, sess, plan, get_stt, progress) -> None:
    while True:
        turn = sess.coach.next_turn()
        if turn is None:
            await ws.send_json({"type": "session_end", "scores": [s.to_dict() for s in sess.coach.scores]})
            break

        if turn["speaker"] == "agent":
            voice = pick_voice(week=plan.week, turn_index=sess.coach._idx)
            await ws.send_json({
                "type": "agent_caption",
                "text": turn["say"],
                "voice": voice,
                "gloss": turn.get("gloss", []),
                "translation": turn.get("translation", ""),
            })
            async for chunk in synthesize_stream(turn["say"], voice=voice):
                await ws.send_bytes(chunk)
            await ws.send_json({"type": "agent_done"})
            progress.append_turn(sess.id, plan.id, {"role": "agent", "text": turn["say"]})
        else:
            await ws.send_json({
                "type": "user_prompt",
                "prompt": turn.get("prompt", "Your turn."),
                "ideal": turn.get("ideal", ""),
                "gloss": turn.get("gloss", []),
                "translation": turn.get("translation", ""),
            })
            pcm = await _receive_user_audio(ws, sess)
            stt_res = get_stt().transcribe(pcm)
            await ws.send_json({"type": "user_transcript", "text": stt_res.text, "confidence": stt_res.confidence})
            score = sess.coach.submit_user_response(stt_res.text, stt_res.words, stt_res.confidence)
            await ws.send_json({"type": "score", "score": score.to_dict()})
            progress.append_turn(sess.id, plan.id, {
                "role": "user", "text": stt_res.text, "score": score.to_dict(),
            })


async def handle_vad(ws: WebSocket, sess, plan, get_stt, progress) -> None:
    vad = VadSegmenter()
    cancel_event_holder: dict = {"event": None}
    user_segment_queue: asyncio.Queue = asyncio.Queue()
    audio_segment = bytearray()
    recv_done = asyncio.Event()
    in_speech_flag = {"on": False}

    async def _recv_loop() -> None:
        nonlocal audio_segment
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    return
                text = msg.get("text")
                if text is None:
                    continue
                try:
                    data = json.loads(text)
                except (TypeError, ValueError):
                    continue
                mtype = data.get("type")
                if mtype == "interrupt":
                    ev = cancel_event_holder["event"]
                    if ev is not None:
                        ev.set()
                elif mtype == "audio_frame":
                    pcm_b64 = data.get("pcm_b64", "")
                    # Bound base64 decode size: a 1024-byte int16 frame
                    # encodes to ~1368 chars; cap at 4x to absorb padding.
                    if not isinstance(pcm_b64, str) or len(pcm_b64) > 4 * _FRAME_BYTES + 8:
                        continue
                    try:
                        pcm = base64.b64decode(pcm_b64)
                    except Exception:
                        continue
                    if not pcm:
                        continue
                    try:
                        events = vad.process_frame(pcm)
                    except ValueError:
                        continue
                    if in_speech_flag["on"]:
                        # Guard against unbounded growth if VAD never emits
                        # an "end" event (silero misclassification, stub
                        # tests). Cap segments at ~30 s.
                        if len(audio_segment) < _MAX_SEGMENT_BYTES:
                            audio_segment.extend(pcm)
                    for ev in events:
                        if ev == "start":
                            audio_segment = bytearray()
                            audio_segment.extend(pcm)
                            in_speech_flag["on"] = True
                            await ws.send_json({"type": "user_speech_start"})
                            cev = cancel_event_holder["event"]
                            if cev is not None:
                                cev.set()
                        elif ev == "end":
                            in_speech_flag["on"] = False
                            seg_id = uuid.uuid4().hex[:12]
                            await ws.send_json({
                                "type": "user_speech_end",
                                "segment_id": seg_id,
                            })
                            captured = bytes(audio_segment)
                            audio_segment = bytearray()
                            await user_segment_queue.put({
                                "segment_id": seg_id,
                                "pcm": captured,
                            })
        except (WebSocketDisconnect, RuntimeError):
            return
        finally:
            recv_done.set()

    async def _turn_loop() -> None:
        while True:
            turn = sess.coach.next_turn()
            if turn is None:
                await ws.send_json({
                    "type": "session_end",
                    "scores": [s.to_dict() for s in sess.coach.scores],
                })
                return

            if turn["speaker"] == "agent":
                voice = pick_voice(week=plan.week, turn_index=sess.coach._idx)
                await ws.send_json({
                    "type": "agent_caption",
                    "text": turn["say"],
                    "voice": voice,
                    "gloss": turn.get("gloss", []),
                    "translation": turn.get("translation", ""),
                })
                cancel_event = asyncio.Event()
                cancel_event_holder["event"] = cancel_event
                agent_task = asyncio.create_task(
                    agent_stream.run_to_ws(ws, turn["say"], voice, cancel_event)
                )
                done, _pending = await asyncio.wait(
                    {agent_task}, return_when=asyncio.FIRST_COMPLETED,
                )
                # If cancelled mid-stream and the task hasn't returned yet, give it
                # a brief grace window then hard-cancel.
                if not agent_task.done():
                    try:
                        await asyncio.wait_for(agent_task, timeout=0.5)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        agent_task.cancel()
                cancel_event_holder["event"] = None
                progress.append_turn(sess.id, plan.id, {"role": "agent", "text": turn["say"]})
            else:
                await ws.send_json({
                    "type": "user_prompt",
                    "prompt": turn.get("prompt", "Your turn."),
                    "ideal": turn.get("ideal", ""),
                    "gloss": turn.get("gloss", []),
                    "translation": turn.get("translation", ""),
                })
                seg = await user_segment_queue.get()
                pcm_arr = (
                    np.frombuffer(seg["pcm"], dtype=np.int16).astype(np.float32) / 32768.0
                )
                stt_res = get_stt().transcribe(pcm_arr)
                await ws.send_json({
                    "type": "user_transcript",
                    "text": stt_res.text,
                    "confidence": stt_res.confidence,
                })
                score = sess.coach.submit_user_response(
                    stt_res.text, stt_res.words, stt_res.confidence
                )
                await ws.send_json({"type": "score", "score": score.to_dict()})
                progress.append_turn(sess.id, plan.id, {
                    "role": "user", "text": stt_res.text, "score": score.to_dict(),
                })

    recv_task = asyncio.create_task(_recv_loop())
    turn_task = asyncio.create_task(_turn_loop())
    try:
        done, pending = await asyncio.wait(
            {recv_task, turn_task}, return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
    except (WebSocketDisconnect, RuntimeError):
        recv_task.cancel()
        turn_task.cancel()


async def handle(ws: WebSocket) -> None:
    # Lazy imports keep the legacy main.py exports untouched.
    from server.main import _get_stt, _progress

    cfg = load_config()
    plan = load_lesson(_curriculum_path())
    sess = new_session(plan)
    await ws.send_json({
        "type": "session_start",
        "session_id": sess.id,
        "lesson": plan.title,
    })

    try:
        if cfg.vad == "on":
            await handle_vad(ws, sess, plan, _get_stt, _progress)
        else:
            await handle_legacy(ws, sess, plan, _get_stt, _progress)
    except (WebSocketDisconnect, RuntimeError):
        _log.info("ws_disconnect", session_id=sess.id)
