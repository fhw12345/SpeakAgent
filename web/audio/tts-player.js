// web/audio/tts-player.js — serial MP3 chunk playback queue.
// Extracted from app.js playWorker; adds stopAll() for barge-in.
(function () {
  class TtsPlayer {
    constructor() {
      this.queue = [];
      this.workerRunning = false;
      this.currentAudio = null;
      this.currentUrl = null;
      this.metrics = null;
    }

    enqueueChunks(chunks) {
      if (!chunks || !chunks.length) return;
      this.queue.push(chunks);
      this._worker();
    }

    stopAll() {
      this.queue.length = 0;
      if (this.currentAudio) {
        try { this.currentAudio.pause(); } catch (_) {}
        try { this.currentAudio.src = ""; } catch (_) {}
        this.currentAudio = null;
      }
      if (this.currentUrl) {
        try { URL.revokeObjectURL(this.currentUrl); } catch (_) {}
        this.currentUrl = null;
      }
      if (this.metrics) this.metrics.ttsStop = performance.now();
    }

    isPlaying() {
      return !!this.currentAudio;
    }

    async _worker() {
      if (this.workerRunning) return;
      this.workerRunning = true;
      try {
        while (this.queue.length) {
          const chunks = this.queue.shift();
          if (!chunks || !chunks.length) continue;
          const blob = new Blob(chunks, { type: "audio/mpeg" });
          const url = URL.createObjectURL(blob);
          const a = new Audio(url);
          this.currentAudio = a;
          this.currentUrl = url;
          await new Promise((resolve) => {
            a.onended = resolve;
            a.onerror = resolve;
            a.play().catch((e) => {
              try { console.log("audio play err " + e); } catch (_) {}
              resolve();
            });
          });
          // If stopAll() ran during playback, currentAudio is already null.
          if (this.currentAudio === a) {
            this.currentAudio = null;
          }
          if (this.currentUrl === url) {
            this.currentUrl = null;
          }
          try { URL.revokeObjectURL(url); } catch (_) {}
        }
      } finally {
        this.workerRunning = false;
      }
    }
  }

  window.TtsPlayer = TtsPlayer;
})();
