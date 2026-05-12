"""Browser unit-style tests for web/audio/tts-player.js and web/session.js.

These are pure-JS module tests run in a real Chromium page so we exercise
the same APIs (AudioContext stubs, dynamic import, performance.now) the
modules will use in production. No backend server is required.

Owned by slice: tts-player-stopall-and-session-wiring (Phase 4 PRD).
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TTS_PLAYER_JS = REPO / "web" / "audio" / "tts-player.js"
SESSION_JS = REPO / "web" / "session.js"


def _blank_page(page):
    page.set_content("<!doctype html><html><head></head><body></body></html>")


def _add_script(page, path: Path):
    assert path.exists(), f"missing {path}"
    page.add_script_tag(content=path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# tts-player.js
# ---------------------------------------------------------------------------

def test_tts_player_exposes_factory(page):
    _blank_page(page)
    _add_script(page, TTS_PLAYER_JS)
    typeof = page.evaluate("typeof window.TtsPlayer")
    assert typeof in ("function", "object"), f"TtsPlayer not exposed (got {typeof})"


def test_tts_player_stopall_clears_queue_and_stops_current(page):
    """stopAll() must call source.stop() on the active node, drop the queue,
    and reset state so a subsequent enqueue plays normally."""
    _blank_page(page)
    _add_script(page, TTS_PLAYER_JS)

    result = page.evaluate(
        """async () => {
            // Build a fake AudioContext that records source.stop() calls and
            // lets us trigger 'onended' synchronously.
            const stops = [];
            const created = [];
            class FakeSource {
                constructor() {
                    this.buffer = null;
                    this.onended = null;
                    this._started = false;
                    this._stopped = false;
                    created.push(this);
                }
                connect() {}
                start() { this._started = true; }
                stop() { this._stopped = true; stops.push(this); }
            }
            const fakeCtx = {
                destination: {},
                sampleRate: 48000,
                state: 'running',
                createBufferSource: () => new FakeSource(),
                decodeAudioData: (buf) => Promise.resolve({ duration: 0.1, buf }),
                resume: () => Promise.resolve(),
                close: () => Promise.resolve(),
            };

            const factory = window.TtsPlayer;
            const player = (typeof factory === 'function')
                ? factory({ audioContext: fakeCtx })
                : factory.create({ audioContext: fakeCtx });

            // Enqueue two chunks so one is "playing" and one is queued.
            player.enqueue(new Uint8Array([1,2,3]).buffer);
            player.enqueue(new Uint8Array([4,5,6]).buffer);

            // Yield so async decodeAudioData resolves and the first source
            // is actually started — mirrors real barge-in where the agent
            // has been speaking before the user interrupts.
            await new Promise(r => setTimeout(r, 0));
            await new Promise(r => setTimeout(r, 0));

            const queuedBefore = player.queueLength();
            player.stopAll();
            const queuedAfter = player.queueLength();

            // After stopAll a new enqueue must work (state reset).
            player.enqueue(new Uint8Array([7,8,9]).buffer);
            await new Promise(r => setTimeout(r, 0));
            const queuedAfterReuse = player.queueLength();

            return {
                stopsCalled: stops.length,
                createdCount: created.length,
                queuedBefore,
                queuedAfter,
                queuedAfterReuse: queuedAfterReuse + (player.isPlaying() ? 1 : 0),
            };
        }"""
    )

    assert result["queuedAfter"] == 0, "stopAll did not clear pending queue"
    assert result["stopsCalled"] >= 1, "stopAll did not call source.stop() on current node"
    assert result["queuedAfterReuse"] >= 1, "player did not accept new chunks after stopAll"


def test_tts_player_stopall_safe_when_idle(page):
    """Calling stopAll() with nothing playing must not throw."""
    _blank_page(page)
    _add_script(page, TTS_PLAYER_JS)
    err = page.evaluate(
        """() => {
            const fakeCtx = {
                destination: {},
                createBufferSource: () => ({
                    connect(){}, start(){}, stop(){}, onended:null, buffer:null,
                }),
                decodeAudioData: (b) => Promise.resolve({ duration: 0, b }),
                resume: () => Promise.resolve(),
                close: () => Promise.resolve(),
            };
            const factory = window.TtsPlayer;
            const player = (typeof factory === 'function')
                ? factory({ audioContext: fakeCtx })
                : factory.create({ audioContext: fakeCtx });
            try { player.stopAll(); player.stopAll(); return null; }
            catch (e) { return String(e); }
        }"""
    )
    assert err is None, f"stopAll threw when idle: {err}"


# ---------------------------------------------------------------------------
# session.js
# ---------------------------------------------------------------------------

def test_session_exposes_metrics_object(page):
    _blank_page(page)
    _add_script(page, SESSION_JS)
    has = page.evaluate("typeof window.__speakAgentMetrics")
    assert has == "object", f"__speakAgentMetrics not initialised (got {has})"
    keys = page.evaluate("Object.keys(window.__speakAgentMetrics || {})")
    for k in ("lastInterruptSentAt", "lastStopAllAt", "lastNewAgentTokenAt"):
        assert k in keys, f"missing metric key {k}: have {keys}"


def test_session_user_speech_start_calls_stopall_and_records_metric(page):
    """When session sees a user_speech_start frame it must invoke
    ttsPlayer.stopAll() and stamp lastStopAllAt."""
    _blank_page(page)
    _add_script(page, SESSION_JS)

    out = page.evaluate(
        """() => {
            const calls = [];
            const fakePlayer = {
                stopAll() { calls.push('stopAll'); },
                enqueue() {},
                queueLength: () => 0,
            };
            const wired = window.SpeakAgentSession.wire({
                ttsPlayer: fakePlayer,
                send: () => {},
            });
            const before = window.__speakAgentMetrics.lastStopAllAt;
            wired.handleMessage({ type: 'user_speech_start' });
            const after = window.__speakAgentMetrics.lastStopAllAt;
            wired.handleMessage({ type: 'agent_token', text: 'hi' });
            const afterToken = window.__speakAgentMetrics.lastNewAgentTokenAt;
            return { calls, beforeNull: before === null, afterNum: typeof after, afterTokenNum: typeof afterToken };
        }"""
    )
    assert "stopAll" in out["calls"], "user_speech_start did not invoke ttsPlayer.stopAll"
    assert out["beforeNull"], "lastStopAllAt was not null before invocation"
    assert out["afterNum"] == "number", "lastStopAllAt was not stamped"
    assert out["afterTokenNum"] == "number", "lastNewAgentTokenAt was not stamped on agent_token"


def test_session_vad_off_does_not_load_mic_client(page):
    """With SPEAKAGENT_VAD='off', session.start() must not attempt to import
    mic-client.js (we assert by checking no fetch for that path)."""
    _blank_page(page)
    _add_script(page, SESSION_JS)
    out = page.evaluate(
        """async () => {
            window.SPEAKAGENT_VAD = 'off';
            const wired = window.SpeakAgentSession.wire({
                ttsPlayer: { stopAll(){}, enqueue(){}, queueLength: () => 0 },
                send: () => {},
            });
            const r = await wired.start({ ws: { readyState: 1 } });
            return { micLoaded: !!r.micLoaded, mode: r.mode };
        }"""
    )
    assert out["micLoaded"] is False, "mic-client should not load when VAD=off"
    assert out["mode"] == "ptt", f"expected ptt mode, got {out['mode']!r}"


def test_session_vad_on_without_audioworklet_warns_and_falls_back(page):
    """With SPEAKAGENT_VAD='on' but AudioWorkletNode missing, session must
    console.warn and fall back to PTT (mode='ptt')."""
    _blank_page(page)
    _add_script(page, SESSION_JS)
    out = page.evaluate(
        """async () => {
            window.SPEAKAGENT_VAD = 'on';
            // Simulate missing AudioWorkletNode.
            const saved = window.AudioWorkletNode;
            try { delete window.AudioWorkletNode; } catch(_) { window.AudioWorkletNode = undefined; }
            const warns = [];
            const origWarn = console.warn;
            console.warn = (...a) => warns.push(a.join(' '));
            try {
                const wired = window.SpeakAgentSession.wire({
                    ttsPlayer: { stopAll(){}, enqueue(){}, queueLength: () => 0 },
                    send: () => {},
                });
                const r = await wired.start({ ws: { readyState: 1 } });
                return { mode: r.mode, micLoaded: !!r.micLoaded, warned: warns.length > 0 };
            } finally {
                console.warn = origWarn;
                if (saved !== undefined) window.AudioWorkletNode = saved;
            }
        }"""
    )
    assert out["mode"] == "ptt", f"fallback mode should be ptt, got {out['mode']!r}"
    assert out["micLoaded"] is False
    assert out["warned"] is True, "expected console.warn for missing AudioWorkletNode"
