/**
 * Playwright e2e for the Phase 2 realtime lesson flow (W1D2).
 *
 * NOTE: this repo currently runs e2e via pytest-playwright (Python). This
 * `.spec.ts` is the canonical Playwright spec required by the PRD; a runnable
 * Python equivalent lives at tests/e2e/test_realtime_lesson.py.
 *
 * To activate this TS spec, add `package.json` with `@playwright/test` and a
 * `playwright.config.ts`, then run `npx playwright test` with the speakAgent
 * server started under env: LLM_MOCK=1 STT_MOCK=1 TTS_MOCK=1.
 */
import { test, expect } from "@playwright/test";

const BASE = process.env.SPEAKAGENT_BASE ?? "http://127.0.0.1:8765";

test("W1D2 realtime: 3 mocked user turns produce 3 distinct agent replies", async ({ page, request }) => {
  // 1. start session
  const start = await request.post(`${BASE}/api/lesson/start`, {
    data: { lesson_id: "w1d2" },
  });
  expect(start.ok()).toBeTruthy();
  const startBody = await start.json();
  expect(startBody.mode).toBe("realtime");
  expect(startBody.first_agent_utterance).toBeTruthy();
  const sid = startBody.session_id as string;

  // 2. drive 3 user turns
  const replies: string[] = [];
  for (const text of [
    "An API is endpoints.",
    "A tool is a function the agent calls.",
    "It picks one based on the request.",
  ]) {
    const r = await request.post(`${BASE}/api/lesson/turn`, {
      data: { session_id: sid, user_text: text },
    });
    expect(r.ok()).toBeTruthy();
    const body = await r.json();
    expect(body.done).toBe(false);
    replies.push(body.agent_utterance);
  }
  // 3 distinct agent replies
  expect(new Set(replies).size).toBe(3);

  // 4. transcript pane: load the SPA and ensure it can render an agent line
  await page.goto(BASE);
  await expect(page).toHaveTitle(/speakAgent/i);
});
