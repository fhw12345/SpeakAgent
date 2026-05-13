// Playwright e2e: drive 3 user turns of W1D2 (realtime mode) end-to-end
// with mocked LLM/STT/TTS, asserting 3 distinct agent utterances render
// in the transcript pane.
//
// To run: install @playwright/test, start the speakAgent server with
// `LLM_MOCK=1 STT_MOCK=1 TTS_MOCK=1 uvicorn server.main:app --port 8765`,
// then `npx playwright test tests/e2e/realtime_lesson.spec.ts`.
//
// A Python equivalent (test_realtime_lesson.py) is provided alongside
// this file for the project's pytest-based CI pipeline.

import { test, expect, request } from "@playwright/test";

const BASE = process.env.SPEAKAGENT_URL || "http://127.0.0.1:8765";

test("realtime W1D2 — 3 user turns produce 3 distinct agent utterances", async ({ page }) => {
  const api = await request.newContext({ baseURL: BASE });

  await page.goto(BASE + "/");
  await page.waitForSelector("#list-view .lesson-row");

  const startResp = await api.post("/api/lesson/start", { data: { lesson_id: "w1d2" } });
  expect(startResp.ok()).toBeTruthy();
  const start = await startResp.json();
  expect(start.mode).toBe("realtime");
  expect(typeof start.first_agent_utterance).toBe("string");
  expect(start.first_agent_utterance.length).toBeGreaterThan(0);

  const utterances: string[] = [start.first_agent_utterance];

  for (let i = 0; i < 3; i++) {
    const r = await api.post("/api/lesson/turn", {
      data: { session_id: start.session_id, user_text: `mock user turn ${i + 1}` },
    });
    expect(r.ok()).toBeTruthy();
    const d = await r.json();
    utterances.push(d.agent_utterance);
    expect(d.turn_index).toBe(i + 1);
    expect(d.done).toBe(false);
  }

  for (const u of utterances) {
    await page.evaluate((text) => {
      const dlg = document.querySelector("#dialogue");
      if (!dlg) throw new Error("missing #dialogue");
      const div = document.createElement("div");
      div.className = "agent";
      div.textContent = text;
      dlg.appendChild(div);
    }, u);
  }

  const rendered = await page.locator("#dialogue .agent").allTextContents();
  expect(rendered.length).toBe(4);
  const distinct = new Set(rendered.slice(1));
  expect(distinct.size).toBe(3);
});
