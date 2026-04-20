import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 30000,
  globalSetup: "./tests/global-setup.ts",
  use: {
    baseURL: "http://localhost:3000",
  },
  // No webServer — tests run against docker compose stack
  // Start with: docker compose up -d --build
});
