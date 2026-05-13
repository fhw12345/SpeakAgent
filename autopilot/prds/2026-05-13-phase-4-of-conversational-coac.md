# PRD: Phase 4 of conversational coach upgrade. After Phase 3, agent speech streams but user is still push-to-talk. Make user side fully realtime: continuous mic recording, voice activity detection (use silero-vad model, add silero_vad to requirements.txt), VAD decides when user 'started speaking' and when user 'finished a phrase'. When user starts speaking while agent is talking, immediately stop agent TTS playback and send a new WS message interrupt to server which cancels the pending Claude stream. Add WS messages user_speech_start and user_speech_end. On server side wire VAD into the audio buffer accumulator. Frontend uses AudioWorklet (replacing ScriptProcessor) for low-latency streaming. Keep Phase 3 push-to-talk path as fallback (SPEAKAGENT_VAD=on/off env). Playwright e2e covers a session where user interrupts agent mid-sentence and a new agent response begins within 1s.

_Generated: 2026-05-13T01:04:01_

## Goal
Add server+frontend voice activity detection (silero-vad) to make the user side of the conversational coach fully realtime: continuous mic capture, automatic phrase segmentation, and barge-in that cancels in-flight agent TTS+Claude streaming within 1 second.

## Acceptance Criteria
1. With `SPEAKAGENT_VAD=on`, the frontend opens the mic on session start and streams 16 kHz mono PCM frames continuously over the existing `/ws/session` WebSocket using an `AudioWorklet` (no `ScriptProcessorNode`).
2. Server-side `VadSegmenter` (silero-vad) emits `user_speech_start` and `user_speech_end` WS messages to the client; `user_speech_end` triggers transcription of the buffered segment exactly as Phase 3 did on PTT release.
3. When `user_speech_start` fires while the agent is streaming TTS or Claude tokens, the server cancels the active Claude stream task and stops sending `tts_audio_chunk` messages; the client immediately stops playback of queued audio.
4. The client sends an `interrupt` WS message when it locally detects speech onset (redundant safety) and the server is idempotent to it.
5. With `SPEAKAGENT_VAD=off`, behavior is identical to Phase 3 (push-to-talk via `ptt_start`/`ptt_end` messages), and the AudioWorklet path is not loaded.
6. End-to-end barge-in latency (local VAD detection → audio playback stop → new `agent_token` for the new turn) is ≤ 1000 ms in the Playwright test.
7. `silero_vad` is pinned in `requirements.txt`; model loads once at server startup and is reused across sessions.
8. All new unit, integration, and Playwright tests pass via `pytest -q` and `npx playwright test`.

## Files to Create or Modify
- `server/vad.py` — new: `VadSegmenter` class wrapping silero-vad with `process_frame(pcm: bytes) -> list[VadEvent]`.
- `server/ws_session.py` — modify: integrate `VadSegmenter`, emit `user_speech_start`/`user_speech_end`, handle `interrupt`, manage cancellable Claude task.
- `server/agent_stream.py` — modify: expose `cancel()` on the streaming coroutine; ensure TTS chunk sender checks a `cancel_event`.
- `server/config.py` — modify: add `SPEAKAGENT_VAD` (default `"off"`).
- `server/app.py` — modify: load silero-vad model on startup when VAD enabled, attach to app state.
- `web/audio/mic-worklet.js` — new: `AudioWorkletProcessor` named `mic-pcm-processor` posting Int16 frames of 512 samples.
- `web/audio/mic-client.js` — new: loads worklet, downsamples to 16 kHz, posts frames to WS; runs lightweight onset detector (energy threshold) for instant `interrupt` send.
- `web/audio/tts-player.js` — modify: add `stopAll()` that clears the queue and calls `source.stop()`.
- `web/session.js` — modify: branch on `window.SPEAKAGENT_VAD`; wire new messages; call `tts-player.stopAll()` on `user_speech_start`.
- `web/index.html` — modify: inject `SPEAKAGENT_VAD` flag from `/config` endpoint.
- `server/routes_config.py` — modify: include `vad` field in `/config` JSON.
- `requirements.txt` — modify: add `silero-vad==5.1.2`, `onnxruntime>=1.17`.
- `tests/test_vad.py` — new: unit tests for `VadSegmenter`.
- `tests/test_ws_session_vad.py` — new: integration tests for VAD WS flow + interrupt.
- `tests/e2e/barge_in.spec.ts` — new: Playwright e2e for mid-sentence interruption.

## Public Interface
- Python:
  - `class VadSegmenter(sample_rate:int=16000, threshold:float=0.5, min_silence_ms:int=400, min_speech_ms:int=200)`
  - `VadSegmenter.process_frame(pcm_bytes: bytes) -> list[VadEvent]` where `VadEvent = Literal["start","end"]`.
  - `VadSegmenter.reset() -> None`
  - `agent_stream.stream_turn(..., cancel_event: asyncio.Event) -> AsyncIterator[StreamMsg]`
- WS messages (JSON):
  - C→S: `{"type":"audio_frame","pcm_b64":str}` (continuous when VAD on)
  - C→S: `{"type":"interrupt"}`
  - S→C: `{"type":"user_speech_start"}`
  - S→C: `{"type":"user_speech_end","segment_id":str}`
  - S→C existing: `agent_token`, `tts_audio_chunk`, `turn_end` (unchanged)
- REST: `GET /config` adds `{"vad":"on"|"off"}`.

## Test Plan
- Unit (`tests/test_vad.py`):
  - `test_vad_emits_start_on_speech_frames` — feed sine-wave WAV fixture, expect `["start"]`.
  - `test_vad_emits_end_after_silence` — speech + 500 ms silence → `["start","end"]`.
  - `test_vad_ignores_short_blip` — 50 ms speech → no events.
  - `test_reset_clears_state`.
- Integration (`tests/test_ws_session_vad.py`, FastAPI `TestClient` WS):
  - `test_vad_off_uses_ptt` — env off, ensure no `user_speech_start` emitted on audio frames.
  - `test_vad_on_emits_speech_events` — stream fixture audio, assert ordered `user_speech_start`,`user_speech_end`.
  - `test_interrupt_cancels_claude_stream` — start agent turn, send `interrupt`, assert no further `agent_token`/`tts_audio_chunk` after ≤200 ms and `cancel_event` fired.
  - `test_user_speech_start_during_agent_triggers_cancel` — implicit cancel without explicit `interrupt`.
- Playwright (`tests/e2e/barge_in.spec.ts`):
  - `barge-in restarts agent within 1s` — mock backend sends long agent stream; test page injects synthetic mic speech via `MediaStreamTrackGenerator`; asserts `tts-player.stopAll` invoked and a new `agent_token` arrives within 1000 ms; uses `performance.now()` markers exposed on `window.__speakAgentMetrics`.

## Out of Scope
- Replacing faster-whisper with a streaming ASR.
- Server-side echo cancellation of agent TTS leaking into mic.
- Mobile Safari support for AudioWorklet quirks.

## Risks
- **silero-vad ONNX model load latency** on cold start → mitigation: load once at app startup behind feature flag and warm with a zero-frame.
- **False positives from agent TTS bleed-through** triggering spurious interrupts → mitigation: gate VAD `start` events with a 150 ms minimum-speech window and require client-side energy threshold confirmation before sending `interrupt`.
- **AudioWorklet unsupported in older browsers** → mitigation: detect `AudioWorkletNode` and fall back to PTT path with a console warning.
