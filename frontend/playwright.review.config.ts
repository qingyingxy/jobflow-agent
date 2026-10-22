import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

export default defineConfig({
  ...base,
  testMatch: "review-priority.spec.ts",
  workers: 1,
  use: { ...base.use, baseURL: "http://localhost:3005" },
  webServer: {
    command: "npm run dev -- --webpack --hostname localhost --port 3005",
    url: "http://localhost:3005", reuseExistingServer: false, timeout: 120000,
    env: { NEXT_PUBLIC_API_URL: "http://127.0.0.1:18001", NEXT_DIST_DIR: ".next-review-ui" },
  },
});
