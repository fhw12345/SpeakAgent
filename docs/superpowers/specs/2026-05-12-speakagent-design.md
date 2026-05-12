# speakAgent design notes

## Phase 3 — sentence-level streaming agent speech (2026-05-13)

The agent-turn path now streams from Claude SSE through Azure TTS to the
WebSocket at sentence granularity, gated by `SPEAKAGENT_STREAMING` (default `on`).

Pipeline:

1. `server/llm_stream.stream_claude` opens an SSE POST against the local
   gateway (`CLAUDE_API_ENDPOINT`) with `stream: true` and yields each
   `content_block_delta` text fragment.
2. `server/sentence_splitter.SentenceAccumulator` buffers deltas and
   emits a sentence whenever it sees `.`, `!`, `?`, or newline AND the
   stripped candidate is ≥ 4 characters (rejects `Mr.` / `3.14`).
3. `server/coach.stream_agent_turn` drives the loop. Per sentence it
   sends `agent_partial_text` then awaits `synthesize_bytes` and sends
   the resulting MP3 as `agent_audio` (base64). TTS errors on a single
   sentence emit `agent_error` and the loop continues.
4. `server/main.ws_session` calls `stream_agent_turn` when streaming is
   enabled, otherwise falls back to the Phase 2 byte-stream path.
5. `web/js/app.js` renders `agent_partial_text` into `#agent-caption` live
   and decodes base64 `agent_audio` frames into the existing play queue.

Fallback behavior: with `SPEAKAGENT_STREAMING=off`, `agent_caption` +
binary MP3 chunks + bare `agent_done` (Phase 2) is sent unchanged.

Out of scope: streaming user STT, barge-in, alternative TTS providers.
