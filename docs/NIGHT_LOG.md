# Night log — 2026-05-13 (post-mortem)

**Status: autopilot ran for 4.5 hours unattended, processed all 22 backlog items, produced 18 real implementation branches. NEEDS YOUR JUDGMENT before merging — they were all branched from the same base, so there are file-level conflicts to reconcile.**

## Timeline

- 17:07 launched `python -m autopilot.main --interval 30 --max-iterations 25`
- 21:37 completed iteration 25 (22 items + 3 idle ticks)
- During the run I (your morning Claude session) misdiagnosed the background task as "exited" because the Bash tool wrapper returned, but the actual python+nohup subprocess kept running.

## What happened

- 22 backlog items dispatched, one at a time
- 18 of 22 spawns produced real commits in their own branches (subagents commit themselves; autopilot's own `_commit_to_branch` adds a no-op since there's nothing left to commit, then misreports it as "committed" — see KNOWN BUGS)
- 4 of 22 produced no work:
  - `llm-client` — claude.cmd exited rc=4294967295 (Windows -1) after 2m14s with no stdout. Probably gateway hiccup at 17:07. This is the FIRST item, so the 17 downstream items that depended on it had to do their own ad-hoc llm client (and they did — multiple branches now have their own variant).
  - `docs-spec-update`, `vad-segmenter`, `web-audio-worklet-and-mic-client` — worktree HEADs unchanged from base sha. Need to inspect logs for cause.
- All 22 items got `needs_human` tag in backlog because verify (`tests/unit + tests/eval + tests/e2e`) failed. **This is expected** — each branch only has its own piece of Phase 2/3/4 and tests for everything else are missing imports.

## What's actually built (verified by inspecting commits)

### Phase 2 — Realtime turn mode
- `coach-realtime` (`10619be`): server/lesson_loader.py, coach_realtime.py, /api/lesson/start, /api/lesson/turn, llm_client.py with LLM_MOCK
- `coach-dispatch-and-api` (`fc1bc99`): REST routes
- `lesson-loader` (`5dd58a3`): mode parsing
- `w1d2-curriculum` (`2c51c8e`): real W1D2 yaml in realtime mode about "tools and APIs"
- `design-doc-update` (`6b2dd44`): added §17 Realtime Lesson Mode to spec

### Phase 3 — SSE streaming
- `llm-stream` (`6132e91`): server/llm_stream.py async iterator, sentence_splitter.py, ws_messages.py, agent_partial_text + agent_audio (b64) + agent_done WS messages
- `sentence-splitter` (`a02bad4`): SentenceAccumulator with Mr./3.14 guards
- `ws-messages` (`55998f7`): WS message protocol
- `tts-azure-sync` (`4173e2d`): Azure TTS sentence-by-sentence
- `coach-streaming` (`ee006a5`): the wiring
- `coach-streaming-tests` (`5c2361b`): 7 unit + 3 integration + 3 Playwright tests
- `web-client-captions` (`e4133c9`): web side live caption rendering
- `e2e-playwright` (`6374511`): adds streaming Playwright e2e

### Phase 4 — VAD + barge-in
- `deps-and-config` (`cc63b27`): SPEAKAGENT_VAD config flag + /config endpoint
- `vad-segmenter` — EMPTY (worktree unchanged), needs investigation
- `agent-stream-cancel` (`f8c79d2`): cooperative cancel events
- `ws-session-vad-integration` (`f947642`): silero-vad ONNX + Windows torchaudio shim, AudioWorklet wiring
- `web-audio-worklet-and-mic-client` — EMPTY
- `tts-player-stopall-and-session-wiring` (`22ac0a7`): tts-player.stopAll() + session.js wiring
- `playwright-barge-in-e2e` (`666c03e`): Playwright spec for barge-in

## Known bugs surfaced tonight

1. **`autopilot/loop.py::_commit_to_branch` falsely reports success when there's nothing to commit.** Subagents already commit themselves (per their prompt), so autopilot's redundant `git commit` returns rc=1 ("nothing to commit") but my code returns the branch name unconditionally. Result: items that the subagent successfully completed AND items where the subagent did nothing both look like "committed" or "needs_human" based on whether `_verify` happened to pass. Need to gate on `git rev-parse HEAD != base_sha`.

2. **`_verify` runs in isolated worktrees.** Each Phase 3/4 subagent depends on Phase 2/3 work, but its worktree doesn't have those commits — so its tests crash on missing imports. This is why 20/22 verify_failed even when the subagent did good work. Need a verify strategy that can pull in dependent branches before running tests, or accept "subagent-self-asserted-tests-passed" via stdout parsing.

3. **`llm-client` claude.cmd rc=4294967295.** Windows unsigned -1, means subprocess crashed or was killed. No stdout/stderr. Need to capture child stderr separately and try `--debug` flag on retry.

## What you should do this morning

**My recommendation, in order:**

1. **Skim 3 commits** to confirm subagent quality: `coach-realtime` (10619be), `llm-stream` (6132e91), `ws-session-vad-integration` (f9476425). They're well-structured.
2. **Decide merge strategy.** Three options:
   - (a) Cherry-pick / merge **per-phase** in order (Phase 2 first, resolve conflicts, then Phase 3, then Phase 4). Linear history, slow.
   - (b) Have me spawn one **integrator subagent** per phase that takes that phase's 5-7 branches, merges them, resolves conflicts, runs full test suite. Fast but trusts the integrator.
   - (c) Open all 18 branches as PRs on GitHub and review one at a time. Most rigorous, slowest.
3. **Fix the two autopilot bugs** (`_commit_to_branch` false success + `_verify` cross-branch deps) before launching another autopilot run.
4. The 3 EMPTY branches (`vad-segmenter`, `web-audio-worklet-and-mic-client`, `docs-spec-update`) need their items re-added to backlog.

## Disk state

22 worktrees × ~100MB = ~2.2GB. 170GB free. Safe.

## Files to read

- `/tmp/autopilot.log` — 255 lines, full structured-log audit trail
- `autopilot/runs/digest-2026-05-13.md` — summary
- `autopilot/backlog.jsonl` — current backlog (all needs-human)
- Each `autopilot/2026-05-13-<slug>` branch's HEAD commit message
