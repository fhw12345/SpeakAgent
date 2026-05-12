// web/js/list_view.js — fetches /api/lessons and renders the course list.
(function () {
  const listEl = document.getElementById("lesson-list");
  const noticeEl = document.getElementById("list-notice");

  let cachedLessons = null;
  let noticeTimer = null;

  function showNotice(text) {
    if (!noticeEl) return;
    noticeEl.textContent = text;
    noticeEl.hidden = false;
    if (noticeTimer) clearTimeout(noticeTimer);
    noticeTimer = setTimeout(() => { noticeEl.hidden = true; }, 2500);
  }

  function renderList(lessons, nextOrder) {
    cachedLessons = lessons;
    listEl.innerHTML = "";
    for (const l of lessons) {
      const row = document.createElement("div");
      row.className = "lesson-row" + (l.available ? "" : " unavailable");
      if (nextOrder != null && l.order === nextOrder) row.classList.add("next-lesson");
      row.dataset.id = l.id;
      row.dataset.order = String(l.order);
      row.dataset.available = String(l.available);

      const id = document.createElement("span");
      id.className = "lesson-id";
      id.textContent = `W${l.week}D${l.day}`;

      const sep = document.createElement("span");
      sep.textContent = " — ";

      const title = document.createElement("span");
      title.className = "lesson-title";
      title.textContent = l.title;

      row.appendChild(id);
      row.appendChild(sep);
      row.appendChild(title);

      row.addEventListener("click", () => {
        if (!l.available) {
          showNotice("Coming soon");
          return;
        }
        window.dispatchEvent(new CustomEvent("lesson:open", {
          detail: { id: l.id, order: l.order },
        }));
      });

      listEl.appendChild(row);
    }
  }

  async function fetchAndRender(nextOrder) {
    const r = await fetch("/api/lessons");
    const j = await r.json();
    renderList(j.lessons, nextOrder);
  }

  // Expose for app.js to trigger refresh on return-to-list.
  window.listView = {
    renderList,
    fetchAndRender,
    getCachedLessons: () => cachedLessons,
  };

  fetchAndRender();
})();
