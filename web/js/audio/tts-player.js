// web/js/audio/tts-player.js — small queued MP3 chunk player with stopAll()
// for barge-in. Mirrors the playWorker behavior in app.js but as a reusable
// module that exposes an explicit stop hook.
(function (global) {
  class TtsPlayer {
    constructor() {
      this._queue = [];
      this._current = null;
      this._running = false;
    }

    pushChunks(chunks) {
      if (!chunks || !chunks.length) return;
      this._queue.push(chunks);
      if (!this._running) this._run();
    }

    async _run() {
      this._running = true;
      try {
        while (this._queue.length) {
          const chunks = this._queue.shift();
          if (!chunks.length) continue;
          const blob = new Blob(chunks, { type: "audio/mpeg" });
          const url = URL.createObjectURL(blob);
          const a = new Audio(url);
          this._current = a;
          await new Promise((resolve) => {
            a.onended = resolve;
            a.onerror = resolve;
            a.play().catch(() => resolve());
          });
          this._current = null;
          URL.revokeObjectURL(url);
        }
      } finally {
        this._running = false;
      }
    }

    stopAll() {
      this._queue.length = 0;
      const a = this._current;
      this._current = null;
      if (a) {
        try { a.pause(); a.currentTime = 0; } catch (_) {}
      }
    }
  }

  global.TtsPlayer = TtsPlayer;
})(window);
