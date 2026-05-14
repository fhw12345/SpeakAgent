# Autopilot scope (repo-local opt-in)

This repository **opts into autonomous mode** for the autopilot subsystem only.
The autopilot loop may iterate without per-step user approval, subject to:

- All commits go to `autopilot/<date>-<slug>` branches. **Never to `main`.**
- The escalation list in `autopilot/policies/escalation.yml` is non-negotiable: matching items file to `autopilot/inbox.md` and stop.
- Rate limit in `autopilot/policies/rate_limit.yml` caps LLM call rate (anti-runaway, not budget).
- Presence of file `autopilot/PAUSE` halts the loop within 60s.
- Single-task concurrency on the main code base.

When the autopilot dispatches a child `claude -p` agent, the child operates inside a fresh worktree under `.claude/worktrees/autopilot-<date>-<slug>/` and runs the project test suite + eval suite before any commit.

## Runner selection

The worker that executes a backlog item is pluggable, controlled by env var `AUTOPILOT_RUNNER`:

- `claude` (default, legacy) — `claude -p --model opus --permission-mode bypassPermissions`. Fast, no Docker dep, but stdout-only trajectory and brittle on partial completions.
- `openhands` — `docker run … openhands/openhands python -m openhands.core.main`. Long-lived event-loop with full ACTION/OBSERVATION trajectory, real Docker sandbox per task, self-diagnoses environment issues. Requires Docker Desktop running and the `docker.all-hands.dev/all-hands-ai/{openhands,runtime}` images available locally (see `experiments/openhands-spike/REPORT.md` for the GHCR-mirror retag trick on networks where the default registry is unreachable).

Both runners return a `subprocess.CompletedProcess` so the rest of the loop (verify gate, branch commit, escalation) is unchanged. Switching is purely an env-var flip; no code changes needed per task.
