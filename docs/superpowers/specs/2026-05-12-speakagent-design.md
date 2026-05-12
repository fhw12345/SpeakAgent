# speakAgent design

## Phase 3 — Sentence-level streaming agent speech

The Phase 2 agent-turn path was turn-blocking: full LLM call, then full Azure
TTS, then forward audio. Phase 3 streams from Claude SSE → sentence splitter →
Azure TTS → WebSocket. The first audible sentence reaches the client well
before the full reply is generated.

### Pipeline

```
Claude SSE (server/llm_stream.stream_claude)
    │  text deltas
    ▼
SentenceAccumulator (server/sentence_splitter)
    │  completed sentences
    ▼
stream_agent_turn (server/coach.py)
    ├─ ws.send_json({type: "agent_partial_text", text, index})
    ├─ tts_bytes(sentence, voice)  →  audio bytes
    └─ ws.send_json({type: "agent_audio", b64, index})
    ───────── (after final sentence) ─────────
    └─ ws.send_json({type: "agent_done", full_text})
```

### Feature flag

`SPEAKAGENT_STREAMING` (default `on`). When `off`, `server/main.py` runs the
Phase 2 path verbatim — no `agent_partial_text` frames are emitted, audio is
sent as raw binary frames as before.

### Public interface

- `server.llm_stream.stream_claude(messages, model, gateway_url=None) -> AsyncIterator[str]`
- `server.sentence_splitter.SentenceAccumulator.push(delta) / .flush()`
- `server.coach.stream_agent_turn(ws, turn, voice) -> str` (returns full text)
- WS message additions: `agent_partial_text`, `agent_audio` (b64), `agent_error`.
- WS message addition: `agent_done` now carries `full_text`.

### Sentence splitter

Splits on `.`, `!`, `?`, or newline when followed by whitespace / EOF /
another terminator. Min length 4 (after strip) to avoid emitting fragments
like `Mr.`. Decimals (`3.14`) survive because `1` is not whitespace.

### Error handling

- SSE parse / network errors inside `stream_claude` are logged and the
  generator ends cleanly. `stream_agent_turn` emits `agent_error` with the
  current sentence index and still flushes any partial buffer + `agent_done`.
- TTS failure on a single sentence emits `agent_error` for that index and
  continues with the next sentence.

### Test surface

| Layer | File |
| --- | --- |
| Unit (splitter) | `tests/unit/test_sentence_splitter.py` |
| Unit (SSE client) | `tests/unit/test_llm_stream.py` |
| Integration (WS flow) | `tests/integration/test_coach_streaming.py` |
| E2E (browser) | `tests/e2e/test_streaming_agent.py` |

E2E filename note: PRD specified `test_streaming_agent.spec.ts`, but the
existing e2e harness in this repo is `pytest-playwright` (python). The python
file under the same directory satisfies the same intent without introducing a
parallel Node toolchain.
