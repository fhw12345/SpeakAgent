// web/app.js — vanilla front end. Push-to-talk on spacebar.
const dialogue = document.getElementById("dialogue");
const startBtn = document.getElementById("start-btn");
const pttBtn = document.getElementById("ptt-btn");
const statusEl = document.getElementById("status");
const lessonTitle = document.getElementById("lesson-title");
const scorecard = document.getElementById("scorecard");
const scorecardBody = document.getElementById("scorecard-body");
const devLog = document.getElementById("dev-log");

let ws = null;
let mediaRecorder = null;
let audioCtx = null;
let pcmChunks = [];
let recording = false;

function log(msg) {
  console.log(msg);
  devLog.textContent += msg + "\n";
  devLog.scrollTop = devLog.scrollHeight;
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

async function loadToday() {
  const r = await fetch("/api/today");
  const j = await r.json();
  lessonTitle.textContent = j.title;
}

async function startSession() {
  startBtn.disabled = true;
  statusEl.textContent = "connecting";
  ws = new WebSocket(`ws://${location.host}/ws/session`);
  ws.binaryType = "arraybuffer";

  // Strict FIFO playback. Each agent turn = one buffer. Caption opens a new
  // buffer; bytes append to the *current* (open) buffer; agent_done seals it
  // and appends to the queue. A single worker awaits onended before pulling
  // the next item, so two voices can never overlap regardless of how fast
  // the server pushes.
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
      }
    } else {
      if (currentBuffer) currentBuffer.push(ev.data);
    }
  };

  ws.onerror = (e) => log("ws error " + e);
  ws.onclose = () => { statusEl.textContent = "disconnected"; pttBtn.disabled = true; };
}

async function playMp3Chunks(chunks) {
  if (!chunks.length) return;
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

async function startRecording() {
  if (recording) return;
  recording = true;
  statusEl.textContent = "recording…";
  pcmChunks = [];
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
  // Connect to a muted gain node instead of destination — ScriptProcessor
  // requires a downstream node to fire onaudioprocess, but we don't want
  // to hear the mic in the speakers (that causes feedback).
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

document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && !pttBtn.disabled && !recording) { e.preventDefault(); startRecording(); }
});
document.addEventListener("keyup", (e) => {
  if (e.code === "Space" && recording) { e.preventDefault(); stopRecording(); }
});
pttBtn.addEventListener("mousedown", startRecording);
pttBtn.addEventListener("mouseup", stopRecording);
startBtn.addEventListener("click", startSession);

loadToday();
