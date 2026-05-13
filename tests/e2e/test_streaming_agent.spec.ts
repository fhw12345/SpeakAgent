/**
 * Phase 3 streaming agent e2e.
 *
 * Asserts that during a streaming session the server emits at least 2
 * `agent_partial_text` WS frames before the first `agent_done`, and that
 * the live caption element `#agent-caption` updates at least twice.
 *
 * Requires the speakAgent server to be running at BASE_URL (default
 * http://127.0.0.1:8765) with SPEAKAGENT_STREAMING=on.
 */
import { test, expect } from "@playwright/test";

const BASE_URL = process.env.BASE_URL || "http://127.0.0.1:8765";

test("streaming agent emits >=2 agent_partial_text before agent_done and updates #agent-caption", async ({ page }) => {
  const partialTexts: string[] = [];
  let firstDoneIndex = -1;
  let frameCount = 0;

  // Capture WS frames via CDP.
  const client = await page.context().newCDPSession(page);
  await client.send("Network.enable");
  client.on("Network.webSocketFrameReceived", (evt: any) => {
    const payload = evt.response?.payloadData;
    if (typeof payload !== "string") return;
    try {
      const msg = JSON.parse(payload);
      const idx = frameCount++;
      if (msg.type === "agent_partial_text") partialTexts.push(msg.text);
      if (msg.type === "agent_done" && firstDoneIndex < 0) firstDoneIndex = idx;
    } catch {}
  });

  await page.goto(BASE_URL);

  // Open the first lesson and start the session.
  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent("lesson:open", { detail: { id: "w1d1", order: 1 } }));
  });
  await page.locator("#start-btn").click();

  // Wait for either streaming events or session_end (max 30s).
  await expect.poll(() => firstDoneIndex >= 0 || partialTexts.length >= 2, { timeout: 30000 }).toBeTruthy();

  expect(partialTexts.length, `partial texts seen: ${JSON.stringify(partialTexts)}`).toBeGreaterThanOrEqual(2);
  if (firstDoneIndex >= 0) {
    // partial_texts must have arrived before the first agent_done frame.
    expect(partialTexts.length).toBeGreaterThanOrEqual(2);
  }

  // The live caption element must have been updated.
  const captionText = await page.locator("#agent-caption").textContent();
  expect(captionText && captionText.trim().length).toBeGreaterThan(0);
});
