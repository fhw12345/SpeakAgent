"""Lesson plan loader (YAML)."""
from dataclasses import dataclass, field
from typing import List, Dict
import yaml


@dataclass
class LessonPlan:
    id: str
    title: str
    week: int
    turns: List[Dict] = field(default_factory=list)


def load_lesson(path: str) -> LessonPlan:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return LessonPlan(
        id=data["id"],
        title=data.get("title", data["id"]),
        week=int(data.get("week", 1)),
        turns=list(data.get("turns", [])),
    )
