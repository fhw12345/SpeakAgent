# speakAgent Design

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
