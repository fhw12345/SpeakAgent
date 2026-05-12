import { defineConfig, devices } from "@playwright/test";
import path from "path";

const FAKE_AUDIO = path.resolve(__dirname, "tests/e2e/fixtures/speech.wav");

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: /.*\.spec\.ts$/,
  timeout: 30_000,
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    baseURL: process.env.SPEAKAGENT_BASE_URL || "http://127.0.0.1:8765",
    trace: "retain-on-failure",
  },
  webServer: process.env.SPEAKAGENT_BASE_URL
    ? undefined
    : {
        command:
          "python -m uvicorn server.main:app --host 127.0.0.1 --port 8765 --log-level warning",
        url: "http://127.0.0.1:8765/",
        reuseExistingServer: true,
        timeout: 30_000,
        env: {
          SPEAKAGENT_PORT: "8765",
          SPEAKAGENT_VAD: "on",
          WHISPER_DEVICE: "cpu",
        },
      },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: {
          args: [
            "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream",
            `--use-file-for-fake-audio-capture=${FAKE_AUDIO}`,
            "--autoplay-policy=no-user-gesture-required",
          ],
        },
      },
    },
  ],
});
