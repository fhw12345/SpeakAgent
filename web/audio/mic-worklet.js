// web/audio/mic-worklet.js — AudioWorklet that downsamples mic input to 16 kHz
// mono Int16 PCM and posts fixed-size frames back to the main thread.
class MicPcmProcessor extends AudioWorkletProcessor {
  constructor(opts) {
    super();
    const o = (opts && opts.processorOptions) || {};
    this.nativeRate = o.nativeRate || sampleRate;
    this.targetRate = o.targetRate || 16000;
    this.frameSamples = o.frameSamples || 512;
    this.ratio = this.nativeRate / this.targetRate;
    this.acc = []; // accumulated downsampled float samples
    this.phase = 0;
    this._tap0 = 0;
    this._tap1 = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    // Anti-alias: 3-tap moving average across consecutive input samples,
    // then decimate by ratio. Without the prefilter, content above the
    // 8 kHz Nyquist of the 16 kHz target rate folds into the audible band
    // and degrades silero-vad probability + Whisper accuracy.
    for (let i = 0; i < ch.length; i++) {
      const a = this._tap0;
      const b = this._tap1;
      const c = ch[i];
      this._tap0 = b;
      this._tap1 = c;
      const filtered = (a + b + c) / 3;
      this.phase += 1;
      if (this.phase >= this.ratio) {
        this.acc.push(filtered);
        this.phase -= this.ratio;
      }
    }
    while (this.acc.length >= this.frameSamples) {
      const slice = this.acc.splice(0, this.frameSamples);
      const i16 = new Int16Array(this.frameSamples);
      for (let j = 0; j < this.frameSamples; j++) {
        const v = Math.max(-1, Math.min(1, slice[j]));
        i16[j] = v < 0 ? v * 0x8000 : v * 0x7FFF;
      }
      this.port.postMessage(i16.buffer, [i16.buffer]);
    }
    return true;
  }
}

registerProcessor('mic-pcm-processor', MicPcmProcessor);
