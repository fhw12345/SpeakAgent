# Plan: Phase 3 — Streaming Agent Speech (speakAgent)

_PRD: autopilot/prds/2026-05-13-phase-3-of-conversational-coac.md_
_Generated: 2026-05-13_

## 1. Problem statement

Convert the agent-speech path from a turn-blocking `LLM-then-TTS-then-send` into a sentence-level pipeline (Claude SSE delta -> sentence accumulator -> Azure TTS -> WS frames) so the user hears the first sentence within ~1s rather than after the entire reply, while preserving Phase 2 byte-identical behavior under `SPEAKAGENT_STREAMING=off`.

## 2. Module-by-module plan

### 2.1 `server/llm_stream.py` (new)

```python
async def stream_claude(
    messages: list[dict],
    model: str | None = None,
    system: str = "You are a helpful English speaking coach.",
    gateway_url: str | None = None,
) -> AsyncIterator[str]: ...
```

- Use `httpx.AsyncClient` (already a dep). Do NOT introduce `anthropic` SDK.
- POST to `gateway_url or os.environ["CLAUDE_API_ENDPOINT"]` with `"stream": true`, headers `Content-Type: application/json`, `anthropic-version: 2023-06-01`, `accept: text/event-stream`.
- Parse SSE via `client.stream("POST", ...).aiter_lines()`. For each `data: {...}` line, parse JSON; yield `delta.text` when `type == "content_block_delta"` and `delta.type == "text_delta"`.
- On non-200 / `httpx.HTTPError` / `json.JSONDecodeError` of full payload: log and raise `RuntimeError("llm_stream_failed:<reason>")`. Malformed individual `data:` lines are skipped (logged, not raised).
- Default model = `os.environ.get("CLAUDE_MODEL", "claude-opus-4.7-1m-internal")`.

**Deviation:** PRD shows `model="claude-3-5-sonnet"`. Use repo default.

### 2.2 `server/sentence_splitter.py` (new)

```python
class SentenceAccumulator:
    def __init__(self, terminators: str = ".!?\n", min_len: int = 4) -> None: ...
    def push(self, delta: str) -> list[str]: ...
    def flush(self) -> list[str]: ...
```

- Internal `_buf: str`. `push` appends, scans left-to-right.
- Cut iff terminator hit AND `len(current.strip()) >= min_len` AND lookahead is end-of-buffer OR whitespace OR another terminator.
- `flush` returns `[buf.strip()]` if non-empty (regardless of min_len), resets buffer.

### 2.3 Splitter rule worked examples

- `"Mr. Smith said hi."` -> 1 sentence: `"Mr. Smith said hi."` (first `.` blocked by min-len).
- `"Pi is 3.14 exactly. "` -> 1 sentence (decimal `.` blocked by digit lookahead).
- `"Hi."` push only -> []; `flush()` -> `["Hi."]`.
- `"Hello world. How are you?"` push -> `["Hello world.", "How are you?"]`.

### 2.4 `server/tts.py` — add helper

**Deviation:** PRD names `tts_azure.py`; existing module is `tts.py`. Add helper to existing module.

```python
async def synthesize_bytes(text: str, voice: str) -> bytes:
    buf = bytearray()
    async for chunk in synthesize_stream(text, voice):
        buf.extend(chunk)
    return bytes(buf)
```

**Deviation:** PRD says "sync wrapper". Async-returning-bytes is correct for an async-native FastAPI codebase.

### 2.5 `server/ws_messages.py` (new)

Pure dict builders (no Pydantic, matches existing inline-dict style):

```python
def agent_partial_text(text: str, index: int) -> dict
def agent_audio_b64(b64: str, index: int) -> dict
def agent_done(full_text: str = "") -> dict
def agent_error(detail: str, index: int | None = None) -> dict
```

Other message types may be added opportunistically but only the streaming-related ones are required.

### 2.6 `server/main.py` — branch on env flag at lines ~62-74

```python
if turn["speaker"] == "agent":
    voice = pick_voice(week=plan.week, turn_index=sess.coach._idx)
    streaming = os.environ.get("SPEAKAGENT_STREAMING", "on").lower() == "on"
    if streaming:
        await stream_agent_turn(ws, sess, turn, voice, plan)
    else:
        # existing Phase 2 path verbatim
        ...
```

**Deviation:** PRD says modify `coach.py`. `coach.py` is a pure state machine; new logic lives in `server/agent_turn.py`.

### 2.7 `server/agent_turn.py` (new)

```python
async def stream_agent_turn(ws, sess, turn, voice, plan) -> None: ...
```

- Send `agent_caption` once up front (so UI's `currentBuffer` initializes).
- Build messages: simple seed asking Claude to deliver `turn["say"]` naturally in 1-3 sentences. (Conversation memory out of scope.)
- Run streaming flow (section 4).
- Wrap in try/except: on top-level exception emit `agent_error(..., index=None)` then `agent_done(full_text)`.

### 2.8 `web/js/app.js` (deviation: PRD path is `web/app.js`)

- Add WS message branches: `agent_partial_text`, `agent_audio` (when JSON, base64-decode and queue), `agent_error`.
- `updateCaption(text, index)` sets `#agent-caption` text.
- Clear `#agent-caption` on next `user_prompt`.

### 2.9 `web/index.html`

- Insert `<div id="agent-caption" aria-live="polite"></div>` inside `#dialogue-view`.

### 2.10 `web/style.css` (deviation: PRD says `styles.css`)

- Add `#agent-caption { font-style: italic; color: #555; min-height: 1.4em; padding: 0.25em 0.5em; }`.

### 2.11 `.env.example`

- Append `SPEAKAGENT_STREAMING=on`.

### 2.12 `docs/superpowers/specs/2026-05-12-speakagent-design.md`

- Append `## Phase 3 — Streaming Agent Speech` section.

## 3. Streaming flow (inside `stream_agent_turn`)

```
full_text = ""
index = 0
acc = SentenceAccumulator()
await ws.send_json(agent_caption(turn["say"], voice, ...))

try:
    async for delta in stream_claude(messages):
        full_text += delta
        for sentence in acc.push(delta):
            await _emit_sentence(ws, sentence, voice, index); index += 1
    for sentence in acc.flush():
        await _emit_sentence(ws, sentence, voice, index); index += 1
except Exception as e:
    await ws.send_json(agent_error(str(e)[:200]))
await ws.send_json(agent_done(full_text))   # exactly once

_emit_sentence:
    await ws.send_json(agent_partial_text(sentence, index))
    try:
        audio = await synthesize_bytes(sentence, voice)
        await ws.send_json(agent_audio_b64(b64encode(audio).decode("ascii"), index))
    except Exception as e:
        await ws.send_json(agent_error(f"tts_failed: {e}", index=index))
```

Invariants: `agent_partial_text[i]` precedes `agent_audio[i]`; `agent_done` exactly once; per-sentence TTS errors don't abort.

## 4. Test plan

### `tests/unit/test_sentence_splitter.py`
- basic period cut; min-length protects abbreviation; decimal lookahead; incremental delta; flush returns partial; newline terminator.

### `tests/unit/test_llm_stream.py`
- Use `httpx.MockTransport` with canned SSE bytes.
- yields deltas in order; skips non-text events; handles `[DONE]`; malformed line skipped; HTTP error raises `RuntimeError`.

### `tests/integration/test_coach_streaming.py`
- FastAPI TestClient WS pattern (see `tests/integration/test_e2e.py`).
- Patch `server.agent_turn.stream_claude` and `server.agent_turn.synthesize_bytes`.
- Cases:
  1. ON mode: 3 partials + 3 audio (JSON) + 1 done; ordering audio[i] follows text[i].
  2. OFF mode: zero partials, audio as binary frames, one done.
  3. TTS error on sentence 2: one `agent_error` with index=1, others continue, single done.
  4. First-audio wall-clock: streaming < 0.5 * OFF baseline (with 200ms/sentence patched latency × 3 sentences).

### `tests/e2e/test_streaming_agent.py` (Python pytest-playwright; deviation from PRD `.spec.ts`)
- intercept WS frames via `page.on("websocket", ...)`; assert ≥2 `agent_partial_text` before first `agent_done`; assert `#agent-caption` text changes ≥2 times.

## 5. Validation commands

```bash
pytest tests/unit/test_sentence_splitter.py tests/unit/test_llm_stream.py -v
pytest tests/integration/test_coach_streaming.py -v
pytest tests/e2e/test_streaming_agent.py -v
pytest -q   # full regression
```

## 6. Risks

- Per-sentence TTS overhead for short replies (mitigated by lazy-stream).
- Gateway disconnect mid-stream → caught, agent_error + agent_done with buffered text.
- Splitter false positives → length+lookahead rule + unit tests.
- MP3 chunks across sentences may glitch at boundaries; mitigated by client queuing each `agent_audio` as its own `Audio` element.
- Local gateway may not honor `stream: true`. Mocked in tests; manual smoke required.

## 7. Acceptance criteria mapping

| AC | Test |
|----|------|
| 1 | `test_coach_streaming::test_streaming_on_emits_partials_and_audio` |
| 2 | same (ordering assertion) |
| 3 | `test_coach_streaming::test_first_audio_under_half_baseline` |
| 4 | `test_coach_streaming::*` (count==1) |
| 5 | `test_coach_streaming::test_streaming_off_byte_identical` |
| 6 | `test_coach_streaming::test_tts_error_per_sentence_continues` |
| 7 | `tests/e2e/test_streaming_agent::test_streaming_partial_captions_arrive` |
| 8 | same |
