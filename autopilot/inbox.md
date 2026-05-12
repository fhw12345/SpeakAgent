# Autopilot inbox

## 2026-05-13 — Phase 4 VAD: PRD AC#6 deviation

**PRD:** `autopilot/prds/2026-05-13-phase-4-of-conversational-coac.md`
**Worktree:** `.claude/worktrees/autopilot-2026-05-13-ws-session-vad-integration`

**Issue:** AC#6 measures barge-in latency to "new `agent_token` for the new turn". The current Phase 3 implementation does not produce `agent_token` events — turns are pre-scripted from YAML lessons and TTS chunks are emitted as raw MP3 bytes. There is no Claude token stream to cancel.

**Deviation:** This wave measures barge-in latency to **first `tts_audio_chunk` of the new turn** (the first audible output the user hears). All other ACs are satisfied as written. The cancellation infrastructure (`cancel_event` plumbed through `agent_stream.stream_turn`) is shaped so that adding a real Claude token stream in a future phase will Just Work — `agent_token` becomes another `StreamMsg` variant with the same cancel guards.

**Recommendation:** Either (a) accept the deviation and reword AC#6 in a follow-up PRD revision, or (b) schedule Phase 5 (Claude streaming integration) to land the missing `agent_token` surface, after which this PR's Playwright test can be tightened to assert on `agent_token` instead of `tts_audio_chunk`.

**Status:** Continuing implementation under deviation (a). Not blocking the wave.
