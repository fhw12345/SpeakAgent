# PRD: Phase 2 of conversational coach upgrade. Currently coach.py is turn-based with hard-coded YAML lesson turns. Make lesson YAML support two modes: scripted (current behavior, default) and realtime (new). When mode=realtime, the YAML only declares topic, target_phrases, vocabulary, and coach_persona; turns are not pre-written. Add server/coach_realtime.py that uses the LLM to generate the next agent utterance based on conversation history + lesson context after each user response. Still turn-based (no streaming yet, that is Phase 3). Add a new lesson curriculum/week1/day2.yml in realtime mode about 'tools and APIs' as a working example. Write Playwright e2e that drives a 3-turn realtime session end-to-end with mocked LLM/STT/TTS. Do not break existing scripted lessons (W1D1 must still work).

_Generated: 2026-05-13T00:58:06_

## Goal
Add a `realtime` lesson mode to speakAgent where the agent's turns are LLM-generated from lesson context + conversation history, while preserving the existing `scripted` mode and all W1D1 behavior.

## Acceptance Criteria
1. Lesson YAML loader accepts a top-level `mode: scripted|realtime` field; absent or invalid → defaults to `scripted` with a WARN log.
2. Scripted lessons (existing `curriculum/week1/day1.yml`) load and run with byte-identical agent turn text as before (verified by snapshot test).
3. Realtime lessons require fields `topic`, `target_phrases` (list[str]), `vocabulary` (list[str]), `coach_persona` (str); missing any → `ValueError("realtime lesson missing field: <name>")` at load time.
4. `curriculum/week1/day2.yml` exists with `mode: realtime`, `topic: "tools and APIs"`, ≥5 `target_phrases`, ≥8 `vocabulary` items, and a non-empty `coach_persona`.
5. POST `/api/lesson/start` with `lesson_id="w1d2"` returns `{session_id, mode:"realtime", first_agent_utterance}` where `first_agent_utterance` is LLM-generated (not from YAML).
6. POST `/api/lesson/turn` with `{session_id, user_text}` for a realtime session calls the LLM with conversation history + lesson context and returns `{agent_utterance, turn_index, done}`; `done=true` after 6 user turns or when LLM emits sentinel `[[END_LESSON]]`.
7. W1D1 scripted endpoints/responses unchanged (regression test passes).
8. Playwright e2e `tests/e2e/realtime_lesson.spec.ts` drives 3 user turns of W1D2 with mocked STT/TTS/LLM and asserts 3 distinct agent utterances render in the transcript pane.
9. All new + existing pytest tests pass; `pytest -q` exit 0.

## Files to Create or Modify
- `server/lesson_loader.py` (modify): add `mode` parsing, realtime field validation, return `LessonSpec` dataclass.
- `server/coach.py` (modify): dispatch on `lesson.mode` to scripted handler (existing) or `coach_realtime.handle_turn`.
- `server/coach_realtime.py` (create): LLM-driven turn generator.
- `server/llm_client.py` (modify if exists, else create): expose `generate(messages: list[dict], max_tokens:int)->str`.
- `curriculum/week1/day2.yml` (create): realtime example lesson.
- `tests/test_lesson_loader.py` (modify/create): mode parsing + validation tests.
- `tests/test_coach_realtime.py` (create): unit tests with mocked LLM.
- `tests/test_coach_scripted_regression.py` (create): W1D1 snapshot.
- `tests/e2e/realtime_lesson.spec.ts` (create): Playwright e2e.
- `tests/e2e/mocks/llm_mock.py` (create): deterministic mock LLM server fixture.
- `docs/superpowers/specs/2026-05-12-speakagent-design.md` (modify): add §"Realtime Lesson Mode".

## Public Interface
Python:
- `LessonSpec(mode: Literal["scripted","realtime"], lesson_id:str, topic:str|None, target_phrases:list[str], vocabulary:list[str], coach_persona:str|None, turns:list[ScriptedTurn]|None)`
- `lesson_loader.load(lesson_id:str) -> LessonSpec`
- `coach_realtime.start_session(lesson:LessonSpec) -> tuple[str, str]` returns `(session_id, first_agent_utterance)`.
- `coach_realtime.handle_turn(session_id:str, user_text:str) -> dict` returns `{agent_utterance:str, turn_index:int, done:bool}`.
- `coach_realtime.MAX_USER_TURNS = 6`
- `coach_realtime.END_SENTINEL = "[[END_LESSON]]"`

REST (existing routes, extended):
- `POST /api/lesson/start` body `{lesson_id:str}` → `{session_id:str, mode:str, first_agent_utterance:str}`
- `POST /api/lesson/turn` body `{session_id:str, user_text:str}` → `{agent_utterance:str, turn_index:int, done:bool}`

LLM prompt (system) constructed as: persona + topic + target_phrases + vocabulary + instruction "Reply with one short coach turn (≤2 sentences). Emit `[[END_LESSON]]` when objectives covered."

## Test Plan
Unit (pytest):
- `test_lesson_loader.py::test_default_mode_scripted`
- `test_lesson_loader.py::test_realtime_requires_topic` (and one per required field)
- `test_lesson_loader.py::test_invalid_mode_falls_back_with_warning`
- `test_lesson_loader.py::test_w1d2_loads`
- `test_coach_realtime.py::test_start_session_calls_llm_and_returns_utterance`
- `test_coach_realtime.py::test_handle_turn_appends_history`
- `test_coach_realtime.py::test_done_after_max_user_turns`
- `test_coach_realtime.py::test_done_on_end_sentinel`
- `test_coach_realtime.py::test_unknown_session_raises_keyerror`
- `test_coach_scripted_regression.py::test_w1d1_turn_sequence_unchanged`

Integration (FastAPI TestClient):
- `test_api_realtime.py::test_start_w1d2_returns_realtime_mode`
- `test_api_realtime.py::test_three_turn_flow_with_mock_llm`

E2E (Playwright):
- `tests/e2e/realtime_lesson.spec.ts`: launch app with `LLM_MOCK=1 STT_MOCK=1 TTS_MOCK=1`, select W1D2, perform 3 mocked user utterances, assert transcript has 1 initial + 3 agent turns and lesson is not `done` before turn 6.

## Out of Scope
- Streaming/token-by-token LLM responses (Phase 3).
- Per-turn pronunciation scoring changes.
- Curriculum entries beyond `w1d2`.

## Risks
- **LLM nondeterminism breaks tests** → mitigate by injecting `LLM_MOCK` returning canned sequence in all automated tests.
- **Session state memory leak** → store sessions in `dict` with TTL eviction (30 min) in `coach_realtime._SESSIONS`.
- **Prompt drift causes off-topic replies** → constrain via system prompt template constants in `coach_realtime.SYSTEM_TEMPLATE` and unit-test prompt assembly.
