"""Lesson loader supporting scripted and realtime modes (Phase 2)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Literal, Optional

import yaml

from server.config import load_config
from server.logging_setup import get_logger

_log = get_logger("lesson_loader")

VALID_MODES = ("scripted", "realtime")
_REALTIME_REQUIRED = ("topic", "target_phrases", "vocabulary", "coach_persona")


@dataclass
class LessonSpec:
    mode: Literal["scripted", "realtime"]
    lesson_id: str
    title: str = ""
    week: int = 1
    topic: Optional[str] = None
    target_phrases: List[str] = field(default_factory=list)
    vocabulary: List[str] = field(default_factory=list)
    coach_persona: Optional[str] = None
    turns: Optional[List[dict]] = None


def _resolve_lesson_path(lesson_id: str) -> Path:
    cfg = load_config()
    base = Path(os.environ.get("SPEAKAGENT_CURRICULUM_DIR", cfg.curriculum_dir))
    if not base.is_absolute():
        base = Path(__file__).resolve().parent.parent / base
    lid = lesson_id.lower()
    if not lid.startswith("w") or "d" not in lid:
        raise FileNotFoundError(f"unknown lesson_id: {lesson_id}")
    week_part, _, day_part = lid.partition("d")
    week = week_part[1:]
    return base / f"week{week}" / f"day{day_part}.yml"


def load(lesson_id: str) -> LessonSpec:
    """Load a lesson by id (e.g. 'w1d1'). Returns a validated LessonSpec."""
    path = _resolve_lesson_path(lesson_id)
    return load_from_path(str(path))


def load_from_path(path: str) -> LessonSpec:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    raw_mode = data.get("mode", "scripted")
    if raw_mode not in VALID_MODES:
        _log.warning("invalid_mode_falling_back", mode=raw_mode, lesson_id=data.get("id"))
        mode = "scripted"
    else:
        mode = raw_mode

    lesson_id = data.get("id", "")
    title = data.get("title", lesson_id)
    week = int(data.get("week", 1))

    if mode == "realtime":
        for fname in _REALTIME_REQUIRED:
            if fname not in data or data[fname] in (None, "", []):
                raise ValueError(f"realtime lesson missing field: {fname}")
        return LessonSpec(
            mode="realtime",
            lesson_id=lesson_id,
            title=title,
            week=week,
            topic=data["topic"],
            target_phrases=list(data["target_phrases"]),
            vocabulary=list(data["vocabulary"]),
            coach_persona=data["coach_persona"],
            turns=None,
        )

    return LessonSpec(
        mode="scripted",
        lesson_id=lesson_id,
        title=title,
        week=week,
        turns=list(data.get("turns", [])),
    )
