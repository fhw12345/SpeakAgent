"""Cluster repeated low-score issues across recent session logs."""
import glob
import json
import os
from collections import Counter
from typing import List
from autopilot.backlog import Item


def discover(sessions_dir: str = "data/sessions", threshold: int = 3) -> List[Item]:
    issue_counts: Counter[str] = Counter()
    for path in glob.glob(os.path.join(sessions_dir, "*.jsonl")):
        seen_in_session: set[str] = set()
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    d = json.loads(line)
                    score = d.get("score") or {}
                    if int(score.get("content_score", 5)) >= 3:
                        continue
                    for issue in score.get("issues", []):
                        seen_in_session.add(str(issue))
        except Exception:
            continue
        for issue in seen_in_session:
            issue_counts[issue] += 1

    items: List[Item] = []
    for issue, count in issue_counts.items():
        if count >= threshold:
            slug = "session-issue-" + issue.replace(" ", "-")[:50]
            items.append(Item(
                slug=slug,
                priority=6,
                source="session_logs",
                prompt=(
                    f"User has hit the issue `{issue}` in {count} distinct sessions. "
                    f"Investigate scorer/coach/curriculum changes that could reduce this. "
                    f"Add a regression fixture under tests/eval/ that captures the desired improvement."
                ),
            ))
    return items
