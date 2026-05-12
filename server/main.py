"""FastAPI app: static frontend, /api/today, /api/progress, /ws/session."""
import asyncio
import json
import os

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.config import load_config
from server.lesson import load_lesson
from server.logging_setup import configure_logging, get_logger
from server.progress import ProgressStore
from server.routes.lessons import router as lessons_router
from server.session import SpeechSession, new_session
from server.stt import SttEngine
from server.tts import pick_voice, synthesize_stream

configure_logging()
_log = get_logger("server")
_cfg = load_config()
_data_dir = os.environ.get("SPEAKAGENT_DATA_DIR", _cfg.data_dir)
_progress = ProgressStore(data_dir=_data_dir)

app = FastAPI(title="speakAgent")
app.include_router(lessons_router)
_stt: SttEngine | None = None


def _get_stt() -> SttEngine:
    global _stt
    if _stt is None:
        _stt = SttEngine(model_name=_cfg.whisper_model)
    return _stt


def _vad_enabled() -> bool:
    # Re-read each call so tests can monkey-patch the env between runs.
    return os.environ.get("SPEAKAGENT_VAD", _cfg.vad).lower() == "on"


@app.get("/api/today")
def api_today():
    plan = load_lesson(os.path.join(_cfg.curriculum_dir, "week1", "day1.yml"))
    return {"id": plan.id, "title": plan.title, "week": plan.week, "turn_count": len(plan.turns)}


@app.get("/api/progress")
def api_progress():
    return {"due_words": _progress.due_words()}


@app.get("/api/config")
def api_config():
    return {"vad": "on" if _vad_enabled() else "off"}


@app.websocket("/ws/session")
async def ws_session(ws: WebSocket):
    await ws.accept()
    plan = load_lesson(os.path.join(_cfg.curriculum_dir, "week1", "day1.yml"))
    sess = new_session(plan)
    await ws.send_json({"type": "session_start", "session_id": sess.id, "lesson": plan.title})

    vad_on = _vad_enabled()
    reader_task: asyncio.Task | None = None
    user_pcm_queue: asyncio.Queue[np.ndarray] = asyncio.Queue()

    if vad_on:
        reader_task = asyncio.create_task(_vad_reader(ws, sess, user_pcm_queue))

    try:
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
                sess.cancel_event.clear()
                sess.agent_streaming = True
                cancelled = False
                try:
                    async for chunk in synthesize_stream(turn["say"], voice=voice):
                        if sess.cancel_event.is_set():
                            cancelled = True
                            break
                        await ws.send_bytes(chunk)
                finally:
                    sess.agent_streaming = False
                await ws.send_json({"type": "agent_done", "cancelled": cancelled})
                _progress.append_turn(sess.id, plan.id, {"role": "agent", "text": turn["say"]})
            else:
                await ws.send_json({
                    "type": "user_prompt",
                    "prompt": turn.get("prompt", "Your turn."),
                    "ideal": turn.get("ideal", ""),
                    "gloss": turn.get("gloss", []),
                    "translation": turn.get("translation", ""),
                })
                sess.cancel_event.clear()
                if vad_on:
                    pcm = await user_pcm_queue.get()
                else:
                    pcm = await _receive_user_audio(ws, sess)
                stt_res = _get_stt().transcribe(pcm)
                await ws.send_json({"type": "user_transcript", "text": stt_res.text, "confidence": stt_res.confidence})
                score = sess.coach.submit_user_response(stt_res.text, stt_res.words, stt_res.confidence)
                await ws.send_json({"type": "score", "score": score.to_dict()})
                _progress.append_turn(sess.id, plan.id, {
                    "role": "user", "text": stt_res.text, "score": score.to_dict(),
                })
    except (WebSocketDisconnect, RuntimeError):
        _log.info("ws_disconnect", session_id=sess.id)
    finally:
        if reader_task is not None:
            reader_task.cancel()
            try:
                await reader_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                _log.warning("vad_reader_exit_error", session_id=sess.id, error=str(e)[:200])


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


# ~200 ms of pre-roll at 16 kHz int16 mono = 200 * 16 * 2 bytes = 6400.
# Captured continuously while idle so the first phoneme isn't truncated
# when VAD declares `start` after `min_speech_ms`.
_VAD_PREROLL_BYTES = 6400


async def _vad_reader(ws: WebSocket, sess: SpeechSession, out_queue: asyncio.Queue) -> None:
    """Continuously read WS messages while VAD mode is on.

    Routes binary frames through the VAD segmenter; emits
    user_speech_start / user_speech_end; on speech start while the agent
    is streaming, signals barge-in by setting sess.cancel_event; on
    speech end, hands the buffered PCM (with pre-roll) to the main loop
    via `out_queue`. Also handles explicit `interrupt` and
    `user_audio_end` messages idempotently."""
    from server.vad import VadSegmenter

    seg = VadSegmenter()
    seg_audio = bytearray()
    preroll = bytearray()
    seg_id = 0

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                return
            if msg.get("bytes") is not None:
                data = msg["bytes"]
                if sess.vad_segment_id is not None:
                    seg_audio.extend(data)
                else:
                    preroll.extend(data)
                    if len(preroll) > _VAD_PREROLL_BYTES:
                        del preroll[:len(preroll) - _VAD_PREROLL_BYTES]
                events = seg.process_frame(data)
                for ev in events:
                    if ev == "start":
                        seg_id += 1
                        sess.vad_segment_id = f"{sess.id}-{seg_id}"
                        # Prepend pre-roll so STT sees the leading phonemes
                        # silero-vad consumed before crossing min_speech_ms.
                        seg_audio = bytearray(preroll)
                        preroll.clear()
                        if sess.agent_streaming:
                            sess.cancel_event.set()
                        await ws.send_json({"type": "user_speech_start"})
                    elif ev == "end":
                        sid = sess.vad_segment_id or f"{sess.id}-{seg_id}"
                        sess.vad_segment_id = None
                        pcm = np.frombuffer(bytes(seg_audio), dtype=np.int16).astype(np.float32) / 32768.0
                        seg_audio.clear()
                        seg.reset()
                        await ws.send_json({"type": "user_speech_end", "segment_id": sid})
                        await out_queue.put(pcm)
            elif msg.get("text") is not None:
                try:
                    obj = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue
                mtype = obj.get("type")
                if mtype == "interrupt":
                    if sess.agent_streaming:
                        sess.cancel_event.set()
                elif mtype == "user_audio_end":
                    pcm = np.frombuffer(bytes(seg_audio), dtype=np.int16).astype(np.float32) / 32768.0
                    seg_audio.clear()
                    seg.reset()
                    sess.vad_segment_id = None
                    await out_queue.put(pcm)
    except WebSocketDisconnect:
        return


_web_dir = os.path.join(os.path.dirname(__file__), "..", "web")
if os.path.isdir(_web_dir):
    app.mount("/static", StaticFiles(directory=_web_dir), name="static")

    @app.get("/")
    def root():
        return FileResponse(os.path.join(_web_dir, "index.html"))
