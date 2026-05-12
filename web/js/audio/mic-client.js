// web/js/audio/mic-client.js — main-thread wrapper around the mic-pcm-processor
// AudioWorklet. Streams 16 kHz int16 mono PCM frames to a sink (typically the
// WebSocket) and runs a tiny RMS-energy onset detector for instant local
// barge-in confirmation.
//
// Usage:
//   const mic = new MicClient({ ws, onLocalSpeechStart: () => {...} });
//   await mic.start();
//   ...
//   await mic.stop();
(function (global) {
  const TARGET_SR = 16000;

  function downsampleTo16k(int16Frame, srcSampleRate) {
    if (srcSampleRate === TARGET_SR) return int16Frame;
    const ratio = srcSampleRate / TARGET_SR;
    const outLen = Math.floor(int16Frame.length / ratio);
    const out = new Int16Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const srcIdx = Math.floor(i * ratio);
      out[i] = int16Frame[srcIdx];
    }
    return out;
  }

  function rms(int16Frame) {
    let sumSq = 0;
    for (let i = 0; i < int16Frame.length; i++) {
      const v = int16Frame[i] / 32768;
      sumSq += v * v;
    }
    return Math.sqrt(sumSq / int16Frame.length);
  }

  class MicClient {
    constructor({ ws, onLocalSpeechStart, energyThreshold = 0.02, workletUrl = "/static/js/audio/mic-worklet.js" }) {
      this.ws = ws;
      this.onLocalSpeechStart = onLocalSpeechStart || (() => {});
      this.energyThreshold = energyThreshold;
      this.workletUrl = workletUrl;
      this._ctx = null;
      this._stream = null;
      this._node = null;
      this._localSpeaking = false;
      this._aboveCount = 0;
    }

    static isSupported() {
      return typeof window !== "undefined"
        && "AudioWorkletNode" in window
        && navigator.mediaDevices && navigator.mediaDevices.getUserMedia;
    }

    async start() {
      if (this._starting || this._ctx) return;
      this._starting = true;
      try {
        this._stream = await navigator.mediaDevices.getUserMedia({
          audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
        });
        this._ctx = new AudioContext();
        await this._ctx.audioWorklet.addModule(this.workletUrl);
        const src = this._ctx.createMediaStreamSource(this._stream);
        this._node = new AudioWorkletNode(this._ctx, "mic-pcm-processor");
        this._node.port.onmessage = (ev) => this._onFrame(new Int16Array(ev.data));
        src.connect(this._node);
        const sink = this._ctx.createGain();
        sink.gain.value = 0;
        this._node.connect(sink).connect(this._ctx.destination);
      } finally {
        this._starting = false;
      }
    }

    _onFrame(frame) {
      const ds = downsampleTo16k(frame, this._ctx.sampleRate);
      if (this.ws && this.ws.readyState === 1) this.ws.send(ds.buffer);
      const e = rms(ds);
      if (e > this.energyThreshold) {
        this._aboveCount++;
        if (!this._localSpeaking && this._aboveCount >= 3) {
          this._localSpeaking = true;
          try { this.onLocalSpeechStart(); } catch (_) {}
        }
      } else {
        this._aboveCount = 0;
        if (this._localSpeaking) this._localSpeaking = false;
      }
    }

    async stop() {
      if (this._stopping) return this._stopping;
      this._stopping = (async () => {
        try { if (this._node) this._node.disconnect(); } catch (_) {}
        if (this._stream) this._stream.getTracks().forEach((t) => t.stop());
        if (this._ctx) { try { await this._ctx.close(); } catch (_) {} }
        this._node = null;
        this._stream = null;
        this._ctx = null;
      })();
      try { await this._stopping; } finally { this._stopping = null; }
    }
  }

  global.MicClient = MicClient;
})(window);
