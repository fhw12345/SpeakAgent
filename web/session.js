// web/session.js
// Session-level wiring for Phase 4 conversational coach: handles VAD-on/off
// mode selection, mic-client bootstrapping (when AudioWorkletNode supported),
// and the new server WS messages (`user_speech_start` / `user_speech_end`).
// Also exposes `window.__speakAgentMetrics` so the Playwright barge-in spec
// can measure latency.
//
// Owned by slice: tts-player-stopall-and-session-wiring.
// The mic-client module (web/audio/mic-client.js) is owned by a peer slice
// and is loaded via dynamic `import()` only when needed, so this file is safe
// to load even before that file lands.
(function (root) {
  // Single shared metrics object — created on first script load so the e2e
  // test can inspect it before any session starts.
  if (!root.__speakAgentMetrics) {
    root.__speakAgentMetrics = {
      lastInterruptSentAt: null,
      lastStopAllAt: null,
      lastNewAgentTokenAt: null,
      lastUserSpeechStartAt: null,
      lastUserSpeechEndAt: null,
    };
  }

  function now() {
    return (root.performance && root.performance.now) ? root.performance.now() : Date.now();
  }

  function vadEnabled() {
    return root.SPEAKAGENT_VAD === "on";
  }

  function audioWorkletSupported() {
    return typeof root.AudioWorkletNode !== "undefined";
  }

  function wire(deps) {
    deps = deps || {};
    const ttsPlayer = deps.ttsPlayer;
    const send = deps.send || function () {};
    let lastSegmentId = null;
    let micHandle = null;

    function sendInterrupt() {
      root.__speakAgentMetrics.lastInterruptSentAt = now();
      try { send({ type: "interrupt" }); } catch (_) {}
    }

    function handleMessage(msg) {
      if (!msg || typeof msg !== "object") return;
      switch (msg.type) {
        case "user_speech_start":
          root.__speakAgentMetrics.lastUserSpeechStartAt = now();
          if (ttsPlayer && typeof ttsPlayer.stopAll === "function") {
            ttsPlayer.stopAll();
            root.__speakAgentMetrics.lastStopAllAt = now();
          }
          break;
        case "user_speech_end":
          root.__speakAgentMetrics.lastUserSpeechEndAt = now();
          lastSegmentId = msg.segment_id || null;
          break;
        case "agent_token":
          root.__speakAgentMetrics.lastNewAgentTokenAt = now();
          break;
        default:
          break;
      }
    }

    async function start(opts) {
      opts = opts || {};
      const ws = opts.ws || null;

      if (!vadEnabled()) {
        return { mode: "ptt", micLoaded: false };
      }
      if (!audioWorkletSupported()) {
        try { console.warn("speakAgent: AudioWorkletNode unsupported; falling back to PTT"); } catch (_) {}
        return { mode: "ptt", micLoaded: false };
      }

      try {
        const mod = await import("./audio/mic-client.js");
        const factory = mod && (mod.default || mod.createMicClient || mod.MicClient);
        if (typeof factory === "function") {
          micHandle = await factory({ ws: ws, onLocalSpeechOnset: sendInterrupt });
        }
        return { mode: "vad", micLoaded: true };
      } catch (err) {
        try { console.warn("speakAgent: failed to load mic-client; falling back to PTT", err); } catch (_) {}
        return { mode: "ptt", micLoaded: false, error: String(err) };
      }
    }

    function stop() {
      if (micHandle && typeof micHandle.stop === "function") {
        try { micHandle.stop(); } catch (_) {}
      }
      micHandle = null;
    }

    return {
      handleMessage,
      start,
      stop,
      sendInterrupt,
      get lastSegmentId() { return lastSegmentId; },
    };
  }

  root.SpeakAgentSession = { wire, vadEnabled, audioWorkletSupported };
})(typeof window !== "undefined" ? window : globalThis);
