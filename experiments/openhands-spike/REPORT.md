# OpenHands Hybrid Spike — Report

**Date:** 2026-05-14
**Goal:** Verify OpenHands headless can replace `_spawn_claude` in `autopilot/loop.py`
**Target task:** sentence-splitter (Phase 3 backlog item)
**Result:** ✅ Wiring works; ⚠️ several Windows/path warts to handle

---

## What worked

1. **GHCR mirror** for both images (`docker.all-hands.dev` was unreachable in CN; `ghcr.io/all-hands-ai/{openhands,runtime}` worked). Re-tagged locally so OpenHands defaults find them.
2. **Local Claude gateway** (`http://localhost:23333/api/anthropic`) worked from inside the container via `host.docker.internal` + `--add-host host.docker.internal:host-gateway`. Model id `anthropic/claude-opus-4.7-1m-internal[1m]` accepted by litellm.
3. **CodeActAgent loop** completed in **~47s, 14 actions**:
   - Read PRD, listed workspace, read existing files, ran `pytest`, observed 7 tests pass, attempted `git status`, hit a path issue, recovered with `AgentThinkAction`, then `AgentFinishAction` with a clean summary asking the host to commit.
4. **Trajectory log** (`run-2.log`, 431 lines) is a structured ACTION/OBSERVATION stream — far richer than autopilot's current "log a few lines + stdout tail."
5. **Agent self-diagnosed** the broken `.git` file in the worktree (Windows path inside Linux container) and refused to commit rather than crashing. This is exactly the "graceful failure" autopilot lacks.

## What broke (and how I fixed)

| Issue | Root cause | Fix |
|---|---|---|
| `docker.all-hands.dev` unreachable | DNS blocked in CN | `docker pull` from `ghcr.io/all-hands-ai/...` then `docker tag` to the all-hands.dev name |
| `pip install openhands-ai` failed (e2b conflict) | The PyPI package is unmaintained (v0.8.3 vs current v0.40+) | Don't use pip — use the Docker image |
| `mount denied: too many colons` | `WORKSPACE_MOUNT_PATH=D:/...` confused Docker's `-v src:dst` parser | Use `SANDBOX_VOLUMES=/d/repo/...:/workspace:rw` (POSIX path) instead |
| `MSYS_NO_PATHCONV=1` needed | Git Bash on Windows mangles `/app`, `/workspace` etc into Windows paths | Set the env var before every `docker run` |
| `git` ops fail inside sandbox | `.git` file in worktree points to a Windows host path that doesn't exist in the Linux container | OpenHands sandbox can't `git commit` against host worktrees. Either (a) commit on host after the run, or (b) mount the parent `.git/worktrees/<name>` dir too, or (c) use a sandbox-internal copy |

## What this means for "replace `_spawn_claude` with OpenHands"

### Pros (vs current `_spawn_claude`)
- **Long-running event loop** with ACTION/OBSERVATION trajectory — replayable, debuggable, much better than tail of stdout
- **Self-diagnosis** of environment issues (the agent thought "git is broken, I'll skip and tell the host")
- **Real sandbox isolation** (Docker runtime container per task) — much stronger than git worktree
- **Built-in iteration cap** (`-i 30`) and budget cap (`-b $$`)
- **MCP-ready**: OpenHands has `openhands/mcp/` — could expose autopilot's policies/triggers as MCP tools to the agent
- **No PRD-context-loss problem**: agent runs in the worktree and reads the PRD file directly

### Cons / open issues to solve before swap
1. **Git workflow inside Docker sandbox is broken on Windows**. Need to either bind-mount `.git/worktrees/<slug>` so the gitfile resolves, or run autopilot's commit logic on the host after `docker run` returns (current `_commit_to_branch` already runs from outside — this is fine, just means we lose "agent commits its own work").
2. **Runtime image is 12.9 GB**. First-time pull is heavy. Cached after that. Acceptable.
3. **`MSYS_NO_PATHCONV=1` env var contagion**. Anyone running this from Git Bash needs it. Wrapper script handles.
4. **Backlog ↔ reality drift**. Most "open" backlog items are actually done on main but not marked. Independent of OpenHands — autopilot needs a "scan main for completed items" reconciler.

## Recommended next step

Write a PRD for **`autopilot/runners/openhands_runner.py`** that:

1. Replaces `_spawn_claude(item, worktree)` with `_spawn_openhands(item, worktree)` — same signature, different impl.
2. Uses `subprocess.run` to invoke `docker run … openhands/openhands python -m openhands.core.main -t "$task" -i 30`.
3. Translates Windows worktree path to POSIX (`/d/...`) before passing to `SANDBOX_VOLUMES`.
4. Forces `MSYS_NO_PATHCONV=1` in subprocess env.
5. Captures `run-N.log` trajectory to `autopilot/runs/<date>-<slug>/trajectory.log`.
6. Keeps existing `_verify` + `_commit_to_branch` (run on host, no change) — agent doesn't need to git itself.
7. Behind a `runner: openhands | claude` flag in backlog Item so we can A/B per-item.

Estimated effort: **0.5–1 day** to add the runner module + wrap path translation; existing autopilot scaffolding (worktree, verify, branch, escalation, PAUSE, rate_limit) stays.

## Decision

**Recommend: Hybrid (Option B from the earlier discussion).**

OpenHands is a strict upgrade for the worker tier. The autopilot scheduling layer (intake/PRD/backlog/triggers/policies) stays — that's your business logic and OpenHands has nothing equivalent. Only swap `_spawn_claude` → `_spawn_openhands`.

---

## Artifacts

- `experiments/openhands-spike/config.toml` — OpenHands config used (also passed via env)
- `experiments/openhands-spike/task.txt` — the prompt fed to the agent
- `experiments/openhands-spike/run-2.log` — full ACTION/OBSERVATION trajectory (431 lines)
- `experiments/openhands-spike/state/` — OpenHands state dir (sessions, conversations)
- Worktree `.claude/worktrees/openhands-spike/` on branch `openhands-spike/sentence-splitter` — left intact for inspection
