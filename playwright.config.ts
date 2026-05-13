import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: /.*\.spec\.ts$/,
  timeout: 60_000,
  use: {
    baseURL: process.env.BASE_URL || "http://127.0.0.1:8765",
    trace: "on-first-retry",
  },
});
