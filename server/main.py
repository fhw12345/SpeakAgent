"""FastAPI app: static frontend, /api/today, /api/progress, /ws/session."""
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
from server.routes.lesson_realtime import router as lesson_realtime_router
from server.routes.lessons import router as lessons_router
from server.session import new_session
from server.stt import SttEngine
from server.tts import pick_voice, synthesize_stream

configure_logging()
_log = get_logger("server")
_cfg = load_config()
_data_dir = os.environ.get("SPEAKAGENT_DATA_DIR", _cfg.data_dir)
_progress = ProgressStore(data_dir=_data_dir)

app = FastAPI(title="speakAgent")
app.include_router(lessons_router)
app.include_router(lesson_realtime_router)
_stt: SttEngine | None = None


def _get_stt() -> SttEngine:
    global _stt
    if _stt is None:
        _stt = SttEngine(model_name=_cfg.whisper_model)
    return _stt


@app.get("/api/today")
def api_today():
    plan = load_lesson(os.path.join(_cfg.curriculum_dir, "week1", "day1.yml"))
    return {"id": plan.id, "title": plan.title, "week": plan.week, "turn_count": len(plan.turns)}


@app.get("/api/progress")
def api_progress():
    return {"due_words": _progress.due_words()}


@app.websocket("/ws/session")
async def ws_session(ws: WebSocket):
    await ws.accept()
    plan = load_lesson(os.path.join(_cfg.curriculum_dir, "week1", "day1.yml"))
    sess = new_session(plan)
    await ws.send_json({"type": "session_start", "session_id": sess.id, "lesson": plan.title})

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
                async for chunk in synthesize_stream(turn["say"], voice=voice):
                    await ws.send_bytes(chunk)
                await ws.send_json({"type": "agent_done"})
                _progress.append_turn(sess.id, plan.id, {"role": "agent", "text": turn["say"]})
            else:
                await ws.send_json({
                    "type": "user_prompt",
                    "prompt": turn.get("prompt", "Your turn."),
                    "ideal": turn.get("ideal", ""),
                    "gloss": turn.get("gloss", []),
                    "translation": turn.get("translation", ""),
                })
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


_web_dir = os.path.join(os.path.dirname(__file__), "..", "web")
if os.path.isdir(_web_dir):
    app.mount("/static", StaticFiles(directory=_web_dir), name="static")

    @app.get("/")
    def root():
        return FileResponse(os.path.join(_web_dir, "index.html"))
