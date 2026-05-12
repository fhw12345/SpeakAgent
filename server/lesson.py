"""Lesson plan loader (YAML).

Supports two modes:
  - scripted (default): pre-written agent + user turns
  - realtime: only declares topic, target_phrases, vocabulary, coach_persona;
    agent turns are LLM-generated at runtime by server.coach_realtime.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Literal
import yaml

from server.logging_setup import get_logger


_log = get_logger("lesson")

VALID_MODES = ("scripted", "realtime")
REALTIME_REQUIRED_FIELDS = ("topic", "target_phrases", "vocabulary", "coach_persona")


@dataclass
class LessonPlan:
    id: str
    title: str
    week: int
    turns: List[Dict] = field(default_factory=list)
    mode: Literal["scripted", "realtime"] = "scripted"
    topic: Optional[str] = None
    target_phrases: List[str] = field(default_factory=list)
    vocabulary: List[str] = field(default_factory=list)
    coach_persona: Optional[str] = None


def _parse_mode(raw, lesson_id: str) -> str:
    if raw is None:
        return "scripted"
    if raw in VALID_MODES:
        return raw
    _log.warning("lesson_invalid_mode_fallback", lesson_id=lesson_id, mode=raw)
    return "scripted"


def load_lesson(path: str) -> LessonPlan:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    lesson_id = data["id"]
    mode = _parse_mode(data.get("mode"), lesson_id)

    if mode == "realtime":
        for fname in REALTIME_REQUIRED_FIELDS:
            if fname not in data or data[fname] in (None, "", []):
                raise ValueError(f"realtime lesson missing field: {fname}")
        target_phrases = list(data["target_phrases"])
        vocabulary = list(data["vocabulary"])
        if not isinstance(target_phrases, list) or not all(isinstance(p, str) for p in target_phrases):
            raise ValueError("realtime lesson missing field: target_phrases")
        if not isinstance(vocabulary, list) or not all(isinstance(v, str) for v in vocabulary):
            raise ValueError("realtime lesson missing field: vocabulary")
        return LessonPlan(
            id=lesson_id,
            title=data.get("title", lesson_id),
            week=int(data.get("week", 1)),
            turns=[],
            mode="realtime",
            topic=str(data["topic"]),
            target_phrases=target_phrases,
            vocabulary=vocabulary,
            coach_persona=str(data["coach_persona"]),
        )

    return LessonPlan(
        id=lesson_id,
        title=data.get("title", lesson_id),
        week=int(data.get("week", 1)),
        turns=list(data.get("turns", [])),
        mode="scripted",
    )
