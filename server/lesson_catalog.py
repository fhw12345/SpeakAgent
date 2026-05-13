"""Lesson catalog: builds the 56-lesson (8 weeks x 7 days) course list."""
from __future__ import annotations

import os
from typing import Optional

import yaml

from server.config import load_config
from server.logging_setup import get_logger

_log = get_logger("lesson_catalog")

WEEKS = 8
DAYS_PER_WEEK = 7
TOTAL_LESSONS = WEEKS * DAYS_PER_WEEK


def _yaml_path_for(lesson_id: str) -> str:
    """W1D1 -> {curriculum_dir}/week1/day1.yml"""
    cfg = load_config()
    week = int(lesson_id[1:lesson_id.index("D")])
    day = int(lesson_id[lesson_id.index("D") + 1:])
    return os.path.join(cfg.curriculum_dir, f"week{week}", f"day{day}.yml")


def load_lesson_title(lesson_id: str) -> Optional[str]:
    """Read the `title` field from the lesson YAML. Returns None if missing/malformed."""
    path = _yaml_path_for(lesson_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (yaml.YAMLError, OSError) as e:
        _log.warning("lesson_yaml_unreadable", lesson_id=lesson_id, path=path, err=str(e))
        return None
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        _log.warning("lesson_yaml_missing_title", lesson_id=lesson_id, path=path)
        return None
    return title


def build_catalog() -> list[dict]:
    """Build the 56-lesson catalog. A lesson is `available` iff its YAML exists."""
    out: list[dict] = []
    order = 1
    for week in range(1, WEEKS + 1):
        for day in range(1, DAYS_PER_WEEK + 1):
            lesson_id = f"W{week}D{day}"
            available = os.path.isfile(_yaml_path_for(lesson_id))
            if available:
                title = load_lesson_title(lesson_id) or f"Lesson {lesson_id}"
            else:
                title = "Coming soon"
            out.append({
                "id": lesson_id,
                "week": week,
                "day": day,
                "title": title,
                "available": available,
                "order": order,
            })
            order += 1
    return out
