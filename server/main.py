"""FastAPI app: static frontend, /api/today, /api/progress, /ws/session."""
import json
import os

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from server.config import load_config
from server.coach import stream_agent_turn, streaming_enabled
from server.lesson import load_lesson
from server.logging_setup import configure_logging, get_logger
from server.progress import ProgressStore
from server.routes.lessons import router as lessons_router
from server.routes.realtime import router as realtime_router
from server.routes_config import router as config_router
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
app.include_router(realtime_router)
app.include_router(config_router)
_stt: SttEngine | None = None


def _get_stt() -> SttEngine:
    global _stt
    if _stt is None:
        _stt = SttEngine(model_name=_cfg.whisper_model)
    return _stt


@app.on_event("startup")
async def _vad_warmup():
    cfg = load_config()
    if cfg.vad == "on":
        from server import vad
        try:
            vad.load_model_once()
        except Exception as e:  # pragma: no cover - logged for ops
            _log.warning("vad_warmup_failed", error=str(e)[:200])


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
    from server.ws_session import handle
    await handle(ws)


async def _receive_user_audio(ws: WebSocket, sess) -> np.ndarray:
    """Receive a user_audio_start ... user_audio_end window. Audio frames arrive as bytes.

    Retained for backward-compat with tests/utilities that import it.
    """
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
