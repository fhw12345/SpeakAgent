"""POST /api/lesson/start and /api/lesson/turn — realtime lesson REST API.

Scripted lessons (e.g. W1D1) continue to run via WebSocket /ws/session.
The REST endpoints here support the realtime mode added in Phase 2 and
also accept scripted lesson_ids (returning the first scripted agent turn
text from YAML, no LLM call) so the UI can use one entry point.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server import coach_realtime
from server.lesson_loader import LessonSpec, load as load_spec

router = APIRouter()


class _StartReq(BaseModel):
    lesson_id: str = Field(..., min_length=1, max_length=32)


class _TurnReq(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64)
    user_text: str = Field(..., max_length=4000)


@router.post("/api/lesson/start")
def lesson_start(req: _StartReq):
    try:
        spec: LessonSpec = load_spec(req.lesson_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"lesson not found: {req.lesson_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if spec.mode == "realtime":
        sid, first = coach_realtime.start_session(spec)
        return {"session_id": sid, "mode": "realtime", "first_agent_utterance": first}

    first = ""
    for t in spec.turns or []:
        if t.get("speaker") == "agent":
            first = t.get("say", "")
            break
    return {"session_id": "", "mode": "scripted", "first_agent_utterance": first}


@router.post("/api/lesson/turn")
def lesson_turn(req: _TurnReq):
    try:
        return coach_realtime.handle_turn(req.session_id, req.user_text)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"session not found: {req.session_id}")
