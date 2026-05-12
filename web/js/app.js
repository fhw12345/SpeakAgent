// web/js/app.js — view switching + dialogue rendering. Session/audio/WS logic
// lives in session.js; this file owns DOM, list/dialogue toggling, and wires
// the start button to a Session instance.
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
    dialogue.innerHTML = "";
    if (scorecard) scorecard.hidden = true;
    if (scorecardBody) scorecardBody.textContent = "";
    if (statusEl) statusEl.textContent = "idle";
    if (startBtn) startBtn.disabled = false;
    if (pttBtn) pttBtn.disabled = true;
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

  // Event wiring.
  window.addEventListener("lesson:open", (e) => {
    currentLesson = { id: e.detail.id, order: e.detail.order };
    showDialogue(e.detail.id);
  });

  window.addEventListener("session_end", (e) => {
    if (window.session) {
      try { window.session.stop(); } catch (_) {}
      window.session = null;
    }
    const finishedOrder = e.detail && e.detail.order;
    let nextOrder = null;
    if (finishedOrder != null) {
      nextOrder = finishedOrder >= 56 ? 1 : finishedOrder + 1;
    }
    currentLesson = null;
    showList(nextOrder);
  });

  if (backBtn) backBtn.addEventListener("click", () => {
    if (window.session) {
      try { window.session.stop(); } catch (_) {}
      window.session = null;
    }
    showList();
  });

  if (startBtn) {
    startBtn.addEventListener("click", async () => {
      if (window.__speakAgentReady) {
        try { await window.__speakAgentReady; } catch (_) {}
      }
      const ui = {
        appendDialogue,
        log,
        setStatus: (s) => { if (statusEl) statusEl.textContent = s; },
        startBtn,
        pttBtn,
        lessonTitle,
        scorecard,
        scorecardBody,
        onSessionEnd: () => {
          const finished = currentLesson;
          window.dispatchEvent(new CustomEvent("session_end", {
            detail: { lessonId: finished ? finished.id : null, order: finished ? finished.order : null },
          }));
        },
      };
      window.session = new window.Session(ui);
      await window.session.start();
    });
  }

  // Expose for tests.
  window.app = { showList, showDialogue, appendDialogue };
})();
