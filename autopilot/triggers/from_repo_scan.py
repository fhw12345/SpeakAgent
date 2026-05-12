"""Daily scan of user's personal repos. Proposes (never auto-merges) updates to personal_projects.json."""
import json
import os
import subprocess
from typing import List
from autopilot.backlog import Item


_KEYWORDS = ("add", "implement", "support", "introduce", "feat", "feature")


def _git_log_since(repo_path: str, since: str = "7.days") -> str:
    try:
        out = subprocess.check_output(
            ["git", "-C", repo_path, "log", f"--since={since}", "--oneline"],
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        return out.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def discover(personal_projects_path: str = "data/personal_projects.json") -> List[Item]:
    if not os.path.exists(personal_projects_path):
        return []
    with open(personal_projects_path, encoding="utf-8") as f:
        projects = json.load(f)
    items: List[Item] = []
    for p in projects:
        log = _git_log_since(p.get("repo_path", ""))
        if not log:
            continue
        if not any(k in log.lower() for k in _KEYWORDS):
            continue
        items.append(Item(
            slug=f"refresh-personal-{p['id']}",
            priority=3,
            source="repo_scan",
            tags=["needs-human"],
            prompt=(
                f"Personal project '{p['name']}' (id={p['id']}) has new commits in the last 7 days:\n"
                f"{log}\n"
                f"Draft a proposed update to data/personal_projects.json (new interview_angles or "
                f"hard_words) and file it for human review. Do NOT auto-merge."
            ),
        ))
    return items
