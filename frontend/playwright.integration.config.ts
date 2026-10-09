import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./integration",
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: "line",
  use: { baseURL: "http://localhost:3001", trace: "retain-on-failure", ...devices["Desktop Chrome"] },
  webServer: [
    {
      command: "uv run python -m scripts.serve_acceptance_backend --fixture --fixture-semantic",
      cwd: "..",
      url: "http://127.0.0.1:18021/health",
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "npm run dev -- --hostname localhost --port 3001",
      url: "http://localhost:3001",
      reuseExistingServer: false,
      timeout: 120_000,
      env: { NEXT_PUBLIC_API_URL: "http://127.0.0.1:18021", NEXT_DIST_DIR: ".next-integration" },
    },
  ],
});
