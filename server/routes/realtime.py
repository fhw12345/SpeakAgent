"""REST endpoints for realtime lessons:

- POST /api/lesson/start  body {lesson_id} -> {session_id, mode, first_agent_utterance}
- POST /api/lesson/turn   body {session_id, user_text} -> {agent_utterance, turn_index, done}

Scripted lessons are still served via the existing /ws/session WebSocket path.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server import coach_realtime
from server.lesson import load_lesson
from server.lesson_catalog import _yaml_path_for


router = APIRouter()


class StartRequest(BaseModel):
    lesson_id: str


class TurnRequest(BaseModel):
    session_id: str
    user_text: str


@router.post("/api/lesson/start")
def lesson_start(req: StartRequest):
    try:
        path = _yaml_path_for(req.lesson_id.upper())
    except (ValueError, IndexError) as e:
        raise HTTPException(status_code=400, detail=f"invalid lesson_id: {req.lesson_id}") from e
    try:
        plan = load_lesson(path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"lesson not found: {req.lesson_id}") from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    if plan.mode == "realtime":
        session_id, first = coach_realtime.start_session(plan)
        return {
            "session_id": session_id,
            "mode": "realtime",
            "first_agent_utterance": first,
        }

    first_utterance = ""
    for turn in plan.turns:
        if turn.get("speaker") == "agent":
            first_utterance = turn.get("say", "")
            break
    return {
        "session_id": "",
        "mode": "scripted",
        "first_agent_utterance": first_utterance,
    }


@router.post("/api/lesson/turn")
def lesson_turn(req: TurnRequest):
    try:
        return coach_realtime.handle_turn(req.session_id, req.user_text)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=f"unknown session_id: {req.session_id}") from e
