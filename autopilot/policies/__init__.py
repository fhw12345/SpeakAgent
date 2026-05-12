"""Loads and evaluates rate-limit + escalation policies."""
import fnmatch
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Dict
import yaml


_HERE = os.path.dirname(__file__)


@dataclass
class RateLimitCfg:
    max_calls_per_minute: int = 60
    pause_seconds_on_trip: int = 60
    trips_per_hour_before_escalate: int = 3


def load_rate_limit(path: str | None = None) -> RateLimitCfg:
    p = path or os.path.join(_HERE, "rate_limit.yml")
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return RateLimitCfg(
        max_calls_per_minute=int(data.get("max_calls_per_minute", 60)),
        pause_seconds_on_trip=int(data.get("pause_seconds_on_trip", 60)),
        trips_per_hour_before_escalate=int(data.get("trips_per_hour_before_escalate", 3)),
    )


@dataclass
class RateLimiter:
    max_calls_per_minute: int = 60
    _hits: Deque[float] = field(default_factory=deque)

    def allow(self) -> bool:
        now = time.monotonic()
        while self._hits and self._hits[0] < now - 60.0:
            self._hits.popleft()
        if len(self._hits) >= self.max_calls_per_minute:
            return False
        self._hits.append(now)
        return True


def load_escalation(path: str | None = None) -> List[Dict]:
    p = path or os.path.join(_HERE, "escalation.yml")
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return list(data.get("patterns", []))


def matches_escalation(rules: List[Dict], files: List[str], diff_summary: str) -> bool:
    diff_lc = (diff_summary or "").lower()
    for rule in rules:
        for g in rule.get("file_globs", []) or []:
            if any(fnmatch.fnmatch(f, g) for f in files):
                return True
        for kw in rule.get("diff_keywords", []) or []:
            if kw.lower() in diff_lc:
                return True
    return False
