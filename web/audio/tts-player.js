// web/audio/tts-player.js
// Streaming TTS playback with stopAll() for barge-in (Phase 4 PRD #1,#3,#5,#6).
// Plays an ordered queue of encoded audio chunks (e.g. MP3 frames from Azure
// TTS) by decoding via Web Audio. stopAll() drops everything pending and stops
// the currently playing AudioBufferSourceNode so a new turn can start cleanly.
(function (root) {
  function createPlayer(opts) {
    opts = opts || {};
    const ctx = opts.audioContext || new (root.AudioContext || root.webkitAudioContext)();

    const queue = [];
    let currentSource = null;
    let draining = false;
    let generation = 0;

    async function drain() {
      if (draining) return;
      draining = true;
      const myGen = generation;
      try {
        while (queue.length && myGen === generation) {
          const buf = queue.shift();
          let decoded;
          try {
            decoded = await ctx.decodeAudioData(buf.slice(0));
          } catch (_) {
            continue;
          }
          if (myGen !== generation) return;
          await playOne(decoded, myGen);
        }
      } finally {
        if (myGen === generation) {
          draining = false;
          currentSource = null;
        }
      }
    }

    function playOne(decoded, myGen) {
      return new Promise((resolve) => {
        const src = ctx.createBufferSource();
        src.buffer = decoded;
        src.connect(ctx.destination);
        let done = false;
        src.onended = () => {
          if (done) return;
          done = true;
          if (currentSource === src) currentSource = null;
          resolve();
        };
        currentSource = src;
        try {
          src.start();
        } catch (_) {
          done = true;
          resolve();
          return;
        }
        // If stopAll fired while we were async-decoding, this source belongs
        // to an old generation. Stop it immediately so audio doesn't leak.
        if (myGen !== generation) {
          try { src.stop(); } catch (_) {}
          if (!done) { done = true; resolve(); }
        }
      });
    }

    return {
      enqueue(arrayBuffer) {
        if (!arrayBuffer) return;
        queue.push(arrayBuffer);
        drain();
      },
      stopAll() {
        generation += 1;
        queue.length = 0;
        const src = currentSource;
        currentSource = null;
        draining = false;
        if (src) {
          try { src.stop(); } catch (_) {}
        }
      },
      queueLength() { return queue.length; },
      isPlaying() { return currentSource !== null; },
      _ctx: ctx,
    };
  }

  const api = createPlayer;
  api.create = createPlayer;
  root.TtsPlayer = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
