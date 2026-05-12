# Phase 4 VAD Implementation Plan

_Plan for: `autopilot/prds/2026-05-13-phase-4-of-conversational-coac.md`_
_Generated: 2026-05-13_
_Target branch: `autopilot/2026-05-13-ws-session-vad-integration`_

## 0. Pre-flight reality check

The PRD's "Files to Modify" list assumes a Phase 3 surface that does not exist in the worktree. Verified absent: `server/ws_session.py`, `server/agent_stream.py`, `server/app.py`, `server/routes_config.py`, `web/session.js`, `web/audio/`, `web/audio/tts-player.js`, `web/index.html` `/config`-injection. What exists today:

- `server/main.py` — FastAPI app, single `/ws/session` handler walking lesson turns sequentially: `agent_caption` (JSON) → raw MP3 bytes from `synthesize_stream` → `agent_done` (JSON) → collect user audio bytes until `user_audio_end` JSON.
- `server/session.py` — `SpeechSession` with `audio_buffer: bytearray`.
- `server/stt.py`, `server/tts.py` — Whisper + edge-tts; `synthesize_stream(text, voice)` is an async generator yielding MP3 chunks.
- `web/js/app.js` — PTT via ScriptProcessor at 16 kHz; raw Int16 over WS; MP3 blobs in an `Audio` element queue.
- `web/index.html` — exists but does not currently fetch `/config`.
- No `/config` REST route.
- No streaming Claude integration; turns are pre-scripted from YAML lessons.

**Impact on AC #6 (barge-in latency to "new agent_token within 1s"):** the system does not produce `agent_token` events. We satisfy the spirit of this AC by measuring barge-in to **first `tts_audio_chunk` of the new turn**. See `autopilot/inbox.md` escalation note.

The plan introduces the new module names from the PRD (`vad.py`, `agent_stream.py`, `ws_session.py`, `routes_config.py`, `web/session.js`, `web/audio/*`) and refactors today's inline `main.py`/`app.js` code into them. The `SPEAKAGENT_VAD=off` path is byte-identical to the current Phase 3 PTT behavior.

---

## 1. Build sequence (phased, each phase ends at a green test gate)

### Phase 4.0 — Foundations & feature flag (no behavior change)

| # | File | Change | Test |
|---|---|---|---|
| 0.1 | `requirements.txt` | Add `silero-vad==5.1.2` and `onnxruntime>=1.17`. | `pip install` succeeds. |
| 0.2 | `server/config.py` | Add `vad: str = "off"` to `Config`; read `SPEAKAGENT_VAD`, normalize. | `tests/unit/test_config.py::test_vad_*`. |
| 0.3 | `server/routes_config.py` (new) | `GET /config` → `{"vad": cfg.vad}`. Wired in `server/main.py`. | `tests/integration/test_config_route.py`. |
| 0.4 | `web/index.html` | Inline bootstrap `<script>` `fetch('/config')` then sets `window.SPEAKAGENT_VAD` BEFORE loading `web/js/app.js`. | Manual + Playwright. |

**Gate:** `pytest -q tests/unit/test_config.py tests/integration/test_config_route.py` green; existing `tests/integration/test_ws.py` still passes unchanged.

### Phase 4.1 — `VadSegmenter` standalone

| # | File | Change | Test |
|---|---|---|---|
| 1.1 | `server/vad.py` (new) | `VadSegmenter`. Lazy-load silero-vad ONNX. State: `in_speech`, `silence_ms`, `speech_ms`. `process_frame(bytes)` accepts 512 samples int16 LE @ 16 kHz; returns `list[Literal["start","end"]]`. `reset()` clears state. | `tests/unit/test_vad.py` (4 tests from PRD). |
| 1.2 | `server/vad.py` | `load_model_once()` singleton. | `test_singleton_load`. |

**Gate:** `pytest -q tests/unit/test_vad.py` green.

### Phase 4.2 — Cancellable agent stream

| # | File | Change | Test |
|---|---|---|---|
| 2.1 | `server/agent_stream.py` (new) | `async def stream_turn(text, voice, cancel_event) -> AsyncIterator[StreamMsg]`. Wraps `tts.synthesize_stream`. Yields `{"type":"tts_audio_chunk","data":bytes}`; emits `turn_end` on natural completion. Checks `cancel_event` after every await. | `tests/unit/test_agent_stream.py`: completes-no-cancel, stops-after-cancel, cancel-before-start. |
| 2.2 | `server/agent_stream.py` | `async def run_to_ws(ws, text, voice, cancel_event)` — forwards each msg as bytes (audio) or JSON (turn_end). | Integration in 4.3. |

**Gate:** `pytest -q tests/unit/test_agent_stream.py` green.

### Phase 4.3 — `ws_session.py`: VAD-aware WS handler

Top-level `async def handle(ws): if cfg.vad=="on": handle_vad else: handle_legacy`.

| # | File | Change | Test |
|---|---|---|---|
| 3.1 | `server/ws_session.py` (new) | Move legacy turn loop verbatim from `main.py` into `handle_legacy`. | `tests/integration/test_ws.py` unchanged + green. |
| 3.2 | `server/ws_session.py` | `handle_vad`: per-session `VadSegmenter`, per-turn `cancel_event`. Two tasks: `_recv_loop` (parses `audio_frame`/`interrupt`), `_turn_loop` (drives lessons via `agent_stream.run_to_ws`). VAD `start` → emit `user_speech_start` + set cancel. VAD `end` → emit `user_speech_end` + transcribe + score. `interrupt` JSON → idempotent cancel. | `tests/integration/test_ws_session_vad.py`. |
| 3.3 | `server/main.py` | Replace inlined `ws_session` with `await ws_session.handle(ws)`. Add startup hook: `if cfg.vad=="on": vad.load_model_once()`. | All integration tests green. |

**Gate:** Full `pytest -q` green under both env states.

### Phase 4.4 — Frontend AudioWorklet path

| # | File | Change | Test |
|---|---|---|---|
| 4.1 | `web/audio/mic-worklet.js` (new) | `MicPcmProcessor` registered as `mic-pcm-processor`. Downsample 48k→16k by 3:1 with simple averaging prefilter. Post Int16 buffers of 512 samples. | Playwright. |
| 4.2 | `web/audio/mic-client.js` (new) | Loads worklet, `getUserMedia`, posts base64 `audio_frame` over WS. Local energy-based onset detector → `interrupt` once per agent turn while TTS is playing. | Playwright. |
| 4.3 | `web/audio/tts-player.js` (new) | `TtsPlayer.enqueue/stopAll/isPlaying`. Refactor of existing playQueue in `app.js`. | Playwright. |
| 4.4 | `web/session.js` (new) | Branches on `window.SPEAKAGENT_VAD`. OFF: existing PTT path verbatim. ON: `MicClient` + handle `user_speech_start`/`end`. | Playwright. |
| 4.5 | `web/index.html` | Load tts-player + session.js (after `/config` bootstrap). | Manual + Playwright. |
| 4.6 | `web/js/app.js` | Trim to view/button wiring; delegate to `Session`. | Existing browser smoke still green. |

**Gate:** Manual Chrome test both VAD on/off; Playwright passes.

### Phase 4.5 — Playwright e2e

| # | File | Change |
|---|---|---|
| 5.1 | `tests/e2e/barge_in.spec.ts` (new) | `MediaStreamTrackGenerator` injects synthetic mic. Asserts `firstAudioChunkAfterInterrupt - speechStartLocal < 1000`. |
| 5.2 | `web/audio/mic-client.js` | `window.__speakAgentMetrics` exposed under `?metrics=1`. |
| 5.3 | `tests/e2e/conftest.py` | Fixture booting uvicorn with `SPEAKAGENT_VAD=on`. |

**Gate:** `npx playwright test tests/e2e/barge_in.spec.ts` green.

---

## 2. Public-interface freezes

### Python

```python
# server/vad.py
class VadSegmenter:
    def __init__(self, sample_rate: int = 16000, threshold: float = 0.5,
                 min_silence_ms: int = 400, min_speech_ms: int = 200) -> None: ...
    def process_frame(self, pcm_bytes: bytes) -> list[str]: ...  # "start"|"end"
    def reset(self) -> None: ...

def load_model_once(): ...  # singleton ONNX model
```

```python
# server/agent_stream.py
async def stream_turn(text: str, voice: str, cancel_event: asyncio.Event) -> AsyncIterator[dict]: ...
async def run_to_ws(ws, text: str, voice: str, cancel_event: asyncio.Event) -> None: ...
```

```python
# server/ws_session.py
async def handle(ws) -> None: ...
```

### WebSocket JSON (added)

C→S:
- `{"type":"audio_frame","pcm_b64":"<base64 int16 LE @16k, 512 samples>"}`
- `{"type":"interrupt"}`

S→C:
- `{"type":"user_speech_start"}`
- `{"type":"user_speech_end","segment_id":"<uuid hex[:12]>"}`
- `{"type":"turn_end"}`

(unchanged: `session_start`, `agent_caption`, `agent_done`, `user_prompt`, `user_transcript`, `score`, `session_end`; raw bytes for TTS chunks)

### REST

`GET /config` → `{"vad": "on"|"off"}`.

---

## 3. Cancellation design

- One `asyncio.Event` per active agent turn.
- VAD `start` or `interrupt` → `cancel_event.set()` (no task.cancel — cooperative).
- `_turn_loop` does `await asyncio.wait_for(agent_task, timeout=0.5)`; on timeout, `agent_task.cancel()`.

Inside `stream_turn`:
```python
if cancel_event.is_set(): return
async for chunk in synthesize_stream(text, voice):
    if cancel_event.is_set(): return
    yield {"type": "tts_audio_chunk", "data": chunk}
    await asyncio.sleep(0)
    if cancel_event.is_set(): return
yield {"type": "turn_end"}
```

`cancel_event.set()` is idempotent. `interrupt` does NOT emit a duplicate `user_speech_start`.

---

## 4. Frontend wiring

Init order (strict):
1. `index.html` bootstrap: `await fetch('/config')` → `window.SPEAKAGENT_VAD`.
2. Load `tts-player.js`.
3. Load `session.js`.
4. On Start: open WS → if VAD: create AudioContext (native rate, NOT forced 16k) → addModule worklet → resume → getUserMedia → connect graph.
5. Server `session_start` → ready.

Downsample: native rate (typ 48k) → 16k via 3-tap averaging then 3:1 decimation. Frame size: 512 samples / 16k = 32 ms.

---

## 5. Feature-flag gating

- Server: `cfg.vad` controls startup model load AND `ws_session.handle()` branch. The OFF branch is a verbatim copy of today's `main.py` body.
- Frontend: `window.SPEAKAGENT_VAD` controls `session.js` branching. OFF never imports worklet modules. Capability check: even when ON, fall back to PTT if `AudioWorkletNode` undefined.

---

## 6. Test plan execution order

1. Phase 4.0 unit + integration (config + /config route).
2. Phase 4.1 unit (vad).
3. Phase 4.2 unit (agent_stream cancellation).
4. Phase 4.3 integration (ws_session VAD flow + interrupt).
5. Phase 4.5 Playwright (barge-in latency).

Synthetic mic for Playwright: `MediaStreamTrackGenerator` of audio kind, monkey-patch `getUserMedia` before Session.start, write 1 s sine after first audio chunk arrives.

---

## 7. Risks / unknowns (with resolutions)

| # | Issue | Resolution |
|---|---|---|
| R1 | **PRD "Phase 3" surface absent** — no Claude streaming, no `agent_token`. | This PR introduces the new modules and uses **first `tts_audio_chunk`** as the latency probe in place of `agent_token`. Escalation logged in `autopilot/inbox.md`. |
| R2 | silero-vad input contract: float32 [-1,1], length 512 @ 16 kHz, returns probability. | Roll our own state machine for `min_silence_ms`/`min_speech_ms` (more testable than `VADIterator`). |
| R3 | `silero-vad==5.1.2` PyPI? | Package name is `silero-vad`, importable as `silero_vad`. Pin to 5.1.2; if not available, nearest 5.1.x. |
| R4 | Outbound queue not needed — current code awaits `ws.send_*` inline; cancel guard inside `stream_turn` is sufficient. |
| R5 | `interrupt` while no active turn → no-op. |
| R6 | AudioWorklet 128-sample quantum vs 512-sample frame → accumulate then post. |
| R7 | Browser sample rate drift → read `audioCtx.sampleRate` and pass into worklet via `processorOptions`. |
| R8 | TTS bleed-through false interrupts → enable browser AEC, plus PRD-mandated 150 ms gate + client energy threshold. |
| R9 | One `VadSegmenter` per session; `reset()` between turns; ONNX model is singleton. |
| R10 | `TestClient` WS doesn't simulate concurrent send/recv well → use `httpx.AsyncClient` + `websockets` for `test_ws_session_vad.py`. |

---

## 8. Acceptance-criteria mapping

| AC | Code/test |
|----|-----------|
| 1  | `web/audio/mic-worklet.js` + `mic-client.js` + `session.js`; verified via Playwright. |
| 2  | `server/vad.py` + `ws_session.py::handle_vad`; tests: `test_vad_*`, `test_vad_on_emits_speech_events`. |
| 3  | Cancellation §3 + `tts-player.stopAll()`; tests: `test_user_speech_start_during_agent_triggers_cancel`, Playwright. |
| 4  | `mic-client.js` energy detector + idempotent server handler. |
| 5  | Byte-identical `handle_legacy`; `tests/integration/test_ws.py` unchanged + green. |
| 6  | Playwright using `firstAudioChunkAfterInterrupt` (note R1). |
| 7  | `requirements.txt` + `vad.load_model_once()` in startup; `test_singleton_load`. |
| 8  | All phases gated on relevant suites. |
