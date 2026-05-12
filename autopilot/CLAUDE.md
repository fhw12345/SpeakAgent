# Autopilot scope (repo-local opt-in)

This repository **opts into autonomous mode** for the autopilot subsystem only.
The autopilot loop may iterate without per-step user approval, subject to:

- All commits go to `autopilot/<date>-<slug>` branches. **Never to `main`.**
- The escalation list in `autopilot/policies/escalation.yml` is non-negotiable: matching items file to `autopilot/inbox.md` and stop.
- Rate limit in `autopilot/policies/rate_limit.yml` caps LLM call rate (anti-runaway, not budget).
- Presence of file `autopilot/PAUSE` halts the loop within 60s.
- Single-task concurrency on the main code base.

When the autopilot dispatches a child `claude -p` agent, the child operates inside a fresh worktree under `.claude/worktrees/autopilot-<date>-<slug>/` and runs the project test suite + eval suite before any commit.
