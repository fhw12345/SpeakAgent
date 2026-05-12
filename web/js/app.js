// web/js/app.js — view switching + dialogue logic. Push-to-talk on spacebar.
(function () {
  const listView = document.getElementById("list-view");
  const dialogueView = document.getElementById("dialogue-view");
  const dialogue = document.getElementById("dialogue");
  const startBtn = document.getElementById("start-btn");
  const pttBtn = document.getElementById("ptt-btn");
  const backBtn = document.getElementById("back-btn");
  const statusEl = document.getElementById("status");
  const lessonTitle = document.getElementById("lesson-title");
  const scorecard = document.getElementById("scorecard");
  const scorecardBody = document.getElementById("scorecard-body");
  const devLog = document.getElementById("dev-log");

  let ws = null;
  let audioCtx = null;
  let recording = false;
  let currentLesson = null; // { id, order }

  function log(msg) {
    console.log(msg);
    if (devLog) {
      devLog.textContent += msg + "\n";
      devLog.scrollTop = devLog.scrollHeight;
    }
  }

  function showList(nextOrder) {
    dialogueView.hidden = true;
    listView.hidden = false;
    // Reset dialogue area for a clean next session.
    dialogue.innerHTML = "";
    if (scorecard) scorecard.hidden = true;
    if (scorecardBody) scorecardBody.textContent = "";
    if (statusEl) statusEl.textContent = "idle";
    if (startBtn) startBtn.disabled = false;
    if (pttBtn) { pttBtn.disabled = true; pttBtn.hidden = false; }
    const rtControls = document.getElementById("realtime-controls");
    const rtInput = document.getElementById("realtime-input");
    if (rtControls) rtControls.hidden = true;
    if (rtInput) { rtInput.value = ""; rtInput.disabled = false; }
    lessonTitle.textContent = "";
    if (window.listView) window.listView.fetchAndRender(nextOrder);
  }

  function showDialogue(lessonId) {
    listView.hidden = true;
    dialogueView.hidden = false;
    dialogue.innerHTML = "";
    if (scorecard) scorecard.hidden = true;
    if (scorecardBody) scorecardBody.textContent = "";
    if (statusEl) statusEl.textContent = "idle";
    lessonTitle.textContent = lessonId;
  }

  function appendDialogue(role, text, extras) {
    const div = document.createElement("div");
    div.className = role;
    div.textContent = (role === "agent" ? "Coach: " : "You: ") + text;
    dialogue.appendChild(div);
    if (extras && extras.translation) {
      const tr = document.createElement("div");
      tr.className = "translation";
      tr.textContent = "  " + extras.translation;
      dialogue.appendChild(tr);
    }
    if (extras && extras.gloss && extras.gloss.length) {
      const gl = document.createElement("div");
      gl.className = "gloss";
      gl.textContent = "  " + extras.gloss.map(g => `${g.w} ${g.ipa || ""} ${g.zh || ""}`.trim()).join("  ·  ");
      dialogue.appendChild(gl);
    }
    dialogue.scrollTop = dialogue.scrollHeight;
  }

  async function startSession() {
    startBtn.disabled = true;
    statusEl.textContent = "connecting";
    ws = new WebSocket(`ws://${location.host}/ws/session`);
    ws.binaryType = "arraybuffer";

    let currentBuffer = null;
    const playQueue = [];
    let workerRunning = false;

    async function playWorker() {
      if (workerRunning) return;
      workerRunning = true;
      try {
        while (playQueue.length) {
          const chunks = playQueue.shift();
          if (!chunks.length) continue;
          const blob = new Blob(chunks, { type: "audio/mpeg" });
          const url = URL.createObjectURL(blob);
          const a = new Audio(url);
          await new Promise((resolve) => {
            a.onended = resolve;
            a.onerror = resolve;
            a.play().catch((e) => { log("audio play err " + e); resolve(); });
          });
          URL.revokeObjectURL(url);
        }
      } finally {
        workerRunning = false;
      }
    }

    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        const msg = JSON.parse(ev.data);
        log(`<- ${msg.type}`);
        if (msg.type === "session_start") {
          statusEl.textContent = "ready";
          if (msg.lesson) lessonTitle.textContent = msg.lesson;
        } else if (msg.type === "agent_caption") {
          appendDialogue("agent", msg.text, { gloss: msg.gloss, translation: msg.translation });
          currentBuffer = [];
        } else if (msg.type === "agent_done") {
          if (currentBuffer) { playQueue.push(currentBuffer); currentBuffer = null; }
          playWorker();
        } else if (msg.type === "user_prompt") {
          appendDialogue("agent", "[" + msg.prompt + "]", { gloss: msg.gloss, translation: msg.translation });
          if (msg.ideal) appendDialogue("agent", "  → " + msg.ideal, {});
          pttBtn.disabled = false;
          statusEl.textContent = "your turn — hold SPACE";
        } else if (msg.type === "user_transcript") {
          appendDialogue("user", msg.text);
        } else if (msg.type === "score") {
          scorecard.hidden = false;
          scorecardBody.textContent = JSON.stringify(msg.score, null, 2);
        } else if (msg.type === "session_end") {
          statusEl.textContent = "session complete";
          scorecard.hidden = false;
          scorecardBody.textContent = JSON.stringify(msg.scores, null, 2);
          const finished = currentLesson;
          window.dispatchEvent(new CustomEvent("session_end", {
            detail: { lessonId: finished ? finished.id : null, order: finished ? finished.order : null },
          }));
        }
      } else {
        if (currentBuffer) currentBuffer.push(ev.data);
      }
    };

    ws.onerror = (e) => log("ws error " + e);
    ws.onclose = () => { statusEl.textContent = "disconnected"; pttBtn.disabled = true; };
  }

  async function startRecording() {
    if (recording) return;
    recording = true;
    statusEl.textContent = "recording…";
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { sampleRate: 16000, channelCount: 1 } });
    audioCtx = new AudioContext({ sampleRate: 16000 });
    const src = audioCtx.createMediaStreamSource(stream);
    const proc = audioCtx.createScriptProcessor(4096, 1, 1);
    proc.onaudioprocess = (ev) => {
      const f32 = ev.inputBuffer.getChannelData(0);
      const i16 = new Int16Array(f32.length);
      for (let i = 0; i < f32.length; i++) i16[i] = Math.max(-1, Math.min(1, f32[i])) * 32767;
      if (ws && ws.readyState === 1) ws.send(i16.buffer);
    };
    src.connect(proc);
    const sink = audioCtx.createGain();
    sink.gain.value = 0;
    proc.connect(sink);
    sink.connect(audioCtx.destination);
    window._sttStream = stream;
    window._sttProc = proc;
  }

  async function stopRecording() {
    if (!recording) return;
    recording = false;
    statusEl.textContent = "scoring…";
    if (window._sttProc) window._sttProc.disconnect();
    if (window._sttStream) window._sttStream.getTracks().forEach((t) => t.stop());
    if (audioCtx) await audioCtx.close();
    if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: "user_audio_end" }));
    pttBtn.disabled = true;
  }

  // Event wiring.
  window.addEventListener("lesson:open", async (e) => {
    currentLesson = { id: e.detail.id, order: e.detail.order };
    showDialogue(e.detail.id);
    try {
      const r = await fetch("/api/lesson/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lesson_id: e.detail.id }),
      });
      const j = await r.json();
      if (j.mode === "realtime") {
        startRealtime(j);
      }
    } catch (err) {
      log("lesson_start_err " + err);
    }
  });

  function startRealtime(startResp) {
    const sessionId = startResp.session_id;
    if (startBtn) startBtn.disabled = true;
    if (pttBtn) { pttBtn.disabled = true; pttBtn.hidden = true; }
    const rtControls = document.getElementById("realtime-controls");
    const rtInput = document.getElementById("realtime-input");
    const rtSend = document.getElementById("realtime-send");
    if (rtControls) rtControls.hidden = false;
    statusEl.textContent = "realtime — type to reply";
    appendDialogue("agent", startResp.first_agent_utterance, {});

    let done = false;

    async function sendUserTurn() {
      if (done) return;
      const text = (rtInput.value || "").trim();
      if (!text) return;
      rtInput.value = "";
      appendDialogue("user", text);
      rtSend.disabled = true;
      try {
        const r = await fetch("/api/lesson/turn", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, user_text: text }),
        });
        const j = await r.json();
        if (j.agent_utterance) appendDialogue("agent", j.agent_utterance, {});
        if (j.done) {
          done = true;
          statusEl.textContent = "session complete";
          rtInput.disabled = true;
          window.dispatchEvent(new CustomEvent("session_end", {
            detail: {
              lessonId: currentLesson ? currentLesson.id : null,
              order: currentLesson ? currentLesson.order : null,
            },
          }));
        }
      } catch (err) {
        log("realtime_turn_err " + err);
      } finally {
        rtSend.disabled = false;
      }
    }

    if (rtSend) rtSend.onclick = sendUserTurn;
    if (rtInput) rtInput.onkeydown = (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); sendUserTurn(); }
    };
  }


  window.addEventListener("session_end", (e) => {
    if (ws && ws.readyState === 1) try { ws.close(); } catch (_) {}
    const finishedOrder = e.detail && e.detail.order;
    let nextOrder = null;
    if (finishedOrder != null) {
      nextOrder = finishedOrder >= 56 ? 1 : finishedOrder + 1;
    }
    currentLesson = null;
    showList(nextOrder);
  });

  if (backBtn) backBtn.addEventListener("click", () => showList());

  document.addEventListener("keydown", (e) => {
    if (e.code === "Space" && pttBtn && !pttBtn.disabled && !recording) { e.preventDefault(); startRecording(); }
  });
  document.addEventListener("keyup", (e) => {
    if (e.code === "Space" && recording) { e.preventDefault(); stopRecording(); }
  });
  if (pttBtn) {
    pttBtn.addEventListener("mousedown", startRecording);
    pttBtn.addEventListener("mouseup", stopRecording);
  }
  if (startBtn) startBtn.addEventListener("click", startSession);

  // Expose for tests.
  window.app = { showList, showDialogue };
})();
