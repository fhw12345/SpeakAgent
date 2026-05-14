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


def _claude_executable() -> str:
    """Locate the claude CLI binary. On Windows this is usually claude.cmd
    in npm's global bin; subprocess won't find .cmd without shell=True or
    an explicit name."""
    import shutil
    found = shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe")
    if not found:
        raise RuntimeError("claude CLI not found on PATH")
    return found


def _spawn_claude(item: Item, worktree: str):
    """Run `claude -p` headless inside the worktree. Returns the CompletedProcess.

    All subagents use opus and bypass permission prompts (autopilot is unattended).
    Force UTF-8 decoding so non-ASCII output (e.g. from emoji or CJK) doesn't
    crash on Windows where the default locale is cp936/GBK.
    """
    exe = _claude_executable()
    cmd = [
        exe, "-p",
        "--model", "opus",
        "--permission-mode", "bypassPermissions",
        item.prompt,
    ]
    _log.info("spawn_claude_start", slug=item.slug, worktree=worktree, exe=exe)
    proc = subprocess.run(
        cmd, capture_output=True, timeout=60 * 30, cwd=worktree,
        text=True, encoding="utf-8", errors="replace",
    )
    _log.info("spawn_claude_done", slug=item.slug, rc=proc.returncode,
              stdout_chars=len(proc.stdout or ""), stderr_chars=len(proc.stderr or ""),
              stdout_tail=(proc.stdout or "")[-300:])
    return proc


def _spawn_runner(item: Item, worktree: str):
    """Dispatch to the configured runner. Selected by AUTOPILOT_RUNNER env
    var: 'claude' (default, legacy) or 'openhands'. Both return a
    subprocess.CompletedProcess with .returncode/.stdout/.stderr."""
    runner = os.environ.get("AUTOPILOT_RUNNER", "claude").lower()
    if runner == "openhands":
        from autopilot.runners.openhands_runner import spawn_openhands
        _log.info("spawn_runner", runner="openhands", slug=item.slug, worktree=worktree)
        proc = spawn_openhands(item, worktree)
        # OpenHands writes its trajectory to stderr; stdout is just the
        # entrypoint banner. Tail stderr instead so the log shows the
        # agent's last action, not "Starting OpenHands...".
        trajectory = proc.stderr or proc.stdout or ""
        _log.info("spawn_runner_done", runner="openhands", slug=item.slug,
                  rc=proc.returncode,
                  stdout_chars=len(proc.stdout or ""),
                  stderr_chars=len(proc.stderr or ""),
                  trajectory_tail=trajectory[-300:])
        return proc
    return _spawn_claude(item, worktree)


def _verify(worktree: str) -> bool:
    """Run unit + eval + e2e suites inside the worktree.

    e2e is best-effort: if Playwright/chromium not installed in the
    worktree's environment we skip rather than fail (so autopilot can
    still iterate on backend-only changes).
    """
    try:
        r1 = subprocess.run(["python", "-m", "pytest", "tests/unit", "-q"],
                            cwd=worktree, capture_output=True, text=True, timeout=600)
        r2 = subprocess.run(["python", "-m", "pytest", "tests/eval", "-q"],
                            cwd=worktree, capture_output=True, text=True, timeout=600)
        unit_ok = r1.returncode == 0
        eval_ok = r2.returncode == 0
        _log.info("verify_unit_eval", unit_rc=r1.returncode, eval_rc=r2.returncode)
        if not (unit_ok and eval_ok):
            return False

        # E2E is opt-in: check if tests/e2e exists AND playwright importable
        e2e_dir = os.path.join(worktree, "tests", "e2e")
        if not os.path.isdir(e2e_dir):
            _log.info("verify_e2e_skipped", reason="no_e2e_dir")
            return True
        check = subprocess.run(["python", "-c", "import playwright"],
                               cwd=worktree, capture_output=True, text=True, timeout=10)
        if check.returncode != 0:
            _log.info("verify_e2e_skipped", reason="playwright_missing")
            return True
        r3 = subprocess.run(["python", "-m", "pytest", "tests/e2e", "-q"],
                            cwd=worktree, capture_output=True, text=True, timeout=900)
        _log.info("verify_e2e", rc=r3.returncode,
                  stdout_tail=(r3.stdout or "")[-400:])
        return r3.returncode == 0
    except Exception as e:
        _log.error("verify_failed", error=str(e))
        return False


def _commit_to_branch(worktree: str, slug: str) -> str:
    """Add + commit any changes in the worktree. Branch is already created
    by _make_worktree, so we just need to stage and commit."""
    today = datetime.date.today().isoformat()
    branch = f"autopilot/{today}-{slug}"
    subprocess.run(["git", "-C", worktree, "add", "-A"],
                   capture_output=True, text=True)
    proc = subprocess.run(
        ["git", "-C", worktree, "commit", "-m", f"[auto] {slug}"],
        capture_output=True, text=True,
    )
    _log.info("commit_to_branch", branch=branch, rc=proc.returncode,
              stdout=proc.stdout[:200], stderr=proc.stderr[:200])
    return branch


def _repo_root() -> str:
    """Find the main repo root (the .git dir, not a worktree's .git file)."""
    proc = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                          capture_output=True, text=True, check=True)
    common_dir = proc.stdout.strip()
    return os.path.dirname(os.path.abspath(common_dir))


def _make_worktree(slug: str) -> str:
    """Create a fresh git worktree under the MAIN repo's .claude/worktrees/.

    Branched off the CURRENT HEAD (not main) so the subagent sees:
    - the autopilot/prds/ directory it needs to read for context
    - the latest spec, curriculum, code, and tests
    - any in-progress work on this development branch

    Avoids nesting (we may already be inside a worktree). Branch named
    autopilot/<date>-<slug> so commits land on the policy-mandated prefix
    automatically.
    """
    today = datetime.date.today().isoformat()
    repo = _repo_root()
    path = os.path.join(repo, ".claude", "worktrees", f"autopilot-{today}-{slug}")
    branch = f"autopilot/{today}-{slug}"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Resolve our current HEAD to a SHA so the new worktree branches from it.
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    proc = subprocess.run(
        ["git", "-C", repo, "worktree", "add", "-b", branch, path, head_sha],
        capture_output=True, text=True,
    )
    _log.info("make_worktree", path=path, branch=branch, base_sha=head_sha[:8],
              rc=proc.returncode,
              stderr=proc.stderr[:200] if proc.stderr else "")
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
    proc = _spawn_runner(picked, worktree)
    _log.info("claude_done", slug=picked.slug, rc=proc.returncode)

    if not _verify(worktree):
        bl.add(Item(slug=picked.slug, priority=picked.priority, source=picked.source,
                    prompt=picked.prompt, tags=list(set(picked.tags + ["needs-human"]))))
        return LoopResult(status="needs_human", item_slug=picked.slug, detail="verify_failed")

    branch = _commit_to_branch(worktree, picked.slug)
    bl.mark_done(picked.slug)
    return LoopResult(status="committed", item_slug=picked.slug, branch=branch)
