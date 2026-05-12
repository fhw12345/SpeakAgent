# speakAgent design — Realtime Lesson Mode (Phase 2)

_Created 2026-05-13 by autopilot wave `2026-05-13-w1d2-curriculum`._

This document describes the realtime lesson mode added in Phase 2. It is a focused
design note rather than a full architecture rewrite; the broader design spec the
PRD references did not yet exist in the repo.

## Two lesson modes

Lessons are YAML files under `curriculum/weekN/dayN.yml`. Each lesson now declares
a top-level `mode` field:

| mode       | source of agent turns                                         | example      |
|------------|---------------------------------------------------------------|--------------|
| `scripted` | pre-written `turns:` array (existing Phase 1 behavior)        | W1D1         |
| `realtime` | LLM-generated at runtime from lesson context + history        | W1D2         |

If `mode` is absent or unknown, the loader logs a WARN and falls back to `scripted`,
preserving backward compatibility with Phase 1 lessons.

## Realtime YAML schema

```yaml
id: w1d2
title: ...
week: 1
mode: realtime

topic: "tools and APIs"            # required
coach_persona: "..."               # required
target_phrases:                    # required, list[str]
  - "..."
vocabulary:                        # required, list[str]
  - tool
```

Missing any required field raises `ValueError("realtime lesson missing field: <name>")`
at load time (`server.lesson.load_lesson`).

## Server modules

- `server/lesson.py` — extended `LessonPlan` dataclass with `mode`, `topic`,
  `target_phrases`, `vocabulary`, `coach_persona`. Mode-aware loader.
- `server/coach_realtime.py` — `start_session(lesson) -> (session_id, first_utterance)`
  and `handle_turn(session_id, user_text) -> {agent_utterance, turn_index, done}`.
  In-process session store with 30-min TTL eviction. Constants:
  `MAX_USER_TURNS = 6`, `END_SENTINEL = "[[END_LESSON]]"`. The system prompt is
  assembled from `SYSTEM_TEMPLATE` (persona + topic + target phrases + vocabulary
  + reply contract).
- `server/routes/realtime.py` — REST endpoints:
  - `POST /api/lesson/start` body `{lesson_id}` →
    `{session_id, mode, first_agent_utterance}`. For scripted lessons returns
    `mode="scripted"` and the first agent `say:` for preview; the actual run
    still uses the existing `/ws/session` WebSocket path.
  - `POST /api/lesson/turn` body `{session_id, user_text}` →
    `{agent_utterance, turn_index, done}`.

## LLM mocking

Setting env `LLM_MOCK=1` makes `coach_realtime` short-circuit `call_with_fallback`
and return a deterministic canned coach sequence (six turns ending with
`[[END_LESSON]]`). Used by the e2e harness so browser tests are reproducible
without depending on a live model.

## Frontend

`web/js/app.js` calls `POST /api/lesson/start` when the user opens a lesson. If
the response has `mode === "realtime"`, the realtime controls (text input + send
button) are revealed and the dialogue pane is driven via `POST /api/lesson/turn`
on each user reply. Phase 2 realtime is text-only; audio (STT/TTS) for realtime
mode is deferred to Phase 3 along with token-by-token streaming.

## Out of scope (Phase 3)

- Streaming/token-by-token LLM responses.
- STT/TTS in realtime mode.
- Per-turn pronunciation scoring of realtime user replies.
- Curriculum entries beyond W1D2.
