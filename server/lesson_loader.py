"""Lesson loader supporting scripted (legacy) and realtime modes.

LessonSpec is the unified record. Scripted mode preserves the existing turns
list (used by the WebSocket flow); realtime mode declares only topic +
target_phrases + vocabulary + coach_persona, and turns are LLM-generated at
runtime by `server.coach_realtime`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal, Optional

import yaml

from server.config import load_config
from server.logging_setup import get_logger

_log = get_logger("lesson_loader")

Mode = Literal["scripted", "realtime"]
_VALID_MODES = ("scripted", "realtime")
_REALTIME_REQUIRED = ("topic", "target_phrases", "vocabulary", "coach_persona")


@dataclass
class ScriptedTurn:
    speaker: str
    data: dict


@dataclass
class LessonSpec:
    mode: Mode
    lesson_id: str
    title: str = ""
    week: int = 1
    topic: Optional[str] = None
    target_phrases: list[str] = field(default_factory=list)
    vocabulary: list[str] = field(default_factory=list)
    coach_persona: Optional[str] = None
    turns: Optional[list[dict]] = None


def _parse_mode(raw) -> Mode:
    if raw in _VALID_MODES:
        return raw  # type: ignore[return-value]
    if raw is not None:
        _log.warning("lesson_invalid_mode", value=str(raw), fallback="scripted")
    return "scripted"


def _validate_realtime(data: dict, lesson_id: str) -> None:
    for fname in _REALTIME_REQUIRED:
        v = data.get(fname)
        if v is None or (isinstance(v, (list, str)) and len(v) == 0):
            raise ValueError(f"realtime lesson missing field: {fname}")


def load_from_path(path: str) -> LessonSpec:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    lesson_id = str(data.get("id") or os.path.splitext(os.path.basename(path))[0])
    mode = _parse_mode(data.get("mode"))
    title = str(data.get("title", lesson_id))
    week = int(data.get("week", 1))

    if mode == "realtime":
        _validate_realtime(data, lesson_id)
        return LessonSpec(
            mode="realtime",
            lesson_id=lesson_id,
            title=title,
            week=week,
            topic=str(data["topic"]),
            target_phrases=list(data["target_phrases"]),
            vocabulary=list(data["vocabulary"]),
            coach_persona=str(data["coach_persona"]),
            turns=None,
        )

    return LessonSpec(
        mode="scripted",
        lesson_id=lesson_id,
        title=title,
        week=week,
        topic=data.get("topic"),
        target_phrases=list(data.get("target_phrases", [])),
        vocabulary=list(data.get("vocabulary", [])),
        coach_persona=data.get("coach_persona"),
        turns=list(data.get("turns", [])),
    )


def _resolve_lesson_path(lesson_id: str, curriculum_dir: Optional[str] = None) -> str:
    cdir = curriculum_dir or load_config().curriculum_dir
    if not os.path.isabs(cdir):
        cdir = os.path.join(os.getcwd(), cdir)
    if len(lesson_id) >= 4 and lesson_id[0] == "w" and "d" in lesson_id[1:]:
        try:
            week_part, day_part = lesson_id[1:].split("d", 1)
            week_num = int(week_part)
            int(day_part)  # validate
            candidate = os.path.join(cdir, f"week{week_num}", f"day{int(day_part)}.yml")
            if os.path.isfile(candidate):
                return candidate
        except ValueError:
            pass
    for root, _dirs, files in os.walk(cdir):
        for fn in files:
            if not fn.endswith((".yml", ".yaml")):
                continue
            full = os.path.join(root, fn)
            try:
                with open(full, encoding="utf-8") as f:
                    head = yaml.safe_load(f) or {}
                if str(head.get("id", "")) == lesson_id:
                    return full
            except Exception:
                continue
    raise FileNotFoundError(f"lesson not found: {lesson_id}")


def load(lesson_id: str, curriculum_dir: Optional[str] = None) -> LessonSpec:
    """Load a lesson by id (e.g. 'w1d1', 'w1d2'). Searches curriculum_dir."""
    path = _resolve_lesson_path(lesson_id, curriculum_dir=curriculum_dir)
    return load_from_path(path)
