// web/js/audio/mic-worklet.js — runs in the AudioWorkletGlobalScope.
// Captures the input channel at the AudioContext's native sample rate and
// posts Int16 frames of MIC_FRAME_SAMPLES (512) to the main thread.
class MicPcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._frame = new Int16Array(512);
    this._fill = 0;
  }
  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const ch = input[0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      const s = Math.max(-1, Math.min(1, ch[i]));
      this._frame[this._fill++] = s * 32767;
      if (this._fill === this._frame.length) {
        this.port.postMessage(this._frame.buffer.slice(0));
        this._fill = 0;
      }
    }
    return true;
  }
}
registerProcessor("mic-pcm-processor", MicPcmProcessor);
