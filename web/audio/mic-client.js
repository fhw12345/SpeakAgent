// web/audio/mic-client.js — manages mic capture via AudioWorklet, sends
// base64-encoded 16 kHz Int16 PCM frames as JSON {type:"audio_frame"} and
// emits {type:"interrupt"} on local energy spike during TTS playback.
(function () {
  class MicClient {
    constructor(ws, ttsPlayer, options) {
      this.ws = ws;
      this.ttsPlayer = ttsPlayer;
      this.audioCtx = null;
      this.node = null;
      this.stream = null;
      this.src = null;
      this.sink = null;
      this.energyOver = 0;
      this.interruptSent = false;
      this.metrics = (options && options.metrics) || null;
    }

    async start() {
      this.audioCtx = new AudioContext();
      await this.audioCtx.audioWorklet.addModule('/static/audio/mic-worklet.js');
      await this.audioCtx.resume();
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: false,
        },
      });
      this.src = this.audioCtx.createMediaStreamSource(this.stream);
      this.node = new AudioWorkletNode(this.audioCtx, 'mic-pcm-processor', {
        processorOptions: {
          nativeRate: this.audioCtx.sampleRate,
          targetRate: 16000,
          frameSamples: 512,
        },
      });
      this.node.port.onmessage = (e) => this._onFrame(e.data);
      this.sink = this.audioCtx.createGain();
      this.sink.gain.value = 0;
      this.src.connect(this.node);
      this.node.connect(this.sink);
      this.sink.connect(this.audioCtx.destination);
    }

    _onFrame(buf) {
      if (!this.ws || this.ws.readyState !== 1) return;
      const i16 = new Int16Array(buf);
      let sumsq = 0;
      for (let i = 0; i < i16.length; i++) {
        const v = i16[i] / 32768;
        sumsq += v * v;
      }
      const rms = Math.sqrt(sumsq / i16.length);
      const dbfs = 20 * Math.log10(rms + 1e-9);
      if (dbfs > -35) this.energyOver++;
      else this.energyOver = 0;
      if (
        this.energyOver >= 2 &&
        this.ttsPlayer &&
        this.ttsPlayer.isPlaying() &&
        !this.interruptSent
      ) {
        this.interruptSent = true;
        if (this.metrics) this.metrics.speechStartLocal = performance.now();
        try { this.ws.send(JSON.stringify({ type: 'interrupt' })); } catch (_) {}
      }
      const b64 = this._b64(buf);
      try { this.ws.send(JSON.stringify({ type: 'audio_frame', pcm_b64: b64 })); } catch (_) {}
    }

    resetInterrupt() {
      this.interruptSent = false;
      this.energyOver = 0;
    }

    _b64(buf) {
      let s = '';
      const u = new Uint8Array(buf);
      const CHUNK = 0x8000;
      for (let i = 0; i < u.length; i += CHUNK) {
        s += String.fromCharCode.apply(null, u.subarray(i, i + CHUNK));
      }
      return btoa(s);
    }

    async stop() {
      if (this.node) { try { this.node.disconnect(); } catch (_) {} this.node = null; }
      if (this.src) { try { this.src.disconnect(); } catch (_) {} this.src = null; }
      if (this.sink) { try { this.sink.disconnect(); } catch (_) {} this.sink = null; }
      if (this.stream) {
        try { this.stream.getTracks().forEach((t) => t.stop()); } catch (_) {}
        this.stream = null;
      }
      if (this.audioCtx) {
        try { await this.audioCtx.close(); } catch (_) {}
        this.audioCtx = null;
      }
    }
  }

  window.MicClient = MicClient;
})();
