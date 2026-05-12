"""B13 smoke: spawn one real claude -p in a real worktree.

Doesn't use run_once or backlog; constructs a minimal Item directly so we
can inspect each step in isolation.
"""
import sys
from autopilot.backlog import Item
from autopilot.loop import _spawn_claude, _make_worktree, _verify, _commit_to_branch
from server.logging_setup import configure_logging, get_logger

configure_logging()
_log = get_logger("b13_smoke")


def main():
    item = Item(
        slug="b13-smoke-readme-line",
        priority=1,
        source="b13_smoke",
        prompt=(
            "Append exactly one line `autopilot smoke test ok` to the end of README.md "
            "in the current working directory. Make sure README.md ends with a single "
            "newline after the appended line. Do not modify any other file. "
            "After the append, commit the change with message 'chore: B13 smoke'."
        ),
    )

    print("=" * 60)
    print("STEP 1: make worktree")
    print("=" * 60)
    wt = _make_worktree(item.slug)
    print(f"  -> worktree at: {wt}")

    print()
    print("=" * 60)
    print("STEP 2: spawn claude -p")
    print("=" * 60)
    proc = _spawn_claude(item, wt)
    print(f"  rc: {proc.returncode}")
    print(f"  stdout (first 500 chars):\n{proc.stdout[:500]}")
    print(f"  stderr (first 500 chars):\n{proc.stderr[:500]}")

    print()
    print("=" * 60)
    print("STEP 3: verify (skip — no tests changed)")
    print("=" * 60)
    print("  (skipping verify for smoke; we just want to see the README change)")

    print()
    print("=" * 60)
    print("STEP 4: inspect README in worktree")
    print("=" * 60)
    import os
    readme = os.path.join(wt, "README.md")
    if os.path.exists(readme):
        with open(readme, "rb") as f:
            data = f.read()
        print(f"  README size: {len(data)} bytes")
        print(f"  last 100 bytes: {data[-100:]!r}")
        if b"autopilot smoke test ok" in data:
            print("  [OK] marker line PRESENT")
        else:
            print("  [FAIL] marker line MISSING")
    else:
        print(f"  [FAIL] README.md not found at {readme}")

    print()
    print("=" * 60)
    print("STEP 5: git status in worktree")
    print("=" * 60)
    import subprocess
    s = subprocess.run(["git", "-C", wt, "status", "--porcelain"], capture_output=True, text=True)
    print(s.stdout or "  (clean)")
    log = subprocess.run(["git", "-C", wt, "log", "--oneline", "-5"], capture_output=True, text=True)
    print("Recent log:")
    print(log.stdout)


if __name__ == "__main__":
    main()
