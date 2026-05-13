"""Lesson loader (Phase 2): adds `mode: scripted|realtime` and validation.

Wraps the legacy `server.lesson.load_lesson` so the existing scripted path
keeps byte-identical behavior (W1D1 regression).

A scripted lesson uses pre-written `turns` from YAML.
A realtime lesson declares only `topic`, `target_phrases`, `vocabulary`,
and `coach_persona`; agent turns are LLM-generated at runtime.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

import yaml

from server.config import load_config
from server.lesson import LessonPlan, load_lesson as _load_scripted
from server.logging_setup import get_logger

_log = get_logger("lesson_loader")

Mode = Literal["scripted", "realtime"]
_VALID_MODES: tuple[str, ...] = ("scripted", "realtime")
_REALTIME_REQUIRED: tuple[str, ...] = ("topic", "target_phrases", "vocabulary", "coach_persona")


@dataclass
class ScriptedTurn:
    speaker: str
    data: Dict


@dataclass
class LessonSpec:
    mode: Mode
    lesson_id: str
    title: str = ""
    week: int = 1
    topic: Optional[str] = None
    target_phrases: List[str] = field(default_factory=list)
    vocabulary: List[str] = field(default_factory=list)
    coach_persona: Optional[str] = None
    turns: Optional[List[Dict]] = None

    def to_legacy_plan(self) -> LessonPlan:
        return LessonPlan(
            id=self.lesson_id,
            title=self.title or self.lesson_id,
            week=self.week,
            turns=list(self.turns or []),
        )


def _yaml_path_for(lesson_id: str) -> str:
    """`w1d2` or `W1D2` -> `<curriculum_dir>/week1/day2.yml`."""
    cfg = load_config()
    lid = lesson_id.upper()
    week = int(lid[1:lid.index("D")])
    day = int(lid[lid.index("D") + 1:])
    return os.path.join(cfg.curriculum_dir, f"week{week}", f"day{day}.yml")


def load(lesson_id: str) -> LessonSpec:
    """Load and validate a lesson by id (e.g. 'w1d1', 'w1d2')."""
    path = _yaml_path_for(lesson_id)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return _build_spec(data, fallback_id=lesson_id.lower())


def load_from_path(path: str) -> LessonSpec:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return _build_spec(data, fallback_id=str(data.get("id", "")))


def _build_spec(data: Dict, fallback_id: str) -> LessonSpec:
    raw_mode = data.get("mode")
    if raw_mode is None:
        mode: Mode = "scripted"
    elif raw_mode in _VALID_MODES:
        mode = raw_mode  # type: ignore[assignment]
    else:
        _log.warning("invalid_mode_falls_back_to_scripted", got=raw_mode)
        mode = "scripted"

    lesson_id = str(data.get("id", fallback_id))
    title = str(data.get("title", lesson_id))
    week = int(data.get("week", 1))

    if mode == "realtime":
        for key in _REALTIME_REQUIRED:
            if key not in data or data[key] in (None, "", []):
                raise ValueError(f"realtime lesson missing field: {key}")
        target_phrases = list(data["target_phrases"])
        vocabulary = list(data["vocabulary"])
        if not all(isinstance(p, str) for p in target_phrases):
            raise ValueError("realtime lesson missing field: target_phrases")
        if not all(isinstance(v, str) for v in vocabulary):
            raise ValueError("realtime lesson missing field: vocabulary")
        return LessonSpec(
            mode="realtime",
            lesson_id=lesson_id,
            title=title,
            week=week,
            topic=str(data["topic"]),
            target_phrases=target_phrases,
            vocabulary=vocabulary,
            coach_persona=str(data["coach_persona"]),
            turns=None,
        )

    return LessonSpec(
        mode="scripted",
        lesson_id=lesson_id,
        title=title,
        week=week,
        turns=list(data.get("turns", [])),
    )


def load_legacy_plan(lesson_id: str) -> LessonPlan:
    """Backwards-compatible helper: returns the existing `LessonPlan` shape.

    Used by callers that haven't migrated to `LessonSpec` yet so that the
    scripted W1D1 path stays byte-identical to its previous behavior."""
    path = _yaml_path_for(lesson_id)
    return _load_scripted(path)
