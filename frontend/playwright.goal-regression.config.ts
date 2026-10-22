import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e", testMatch: "search-goals.spec.ts", workers: 1, retries: 0,
  reporter: "line", timeout: 60000,
  use: { baseURL: "http://localhost:3000", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: {
    command: "npm run dev -- --webpack --hostname localhost --port 3000",
    url: "http://localhost:3000", reuseExistingServer: false, timeout: 120000,
    env: { NEXT_PUBLIC_API_URL: "http://127.0.0.1:18001", NEXT_DIST_DIR: ".next-goal-regression" },
  },
});
