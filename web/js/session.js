// web/js/session.js — encapsulates WebSocket session, TTS playback, and mic
// capture. Branches on window.SPEAKAGENT_VAD: "on" uses MicClient + AudioWorklet
// streaming audio_frame messages; otherwise falls back to legacy push-to-talk
// with raw 16 kHz Int16 PCM over the binary channel.
(function () {
  function metricsEnabled() {
    try {
      return new URLSearchParams(location.search).get('metrics') === '1';
    } catch (_) {
      return false;
    }
  }

  class Session {
    constructor(ui, opts) {
      this.ui = ui;
      this.lessonId = (opts && opts.lessonId) || 'W1D1';
      this.mode = (opts && opts.mode) || 'scripted';
      this.ws = null;
      this.ttsPlayer = null;
      this.micClient = null;
      this.vad = false;
      this.metrics = null;
      this.currentBuffer = null;
      // PTT state
      this.recording = false;
      this.pttCtx = null;
      this.pttStream = null;
      this.pttProc = null;
      // realtime REST state
      this.realtimeSessionId = null;
      // bound spacebar handlers (so stop() can remove them)
      this._kd = null;
      this._ku = null;
      this._md = null;
      this._mu = null;
    }

    async start() {
      this.vad = window.SPEAKAGENT_VAD === 'on';
      // Capability check: if AudioWorklet not available, fall back to PTT.
      if (this.vad && typeof AudioWorkletNode === 'undefined') {
        try { console.log('AudioWorkletNode unavailable; falling back to PTT'); } catch (_) {}
        this.vad = false;
      }

      if (this.ui.startBtn) this.ui.startBtn.disabled = true;
      this.ui.setStatus('connecting');

      if (this.mode === 'realtime') {
        // Realtime mode also uses the WS so STT/TTS audio flows the same
        // way as scripted lessons; the server-side ws_session router
        // dispatches to handle_realtime_ws based on the mode query param.
        const qs = `?lesson_id=${encodeURIComponent(this.lessonId)}&mode=realtime`;
        this.ws = new WebSocket(`ws://${location.host}/ws/session${qs}`);
      } else {
        const qs = `?lesson_id=${encodeURIComponent(this.lessonId)}`;
        this.ws = new WebSocket(`ws://${location.host}/ws/session${qs}`);
      }
      this.ws.binaryType = 'arraybuffer';

      if (metricsEnabled()) {
        window.__speakAgentMetrics = {
          speechStartLocal: null,
          ttsStop: null,
          firstAudioChunkAfterInterrupt: null,
        };
        this.metrics = window.__speakAgentMetrics;
      }

      this.ttsPlayer = new window.TtsPlayer();
      if (this.metrics) this.ttsPlayer.metrics = this.metrics;

      this.ws.onmessage = (ev) => this._onMessage(ev);
      this.ws.onerror = (e) => this.ui.log('ws error ' + e);
      this.ws.onclose = () => {
        this.ui.setStatus('disconnected');
        if (this.ui.pttBtn) this.ui.pttBtn.disabled = true;
      };

      // PTT bindings (only effective in OFF path; harmless in VAD path because
      // pttBtn stays disabled).
      if (!this.vad) {
        this._kd = (e) => {
          if (
            e.code === 'Space' &&
            this.ui.pttBtn &&
            !this.ui.pttBtn.disabled &&
            !this.recording
          ) {
            e.preventDefault();
            this._startRecording();
          }
        };
        this._ku = (e) => {
          if (e.code === 'Space' && this.recording) {
            e.preventDefault();
            this._stopRecording();
          }
        };
        document.addEventListener('keydown', this._kd);
        document.addEventListener('keyup', this._ku);
        if (this.ui.pttBtn) {
          this._md = () => this._startRecording();
          this._mu = () => this._stopRecording();
          this.ui.pttBtn.addEventListener('mousedown', this._md);
          this.ui.pttBtn.addEventListener('mouseup', this._mu);
        }
      }
    }

    stop() {
      if (this._kd) document.removeEventListener('keydown', this._kd);
      if (this._ku) document.removeEventListener('keyup', this._ku);
      if (this.ui.pttBtn) {
        if (this._md) this.ui.pttBtn.removeEventListener('mousedown', this._md);
        if (this._mu) this.ui.pttBtn.removeEventListener('mouseup', this._mu);
      }
      this._kd = this._ku = this._md = this._mu = null;
      if (this.micClient) {
        try { this.micClient.stop(); } catch (_) {}
        this.micClient = null;
      }
      if (this.ttsPlayer) {
        try { this.ttsPlayer.stopAll(); } catch (_) {}
      }
      if (this.ws && this.ws.readyState === 1) {
        try { this.ws.close(); } catch (_) {}
      }
    }

    async _onMessage(ev) {
      if (typeof ev.data === 'string') {
        let msg;
        try { msg = JSON.parse(ev.data); } catch (_) { return; }
        this.ui.log('<- ' + msg.type);

        if (msg.type === 'session_start') {
          this.ui.setStatus('ready');
          if (msg.lesson && this.ui.lessonTitle) this.ui.lessonTitle.textContent = msg.lesson;
          if (this.vad) {
            try {
              this.micClient = new window.MicClient(this.ws, this.ttsPlayer, { metrics: this.metrics });
              await this.micClient.start();
            } catch (e) {
              this.ui.log('mic start failed: ' + e);
              // Fall back to PTT for this session.
              this.vad = false;
              this.micClient = null;
            }
          }
        } else if (msg.type === 'agent_caption') {
          this.ui.appendDialogue('agent', msg.text, { gloss: msg.gloss, translation: msg.translation });
          this.currentBuffer = [];
          // New agent turn → reset interrupt latch so user can barge in again.
          if (this.micClient) this.micClient.resetInterrupt();
        } else if (msg.type === 'agent_done') {
          if (this.currentBuffer) {
            this.ttsPlayer.enqueueChunks(this.currentBuffer);
            this.currentBuffer = null;
          }
        } else if (msg.type === 'user_prompt') {
          this.ui.appendDialogue('agent', '[' + msg.prompt + ']', { gloss: msg.gloss, translation: msg.translation });
          if (msg.ideal) this.ui.appendDialogue('agent', '  → ' + msg.ideal, {});
          if (!this.vad && this.ui.pttBtn) this.ui.pttBtn.disabled = false;
          this.ui.setStatus(this.vad ? 'your turn — speak' : 'your turn — hold SPACE');
        } else if (msg.type === 'user_transcript') {
          this.ui.appendDialogue('user', msg.text);
        } else if (msg.type === 'score') {
          if (this.ui.scorecard) this.ui.scorecard.hidden = false;
          if (this.ui.scorecardBody) this.ui.scorecardBody.textContent = JSON.stringify(msg.score, null, 2);
        } else if (msg.type === 'session_end') {
          this.ui.setStatus('session complete');
          if (this.ui.scorecard) this.ui.scorecard.hidden = false;
          if (this.ui.scorecardBody) this.ui.scorecardBody.textContent = JSON.stringify(msg.scores, null, 2);
          // Tear down mic before app dispatches session_end.
          if (this.micClient) {
            try { await this.micClient.stop(); } catch (_) {}
            this.micClient = null;
          }
          if (typeof this.ui.onSessionEnd === 'function') this.ui.onSessionEnd();
        } else if (msg.type === 'user_speech_start') {
          // Server-confirmed barge-in: stop any in-flight TTS immediately.
          this.ttsPlayer.stopAll();
        } else if (msg.type === 'user_speech_end') {
          this.ui.setStatus('scoring…');
        } else if (msg.type === 'turn_end') {
          // Reserved for future use; no-op while server still emits agent_done.
        }
      } else {
        // Binary: TTS MP3 chunk.
        if (
          this.metrics &&
          this.metrics.speechStartLocal &&
          !this.metrics.firstAudioChunkAfterInterrupt
        ) {
          this.metrics.firstAudioChunkAfterInterrupt = performance.now();
        }
        if (this.currentBuffer) this.currentBuffer.push(ev.data);
      }
    }

    // ---- Legacy push-to-talk (OFF path) ----
    async _startRecording() {
      if (this.recording) return;
      this.recording = true;
      this.ui.setStatus('recording…');
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { sampleRate: 16000, channelCount: 1 } });
      const ctx = new AudioContext({ sampleRate: 16000 });
      const src = ctx.createMediaStreamSource(stream);
      const proc = ctx.createScriptProcessor(4096, 1, 1);
      proc.onaudioprocess = (ev) => {
        const f32 = ev.inputBuffer.getChannelData(0);
        const i16 = new Int16Array(f32.length);
        for (let i = 0; i < f32.length; i++) i16[i] = Math.max(-1, Math.min(1, f32[i])) * 32767;
        if (this.ws && this.ws.readyState === 1) this.ws.send(i16.buffer);
      };
      src.connect(proc);
      const sink = ctx.createGain();
      sink.gain.value = 0;
      proc.connect(sink);
      sink.connect(ctx.destination);
      this.pttCtx = ctx;
      this.pttStream = stream;
      this.pttProc = proc;
    }

    async _stopRecording() {
      if (!this.recording) return;
      this.recording = false;
      this.ui.setStatus('scoring…');
      if (this.pttProc) { try { this.pttProc.disconnect(); } catch (_) {} this.pttProc = null; }
      if (this.pttStream) {
        try { this.pttStream.getTracks().forEach((t) => t.stop()); } catch (_) {}
        this.pttStream = null;
      }
      if (this.pttCtx) {
        try { await this.pttCtx.close(); } catch (_) {}
        this.pttCtx = null;
      }
      if (this.ws && this.ws.readyState === 1) {
        try { this.ws.send(JSON.stringify({ type: 'user_audio_end' })); } catch (_) {}
      }
      if (this.ui.pttBtn) this.ui.pttBtn.disabled = true;
    }
  }

  window.Session = Session;
})();
