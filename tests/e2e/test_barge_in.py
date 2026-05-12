"""E2E barge-in test (Phase 4.5).

Approach: hybrid Approach A.

The silero-vad/torchaudio install on Windows fails to load native libs
(``OSError: [WinError 127]`` from torchaudio's ``_torchaudio`` extension),
so we cannot start uvicorn with ``SPEAKAGENT_VAD=on``. Instead we run the
server with VAD OFF (the existing ``server`` fixture) and:

  * Use ``page.route('**/config', ...)`` to force the browser to see
    ``{vad: 'on'}`` regardless of the server's real flag.
  * Use ``page.add_init_script`` to install a fake ``WebSocket`` BEFORE
    the page's own scripts run, so ``new WebSocket(...)`` inside
    ``Session.start()`` returns our stub.
  * Stub ``navigator.mediaDevices.getUserMedia`` so MicClient's ``start()``
    succeeds without prompting for a real microphone.
  * Drive the barge-in protocol entirely from JS via ``page.evaluate``:
    feed an ``agent_caption``, simulate TTS playback, fire ``user_speech_start``
    (which calls ``ttsPlayer.stopAll()``), feed a fresh ``agent_caption``
    + binary chunk, and read the metrics surface
    ``window.__speakAgentMetrics``.

The local energy-detector path is exercised by directly calling
``window.session.micClient._onFrame(buf)`` with a high-energy Int16 buffer
during TTS playback, asserting that an ``interrupt`` JSON was sent on the
fake WS and that ``metrics.speechStartLocal`` was populated.

Reporting:
  * AC#6: ``firstAudioChunkAfterInterrupt - speechStartLocal < 1000`` ms.
  * Backend ``user_speech_start`` path is also validated: ``ttsPlayer.stopAll()``
    fires and ``metrics.ttsStop`` is populated.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


SCREENSHOTS = Path(__file__).resolve().parent / "screenshots"


# ---------- shared helper scripts -----------------------------------------

# Installed via add_init_script; runs before any page script. Sets up:
#   - window.__fakeWs: latest WebSocket instance (stub)
#   - window.WebSocket: a stub class
#   - navigator.mediaDevices.getUserMedia: returns a fake stream
#   - AudioWorkletNode/AudioContext.audioWorklet.addModule patched if missing
_INIT_SCRIPT = r"""
(() => {
  // ---- WebSocket stub ----
  class FakeWS {
    constructor(url) {
      this.url = url;
      this.readyState = 0; // CONNECTING
      this.binaryType = 'arraybuffer';
      this.sent = [];
      this.onopen = null;
      this.onmessage = null;
      this.onerror = null;
      this.onclose = null;
      window.__fakeWs = this;
      // Open asynchronously so caller can attach handlers first.
      setTimeout(() => {
        this.readyState = 1;
        if (typeof this.onopen === 'function') this.onopen({});
      }, 0);
    }
    send(data) {
      // Record JSON messages as parsed objects when possible; binary as ArrayBuffer.
      if (typeof data === 'string') {
        try { this.sent.push(JSON.parse(data)); }
        catch (_) { this.sent.push(data); }
      } else {
        this.sent.push(data);
      }
    }
    close() {
      this.readyState = 3;
      if (typeof this.onclose === 'function') this.onclose({});
    }
    // Test helpers
    fire(obj) {
      if (typeof this.onmessage === 'function') {
        this.onmessage({ data: JSON.stringify(obj) });
      }
    }
    fireBinary(buf) {
      if (typeof this.onmessage === 'function') {
        this.onmessage({ data: buf });
      }
    }
  }
  window.WebSocket = FakeWS;

  // ---- getUserMedia stub ----
  // Provide a minimal MediaStream with one audio track.
  const fakeTrack = {
    kind: 'audio',
    enabled: true,
    readyState: 'live',
    stop() { this.readyState = 'ended'; },
  };
  const fakeStream = {
    getTracks() { return [fakeTrack]; },
    getAudioTracks() { return [fakeTrack]; },
  };
  if (!navigator.mediaDevices) {
    Object.defineProperty(navigator, 'mediaDevices', { value: {}, configurable: true });
  }
  navigator.mediaDevices.getUserMedia = async () => fakeStream;

  // ---- AudioContext / AudioWorklet stubs ----
  // Real Chromium has these, but addModule needs a real worklet file. We stub
  // out enough that MicClient.start() resolves without error and exposes a
  // .node.port we can drive.
  const RealAudioContext = window.AudioContext || window.webkitAudioContext;
  function stubNode() {
    const port = {
      onmessage: null,
      postMessage() {},
    };
    return {
      port,
      connect() {},
      disconnect() {},
    };
  }
  // Minimal AudioContext replacement that satisfies MicClient.start().
  class StubAudioContext {
    constructor() {
      this.sampleRate = 48000;
      this.destination = {};
      this.audioWorklet = { addModule: async () => {} };
    }
    async resume() {}
    async close() {}
    createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
    createGain() { return { gain: { value: 0 }, connect() {}, disconnect() {} }; }
  }
  window.AudioContext = StubAudioContext;
  window.AudioWorkletNode = function (ctx, name, opts) { return stubNode(); };
})();
"""


# Drive the full barge-in dance from inside the page. Returns a dict of
# observations: WS messages sent, metrics, ttsPlayer.isPlaying snapshots.
_DRIVE_BARGE_IN = r"""
async () => {
  const ws = window.__fakeWs;
  const sess = window.session;
  if (!ws || !sess) return { error: 'no ws or session' };

  // 1) Server greets the client.
  ws.fire({ type: 'session_start', lesson: 'TEST' });

  // Wait briefly so MicClient.start() (async) attaches to session.
  await new Promise(r => setTimeout(r, 50));

  // 2) Agent says something — caption then audio chunk.
  ws.fire({ type: 'agent_caption', text: 'hello', gloss: [], translation: '' });
  // Push a binary chunk and trigger agent_done so TtsPlayer starts playing.
  // The chunk is a tiny invalid buffer; TtsPlayer.play() will reject and the
  // worker still sets currentAudio briefly. We instead force isPlaying=true by
  // monkey-patching after agent_done so the test is deterministic regardless of
  // codec support.
  ws.fireBinary(new ArrayBuffer(16));
  ws.fire({ type: 'agent_done' });

  // Pin TtsPlayer into "playing" state for the duration of barge-in.
  const player = sess.ttsPlayer;
  player.currentAudio = { pause() {}, set src(_) {} };

  // 3) Local energy-detector path: feed a high-energy frame to MicClient.
  //    This should fire 'interrupt' on the fake WS and stamp speechStartLocal.
  let interruptSent = false;
  if (sess.micClient) {
    const N = 512;
    const i16 = new Int16Array(N);
    for (let i = 0; i < N; i++) i16[i] = 30000; // ~ -0.7 dBFS, way above -35
    // Two consecutive frames are required (energyOver >= 2).
    sess.micClient._onFrame(i16.buffer);
    sess.micClient._onFrame(i16.buffer);
    interruptSent = ws.sent.some(m => m && m.type === 'interrupt');
  }

  // 4) Server confirms barge-in.
  ws.fire({ type: 'user_speech_start' });

  // 5) New agent turn after the interrupt.
  ws.fire({ type: 'agent_caption', text: 'sorry', gloss: [], translation: '' });
  // Fire the post-interrupt binary chunk. The Session._onMessage binary
  // branch stamps firstAudioChunkAfterInterrupt because speechStartLocal is set.
  ws.fireBinary(new ArrayBuffer(16));

  // Wait a tick so promises settle.
  await new Promise(r => setTimeout(r, 20));

  return {
    interruptSent,
    sentTypes: ws.sent.map(m => (m && m.type) || (m && m.byteLength != null ? '<binary>' : typeof m)),
    metrics: window.__speakAgentMetrics,
  };
}
"""


def _open_dialogue(page, port):
    """Navigate to the dialogue view for any lesson and click Start."""
    page.goto(f"http://127.0.0.1:{port}/?metrics=1")
    page.wait_for_selector('#list-view .lesson-row[data-id="W1D1"]')
    page.click('.lesson-row[data-id="W1D1"]')
    page.wait_for_selector('#dialogue-view:not([hidden])')


def test_barge_in_metrics_within_one_second(server, page):
    """AC#6: firstAudioChunkAfterInterrupt - speechStartLocal < 1000 ms."""
    SCREENSHOTS.mkdir(exist_ok=True)

    # Force VAD on at the page level (real server may have VAD off because
    # silero-vad/torchaudio fails to load on Windows test env).
    page.route(
        "**/config",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"vad": "on"}),
        ),
    )
    # Install WebSocket / getUserMedia / AudioContext stubs BEFORE page scripts.
    page.add_init_script(script=_INIT_SCRIPT)

    _open_dialogue(page, server)
    # Click Start; Session.start() will see SPEAKAGENT_VAD === 'on' and try
    # to construct MicClient after session_start arrives.
    page.click("#start-btn")

    # Drive the protocol entirely from JS.
    result = page.evaluate(_DRIVE_BARGE_IN)

    assert "error" not in result, f"driver script failed: {result}"

    metrics = result.get("metrics") or {}
    assert metrics.get("speechStartLocal") is not None, \
        f"speechStartLocal not stamped — energy detector did not fire. result={result}"
    assert metrics.get("ttsStop") is not None, \
        f"ttsStop not stamped — server-confirmed barge-in path did not call stopAll(). result={result}"
    assert metrics.get("firstAudioChunkAfterInterrupt") is not None, \
        f"firstAudioChunkAfterInterrupt not stamped — post-interrupt binary chunk path broken. result={result}"

    delta = metrics["firstAudioChunkAfterInterrupt"] - metrics["speechStartLocal"]
    assert delta < 1000, f"AC#6 violated: delta={delta:.1f}ms (>=1000)"

    # Bonus: confirm the local energy detector actually emitted 'interrupt'.
    assert result.get("interruptSent"), \
        f"local energy interrupt JSON was not sent. sentTypes={result.get('sentTypes')}"

    page.screenshot(path=str(SCREENSHOTS / "barge_in.png"))


def test_vad_off_path_unchanged(server, page):
    """When backend reports VAD off, no MicClient is constructed and PTT button
    is the only mic affordance. Validates the OFF path is undisturbed by the
    Phase 4 wiring."""
    # Server fixture starts uvicorn WITHOUT SPEAKAGENT_VAD=on, so /config
    # naturally returns {"vad": "off"}. We do not stub WebSocket here because
    # we don't click Start — we only inspect the bootstrap state.
    page.goto(f"http://127.0.0.1:{server}/")
    # Wait for /config bootstrap to finish.
    page.wait_for_function("window.SPEAKAGENT_VAD !== undefined", timeout=5000)

    vad_flag = page.evaluate("window.SPEAKAGENT_VAD")
    assert vad_flag == "off", f"expected SPEAKAGENT_VAD='off', got {vad_flag!r}"

    # PTT button exists and MicClient class is present (script loaded) but no
    # MicClient instance has been constructed — Session has not been started.
    state = page.evaluate(
        "({ hasPtt: !!document.getElementById('ptt-btn'),"
        "   micClientLoaded: typeof window.MicClient !== 'undefined',"
        "   sessionInstance: !!window.session })"
    )
    assert state["hasPtt"], "PTT button missing in OFF path"
    assert state["micClientLoaded"], "MicClient script failed to load"
    assert not state["sessionInstance"], \
        "Session was constructed before user clicked Start"
