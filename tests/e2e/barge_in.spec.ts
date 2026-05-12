import { test, expect, type WebSocketRoute } from "@playwright/test";

const BARGE_IN_BUDGET_MS = 1000;

type Metrics = {
  lastInterruptSentAt?: number;
  lastVadOnsetAt?: number;
  lastStopAllAt?: number;
  lastNewAgentTokenAt?: number;
  stopAllCallCount?: number;
  agentTokenSeq?: number[];
};

declare global {
  interface Window {
    __speakAgentMetrics?: Metrics;
    SPEAKAGENT_VAD?: string;
  }
}

function installMockWsServer(ws: WebSocketRoute) {
  let firstStreamTimer: NodeJS.Timeout | null = null;
  let secondStreamStarted = false;
  let cancelled = false;

  const stopFirstStream = () => {
    cancelled = true;
    if (firstStreamTimer) {
      clearInterval(firstStreamTimer);
      firstStreamTimer = null;
    }
  };

  const startSecondStream = () => {
    if (secondStreamStarted) return;
    secondStreamStarted = true;
    ws.send(
      JSON.stringify({ type: "agent_token", text: "B", turn_id: 2, seq: 0 }),
    );
  };

  ws.onMessage((raw) => {
    let msg: { type?: string };
    try {
      msg = typeof raw === "string" ? JSON.parse(raw) : { type: "binary" };
    } catch {
      msg = {};
    }
    if (msg.type === "interrupt" || msg.type === "user_speech_start") {
      if (!cancelled) {
        stopFirstStream();
        ws.send(JSON.stringify({ type: "user_speech_start" }));
        ws.send(
          JSON.stringify({ type: "user_speech_end", segment_id: "seg-1" }),
        );
        setTimeout(startSecondStream, 50);
      }
    }
  });

  ws.onClose(stopFirstStream);

  let seq = 0;
  firstStreamTimer = setInterval(() => {
    if (cancelled) return;
    ws.send(
      JSON.stringify({ type: "agent_token", text: "A", turn_id: 1, seq }),
    );
    ws.send(
      JSON.stringify({
        type: "tts_audio_chunk",
        turn_id: 1,
        seq,
        pcm_b64: "AAAA",
      }),
    );
    seq += 1;
  }, 40);
}

test.describe("Phase 4 barge-in", () => {
  test.beforeEach(async ({ page, context }) => {
    await context.grantPermissions(["microphone"]);

    await page.addInitScript(() => {
      window.SPEAKAGENT_VAD = "on";
      window.__speakAgentMetrics = {
        stopAllCallCount: 0,
        agentTokenSeq: [],
      };
    });

    await page.route("**/config", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ vad: "on" }),
      }),
    );

    await page.routeWebSocket("**/ws/session*", (ws) => {
      installMockWsServer(ws);
    });
  });

  test("barge-in restarts agent within 1s", async ({ page }) => {
    await page.goto("/");

    await page.waitForFunction(
      () =>
        !!window.__speakAgentMetrics &&
        Array.isArray(window.__speakAgentMetrics.agentTokenSeq),
    );

    await page.waitForFunction(
      () => (window.__speakAgentMetrics?.agentTokenSeq?.length ?? 0) >= 2,
      null,
      { timeout: 5_000 },
    );

    await page.waitForFunction(
      () => typeof window.__speakAgentMetrics?.lastVadOnsetAt === "number",
      null,
      { timeout: 8_000 },
    );

    await page.waitForFunction(
      () => (window.__speakAgentMetrics?.stopAllCallCount ?? 0) >= 1,
      null,
      { timeout: 2_000 },
    );

    const onsetAt = await page.evaluate(
      () => window.__speakAgentMetrics?.lastVadOnsetAt as number,
    );

    await page.waitForFunction(
      (onset: number) => {
        const m = window.__speakAgentMetrics;
        return (
          typeof m?.lastNewAgentTokenAt === "number" &&
          m.lastNewAgentTokenAt > onset
        );
      },
      onsetAt,
      { timeout: BARGE_IN_BUDGET_MS + 500 },
    );

    const metrics = (await page.evaluate(
      () => window.__speakAgentMetrics,
    )) as Metrics;

    expect(metrics.stopAllCallCount, "tts-player.stopAll must be called").toBeGreaterThanOrEqual(1);
    expect(metrics.lastStopAllAt, "lastStopAllAt must be recorded").toBeDefined();
    expect(metrics.lastVadOnsetAt, "lastVadOnsetAt must be recorded").toBeDefined();
    expect(metrics.lastNewAgentTokenAt, "lastNewAgentTokenAt must be recorded").toBeDefined();

    const onset = metrics.lastVadOnsetAt!;
    const stop = metrics.lastStopAllAt!;
    const newToken = metrics.lastNewAgentTokenAt!;

    expect(stop, "stopAll must fire at or after VAD onset").toBeGreaterThanOrEqual(onset);
    expect(newToken, "new agent_token must arrive after onset").toBeGreaterThan(onset);

    const bargeInLatency = newToken - onset;
    expect(
      bargeInLatency,
      `barge-in latency ${bargeInLatency.toFixed(1)}ms must be <= ${BARGE_IN_BUDGET_MS}ms`,
    ).toBeLessThanOrEqual(BARGE_IN_BUDGET_MS);
  });
});
