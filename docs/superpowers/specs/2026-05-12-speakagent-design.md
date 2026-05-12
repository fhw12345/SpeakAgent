# speakAgent Design

## Phase 3 — Streaming Agent Speech

Phase 3 converts the agent-utterance path from blocking
`LLM-then-TTS-then-send` to a sentence-level pipeline so the learner
hears the first sentence within ~1s instead of after the entire reply.

### Pipeline

```
  Claude SSE delta  ->  SentenceAccumulator  ->  Azure TTS (per sentence)
        │                      │                          │
        ▼                      ▼                          ▼
  full_text+= text     yield sentence           audio bytes
                                                          │
                                                          ▼
                              WS  agent_partial_text  +  agent_audio (b64)
                                                          │
                                                          ▼
                                              agent_done (once at end)
```

### Env-flag behavior

`SPEAKAGENT_STREAMING` (default `on`) selects the agent-turn handler
inside `server/main.py::ws_session`:

- `on`  -> `server.agent_turn.stream_agent_turn` (Phase 3 pipeline above).
- `off` -> verbatim Phase 2 path: single `agent_caption`, MP3 chunks
  pushed as binary WS frames via `synthesize_stream`, then `agent_done`.

`SPEAKAGENT_FAKE_STREAM=1` swaps `stream_claude` for a deterministic
in-process stub so e2e tests run without the local Claude gateway.

### WS message shapes (server -> client)

| type | payload | mode |
|------|---------|------|
| `agent_caption` | `{text, voice, gloss, translation}` | both |
| `agent_partial_text` | `{text, index}` | streaming only |
| `agent_audio` | binary MP3 frame | OFF mode |
| `agent_audio` | `{b64, index}` JSON | streaming mode |
| `agent_error` | `{detail, index?}` | streaming on per-sentence TTS failure |
| `agent_done` | `{full_text}` (streaming) or `{}` (OFF) | both, exactly once |

Per-sentence ordering invariant: `agent_partial_text[i]` is sent before
`agent_audio[i]`. A single sentence's TTS failure emits `agent_error`
with that index and the loop continues to the next sentence; the turn
still ends with exactly one `agent_done`.

### Sentence splitter rule

`server/sentence_splitter.SentenceAccumulator` cuts iff:

1. Current char is a terminator in `.!?\n`.
2. `len(buffered_sentence.strip()) >= min_len` (default 4) — protects
   `Mr.`, `Dr.`, etc.
3. Lookahead char exists and is whitespace OR another terminator —
   protects decimals like `3.14` (next char is digit) and defers cut
   when the terminator is the very last buffered char (no lookahead
   yet).

`flush()` emits the trailing partial regardless of `min_len` once the
SSE stream ends.

### Web client

`web/index.html` adds `<div id="agent-caption" aria-live="polite">`
inside `#dialogue-view`. `web/js/app.js` handles three new message
types:

- `agent_partial_text` -> `setCaption(text)`.
- `agent_audio` (JSON variant with `b64`) -> base64-decode to
  `Uint8Array`, push into `currentBuffer`; `agent_done` queues the
  buffer for sequential playback (same path as OFF binary frames).
- `agent_error` -> log to dev panel; playback continues with whichever
  sentence audio did succeed.

`#agent-caption` is cleared on every `agent_caption` (new turn) and
every `user_prompt`.
