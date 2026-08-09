import { defineConfig, devices } from "@playwright/test";

const captureDemo = process.env.UPDATE_DEMO_ASSETS === "1";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 0,
  reporter: "line",
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    video: captureDemo ? { mode: "on", size: { width: 1280, height: 800 } } : "off",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 800 },
        launchOptions: captureDemo ? { slowMo: 180 } : undefined,
      },
    },
    {
      name: "mobile-chromium",
      use: { ...devices["Pixel 7"] },
    },
  ],
  webServer: {
    command: "npm run dev -- --hostname localhost --port 3000",
    url: "http://localhost:3000",
    reuseExistingServer: true,
    timeout: 120_000,
    env: {
      NEXT_PUBLIC_API_URL: "http://127.0.0.1:18001",
    },
  },
});
