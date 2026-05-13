# speakAgent — Design Spec

> Generated 2026-05-12. Living document.

## Overview
speakAgent is a turn-based English speaking coach that takes the learner
through scripted lessons (Week 1–8) using browser STT + TTS and a coach
state machine on the server.

## Core Modules
- `server/lesson.py` — legacy `LessonPlan` + `load_lesson(path)` for scripted YAML.
- `server/lesson_loader.py` (Phase 2) — `LessonSpec` + `load(lesson_id)` with mode parsing and validation.
- `server/coach.py` — turn-based scripted state machine.
- `server/coach_realtime.py` (Phase 2) — LLM-driven realtime coach.
- `server/llm.py` — Claude/GPT backends with retry + fallback.
- `server/llm_client.py` (Phase 2) — `generate(messages, max_tokens)` wrapper, honors `LLM_MOCK=1`.
- `server/main.py` — FastAPI app: `/api/today`, `/api/lessons`, `/api/lesson/start`, `/api/lesson/turn`, `/ws/session`.

## Realtime Lesson Mode (Phase 2)

### Why
Scripted lessons require a human author for every line. To scale past
W1D1 quickly while still keeping the pedagogical scaffolding (target
phrases, vocabulary), we add a `realtime` mode where the agent's turns
are LLM-generated from lesson context + conversation history.

### Lesson YAML schema additions
A top-level `mode` field selects the lesson kind:

```yaml
mode: scripted    # default if absent or invalid (falls back with WARN log)
# OR
mode: realtime
```

Realtime lessons require:
- `topic: str` — subject of the conversation
- `target_phrases: list[str]` — sentences the learner should practice
- `vocabulary: list[str]` — in-scope words
- `coach_persona: str` — short description fed into the LLM system prompt

Missing any required field raises `ValueError("realtime lesson missing field: <name>")` at load time.

### Public Python interface
```python
LessonSpec(mode, lesson_id, topic, target_phrases, vocabulary, coach_persona, turns)
lesson_loader.load(lesson_id) -> LessonSpec

coach_realtime.start_session(spec) -> (session_id, first_agent_utterance)
coach_realtime.handle_turn(session_id, user_text) -> {agent_utterance, turn_index, done}
coach_realtime.MAX_USER_TURNS = 6
coach_realtime.END_SENTINEL = "[[END_LESSON]]"
```

Sessions live in-process in `coach_realtime._SESSIONS` with a 30-minute TTL.

### REST endpoints
- `POST /api/lesson/start  {lesson_id} -> {session_id, mode, first_agent_utterance}`
- `POST /api/lesson/turn   {session_id, user_text} -> {agent_utterance, turn_index, done}`

`done=true` after `MAX_USER_TURNS` user turns or when the LLM emits `[[END_LESSON]]`.

### LLM prompt
```
SYSTEM: You are <persona>. You are coaching a Chinese learner of English on <topic>.
        Target phrases the learner should use: <phrases>.
        Vocabulary in scope: <vocab>.
        Reply with one short coach turn (≤2 sentences). Emit `[[END_LESSON]]`
        when objectives covered.
USER:    Greet the learner and pose your first short question. (kickoff, then dropped from history)
ASSISTANT: <first utterance>
USER:    <learner reply 1>
ASSISTANT: <coach turn 2>
...
```

### Determinism in tests
`LLM_MOCK=1` makes `llm_client.generate` return a canned 6-utterance
sequence (last item ends with the end sentinel). Used by all e2e and
integration tests so behavior is reproducible.

### Backwards compatibility
`server/coach.py` and `server/lesson.py` are unchanged in behavior —
only `coach.dispatch_turn` is added. The `/ws/session` flow continues
to drive scripted W1D1 byte-identically (snapshotted in
`tests/unit/test_coach_scripted_regression.py`).

## Out of scope
- Token streaming (Phase 3).
- Per-turn pronunciation scoring changes for realtime mode.
- Curriculum entries beyond W1D2.

---

## Phase 3 — Streaming Agent Speech

Replaces the Phase 2 blocking agent-turn with a true sentence-level
streaming pipeline:

```
Claude SSE  ─►  SentenceAccumulator  ─►  Azure TTS (per sentence)  ─►  WS frames
```

### Components

- `server/llm_stream.py::stream_claude(messages, model, gateway_url) -> AsyncIterator[str]`
  — Anthropic-compatible SSE client over the local gateway
  (`CLAUDE_API_ENDPOINT`). Yields `text_delta` strings; tolerates `[DONE]`
  and malformed lines.
- `server/sentence_splitter.py::SentenceAccumulator` — incremental splitter.
  Terminators: `.`, `!`, `?`, `\n`. Min 4 chars per sentence to avoid
  splitting on `Mr.` / `3.14`.
- `server/tts.py::synthesize_bytes(text, voice) -> bytes` — sentence-level
  sync wrapper around the existing Azure / edge-tts streaming backend.
- `server/coach.py::stream_agent_turn(ws, messages, voice)` — orchestrator.
  For each completed sentence: emits `agent_partial_text` then
  `agent_audio` (base64). On TTS failure for one sentence: emits
  `agent_error` and continues. Always emits exactly one `agent_done` at the
  end.
- `server/ws_messages.py` — typed serializers for the new and existing
  server→client message shapes.

### WebSocket protocol (server → client)

| type                  | payload                                       |
| --------------------- | --------------------------------------------- |
| `agent_partial_text`  | `{ text: str, index: int }` (new in Phase 3)  |
| `agent_audio`         | `{ b64: str, index: int }` (new in Phase 3)   |
| `agent_done`          | `{ full_text: str }`                          |
| `agent_error`         | `{ detail: str, index: int|null }`            |

### Env flag

`SPEAKAGENT_STREAMING=on` (default) selects the streaming path.
`SPEAKAGENT_STREAMING=off` reverts byte-identically to Phase 2 behavior
(no `agent_partial_text`, no `agent_audio` JSON frames; raw audio bytes
streamed instead).

### Web client

`web/index.html` adds `<div id="agent-caption"></div>`. `web/js/app.js`
handles `agent_partial_text` (appends to caption), `agent_audio` (decodes
base64 and queues for playback), and clears the caption on the next user
turn.

### Tests

- `tests/test_sentence_splitter.py` — terminators, min-length, flush.
- `tests/test_llm_stream.py` — SSE parsing with `httpx.MockTransport`.
- `tests/test_coach_streaming.py` — fake-WS integration: ordering,
  per-sentence error, latency budget (first audio ≤ 50% of blocking
  equivalent at 200ms/sentence × 3), and the `=off` fallback path.
- `tests/e2e/test_streaming_agent.spec.ts` — Playwright: ≥2
  `agent_partial_text` before first `agent_done`; `#agent-caption`
  updated.
