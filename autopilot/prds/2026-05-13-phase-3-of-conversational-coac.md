# PRD: Phase 3 of conversational coach upgrade. After Phase 2, coach.py has a realtime mode but still turn-based blocking on full LLM/TTS round-trip. Make agent speech truly streaming: when generating an agent utterance, stream from Claude SSE (Anthropic streaming protocol via the local gateway), accumulate text by sentence boundary, send each sentence to Azure TTS as soon as it is complete, and forward audio bytes to the WS client immediately. Add new WS message type agent_partial_text for live caption updates. Keep Phase 2 realtime mode working for non-streaming fallback (env flag SPEAKAGENT_STREAMING=on/off). Update web/js to render partial captions live. Playwright e2e covers a streaming session and verifies multiple agent_partial_text events arrive before agent_done.

_Generated: 2026-05-13T01:02:20_

## Goal
Convert `server/coach.py` agent speech path from blocking full-utterance LLM+TTS to true sentence-level streaming over Claude SSE → Azure TTS → WebSocket, with live caption updates via a new `agent_partial_text` message and an env-flag fallback to Phase 2 behavior.

## Acceptance Criteria
1. When `SPEAKAGENT_STREAMING=on` (default), an agent turn streams Claude SSE responses from the local gateway and emits ≥2 `agent_partial_text` WS messages before `agent_done` for any reply containing ≥2 sentences.
2. Each completed sentence (terminated by `.`, `!`, `?`, or newline; min 4 chars) is synthesized via Azure TTS and its audio bytes forwarded as `agent_audio` WS frames before the next sentence's text is emitted.
3. First `agent_audio` frame arrives at the client in ≤50% of the wall-clock time of the equivalent non-streaming path (measured in test with mocked TTS latency 200ms/sentence over 3 sentences).
4. `agent_done` is sent exactly once per agent turn, after the final sentence's audio.
5. With `SPEAKAGENT_STREAMING=off`, behavior is byte-identical to Phase 2 (no `agent_partial_text` messages emitted).
6. SSE parse errors or TTS errors on a single sentence emit an `agent_error` WS message and continue with remaining sentences; the turn still ends with `agent_done`.
7. Web client (`web/app.js`) renders partial captions live in element `#agent-caption`, updating on each `agent_partial_text` and clearing on next user turn.
8. Playwright e2e `tests/e2e/test_streaming_agent.spec.ts` asserts ≥2 `agent_partial_text` events arrive before `agent_done` in a streaming session.

## Files to Create or Modify
- `server/coach.py` — add streaming agent-turn path; branch on `SPEAKAGENT_STREAMING`.
- `server/llm_stream.py` (new) — Claude SSE client `stream_claude(messages, model) -> AsyncIterator[str]`.
- `server/sentence_splitter.py` (new) — incremental sentence accumulator.
- `server/tts_azure.py` — add `synthesize_bytes(text: str) -> bytes` (sync wrapper exposed for streaming) if not present; otherwise reuse.
- `server/ws_messages.py` — add `AgentPartialText` message type and serializer.
- `web/app.js` — handle `agent_partial_text`; update `#agent-caption`.
- `web/index.html` — add `<div id="agent-caption"></div>`.
- `web/styles.css` — style `#agent-caption`.
- `tests/test_sentence_splitter.py` (new) — unit tests.
- `tests/test_llm_stream.py` (new) — unit tests with mocked SSE.
- `tests/test_coach_streaming.py` (new) — integration test of streaming WS flow.
- `tests/e2e/test_streaming_agent.spec.ts` (new) — Playwright e2e.
- `docs/superpowers/specs/2026-05-12-speakagent-design.md` — append Phase 3 section.
- `.env.example` — add `SPEAKAGENT_STREAMING=on`.

## Public Interface
- `async def stream_claude(messages: list[dict], model: str = "claude-3-5-sonnet", gateway_url: str | None = None) -> AsyncIterator[str]` — yields text deltas.
- `class SentenceAccumulator: def push(self, delta: str) -> list[str]; def flush(self) -> list[str]` — returns completed sentences.
- `async def stream_agent_turn(ws, conversation_state) -> None` — new in `coach.py`.
- WS messages (server→client JSON):
  - `{"type":"agent_partial_text","text":<sentence>,"index":<int>}`
  - `{"type":"agent_audio","b64":<str>,"index":<int>}` (existing)
  - `{"type":"agent_done","full_text":<str>}` (existing)
  - `{"type":"agent_error","detail":<str>,"index":<int|null>}` (existing)
- No new REST routes.

## Test Plan
Unit:
- `test_sentence_splitter.py`: splits on `.`, `!`, `?`, newline; preserves trailing partial; ignores `.` in `Mr.`/decimals via min-length 4 rule; flush returns leftover.
- `test_llm_stream.py`: mocks SSE stream with `event: content_block_delta` frames; asserts deltas yielded in order; handles `[DONE]` and malformed lines.

Integration:
- `test_coach_streaming.py` (pytest-asyncio + FastAPI TestClient WS):
  - With `SPEAKAGENT_STREAMING=on` and mocked `stream_claude` yielding "Hi there. How are you? Tell me more.", assert WS receives 3 `agent_partial_text`, ≥3 `agent_audio`, 1 `agent_done`, ordered such that audio[i] follows partial_text[i].
  - With `SPEAKAGENT_STREAMING=off`, assert zero `agent_partial_text` and one `agent_audio` + `agent_done`.
  - TTS error on sentence 2 emits `agent_error` with `index=1` and continues.

Playwright e2e:
- `test_streaming_agent.spec.ts`: launches app, starts session, triggers agent turn via injected user message, captures WS frames via CDP; asserts `agent_partial_text` count ≥2 before first `agent_done`; verifies `#agent-caption` text updates at least twice.

## Out of Scope
- Streaming user STT (already handled in Phase 2).
- Barge-in / interruption of in-flight agent audio.
- Switching TTS provider.

## Risks
- Azure TTS per-sentence overhead may exceed savings for short replies — mitigation: only stream when first sentence completes within 1.5s; otherwise fall through to single-shot.
- SSE gateway disconnect mid-stream — mitigation: catch in `stream_claude`, emit `agent_error`, flush accumulated partial as final sentence.
- Sentence splitter false positives on abbreviations — mitigation: min-length 4 chars and unit tests covering `Mr.`, `3.14`.
