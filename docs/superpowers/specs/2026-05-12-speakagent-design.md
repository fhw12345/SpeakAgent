# speakAgent design (Phase 3 section)

> Phase 1 and 2 are not in the repo as a written spec. This file was
> created in Phase 3 to satisfy the PRD's append target. Earlier phases
> live in `autopilot/prds/`.

## Phase 3 — Streaming agent speech (2026-05-13)

PRD: [`autopilot/prds/2026-05-13-phase-3-of-conversational-coac.md`](../../../autopilot/prds/2026-05-13-phase-3-of-conversational-coac.md)

### What changed

When `SPEAKAGENT_STREAMING=on` (default), the agent turn is no longer a
single blocking LLM-then-TTS round-trip. Instead:

1. `server/llm_stream.stream_claude` opens an SSE connection to the local
   Agent Maestro gateway and yields `text_delta` chunks as they arrive.
2. `server/sentence_splitter.SentenceAccumulator` buffers chunks and
   returns each completed sentence (terminated by `.`, `!`, `?`, `\n`,
   min 4 chars after strip).
3. `server/coach.stream_agent_turn` consumes the splitter output. For
   each sentence it sends a JSON `agent_partial_text` frame, then
   synthesizes one MP3 blob via `server/tts.synthesize_bytes` and pushes
   it as a single binary WS frame.
4. After the SSE stream ends, any leftover partial is flushed and a
   final `agent_done` JSON frame is sent with `full_text`.

When `SPEAKAGENT_STREAMING=off`, `server/main.ws_session` runs the
Phase 2 path verbatim — no `agent_partial_text` is emitted.

### WebSocket message catalog (Phase 3 additions)

| Direction      | Type                  | Shape                                                              |
| -------------- | --------------------- | ------------------------------------------------------------------ |
| server→client  | `agent_partial_text`  | `{type, text: <sentence>, index: <int>}`                           |
| server→client  | `agent_error`         | `{type, detail: <str>, index: <int|null>}`                         |
| server→client  | `agent_done`          | now also carries `full_text: <str>` in the streaming branch        |

### Failure handling

- SSE gateway error mid-stream: caught in `stream_agent_turn`, emits
  `agent_error` with `index=null`, then flushes any partial sentence and
  ends with `agent_done`.
- TTS error on a single sentence: emits `agent_error` with that
  sentence's `index` and continues; the turn still ends with
  `agent_done`.

### Frontend

- `web/index.html` adds `<div id="agent-caption" aria-live="polite">`.
- `web/js/app.js` handles `agent_partial_text` by appending the sentence
  to that div, flushes the previous sentence's audio buffer to the play
  queue, and clears the caption on the next user turn.
- `web/style.css` styles `#agent-caption` and hides it when empty.
