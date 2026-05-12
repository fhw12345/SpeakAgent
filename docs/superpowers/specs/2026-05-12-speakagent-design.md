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
