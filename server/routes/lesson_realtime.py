"""REST endpoints for the realtime lesson flow.

POST /api/lesson/start  body {lesson_id} -> {session_id, mode, first_agent_utterance}
POST /api/lesson/turn   body {session_id, user_text} -> {agent_utterance, turn_index, done}

Scripted lessons can be started via /api/lesson/start (returns mode='scripted'
plus the first scripted agent utterance), but ongoing scripted dialogue still
uses the WebSocket flow at /ws/session.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server import coach_realtime, lesson_loader

router = APIRouter()


class StartReq(BaseModel):
    lesson_id: str


class StartResp(BaseModel):
    session_id: str
    mode: str
    first_agent_utterance: str


class TurnReq(BaseModel):
    session_id: str
    user_text: str


class TurnResp(BaseModel):
    agent_utterance: str
    turn_index: int
    done: bool


def _first_scripted_utterance(spec: lesson_loader.LessonSpec) -> str:
    for t in spec.turns or []:
        if t.get("speaker") == "agent":
            return str(t.get("say", ""))
    return ""


@router.post("/api/lesson/start", response_model=StartResp)
def lesson_start(req: StartReq) -> StartResp:
    try:
        spec = lesson_loader.load(req.lesson_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if spec.mode == "realtime":
        sid, first = coach_realtime.start_session(spec)
        return StartResp(session_id=sid, mode="realtime", first_agent_utterance=first)

    # scripted: still expose a session_id (lesson_id) and the opening line
    return StartResp(
        session_id=f"scripted:{spec.lesson_id}",
        mode="scripted",
        first_agent_utterance=_first_scripted_utterance(spec),
    )


@router.post("/api/lesson/turn", response_model=TurnResp)
def lesson_turn(req: TurnReq) -> TurnResp:
    try:
        result = coach_realtime.handle_turn(req.session_id, req.user_text)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return TurnResp(**result)
