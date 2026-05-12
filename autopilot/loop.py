"""Autopilot main loop: discover -> pick -> spawn -> verify -> branch-commit."""
import datetime
import os
import subprocess
from dataclasses import dataclass
from typing import List, Optional

from autopilot.backlog import Backlog, Item
from autopilot.killswitch import is_paused
from autopilot.triggers.from_test_fails import discover as t_tests
from autopilot.triggers.from_session_logs import discover as t_logs
from autopilot.triggers.from_eval_drift import discover as t_eval
from autopilot.triggers.from_repo_scan import discover as t_repo
from server.logging_setup import get_logger

_log = get_logger("autopilot")


@dataclass
class LoopResult:
    status: str  # paused | idle | committed | needs_human | error
    item_slug: Optional[str] = None
    branch: Optional[str] = None
    detail: str = ""


def _collect_all_triggers() -> List[Item]:
    items: List[Item] = []
    for fn in (t_tests, t_logs, t_eval, t_repo):
        try:
            items.extend(fn())
        except Exception as e:
            _log.warning("trigger_failed", trigger=fn.__module__, error=str(e))
    return items


def _spawn_claude(item: Item, worktree: str):
    """Run `claude -p` headless inside the worktree. Returns the CompletedProcess."""
    cmd = ["claude", "-p", item.prompt, "--cwd", worktree]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60 * 30)


def _verify(worktree: str) -> bool:
    """Run unit + eval suites inside the worktree."""
    try:
        r1 = subprocess.run(["python", "-m", "pytest", "tests/unit", "-q"],
                            cwd=worktree, capture_output=True, text=True, timeout=600)
        r2 = subprocess.run(["python", "-m", "pytest", "tests/eval", "-q"],
                            cwd=worktree, capture_output=True, text=True, timeout=600)
        return r1.returncode == 0 and r2.returncode == 0
    except Exception as e:
        _log.error("verify_failed", error=str(e))
        return False


def _commit_to_branch(worktree: str, slug: str) -> str:
    today = datetime.date.today().isoformat()
    branch = f"autopilot/{today}-{slug}"
    subprocess.run(["git", "-C", worktree, "checkout", "-b", branch], check=False)
    subprocess.run(["git", "-C", worktree, "add", "-A"], check=False)
    subprocess.run(
        ["git", "-C", worktree, "commit", "-m", f"[auto] {slug}"],
        check=False,
    )
    return branch


def _make_worktree(slug: str) -> str:
    today = datetime.date.today().isoformat()
    path = os.path.join(".claude", "worktrees", f"autopilot-{today}-{slug}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(["git", "worktree", "add", "-b", f"wt-{today}-{slug}", path], check=False)
    return path


def run_once(pause_path: str = "autopilot/PAUSE",
             backlog_path: str = "autopilot/backlog.jsonl") -> LoopResult:
    if is_paused(pause_path):
        _log.info("autopilot_paused")
        return LoopResult(status="paused")

    bl = Backlog(path=backlog_path)
    for item in _collect_all_triggers():
        bl.add(item)

    picked = bl.pick()
    if picked is None:
        return LoopResult(status="idle")

    _log.info("autopilot_pick", slug=picked.slug, priority=picked.priority, source=picked.source)
    worktree = _make_worktree(picked.slug)
    proc = _spawn_claude(picked, worktree)
    _log.info("claude_done", slug=picked.slug, rc=proc.returncode)

    if not _verify(worktree):
        bl.add(Item(slug=picked.slug, priority=picked.priority, source=picked.source,
                    prompt=picked.prompt, tags=list(set(picked.tags + ["needs-human"]))))
        return LoopResult(status="needs_human", item_slug=picked.slug, detail="verify_failed")

    branch = _commit_to_branch(worktree, picked.slug)
    bl.mark_done(picked.slug)
    return LoopResult(status="committed", item_slug=picked.slug, branch=branch)
