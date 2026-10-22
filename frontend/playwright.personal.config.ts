import { defineConfig, devices } from "@playwright/test";
import { resolve } from "node:path";

const directory = resolve(process.env.JOBFLOW_PERSONAL_TRIAL || "../artifacts/personal-flow-20261019");
export default defineConfig({
  testDir: "./personal-acceptance", workers: 1, retries: 0, timeout: 60000, reporter: "line",
  use: { baseURL: "http://localhost:3001", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [
    { command: `.venv\\Scripts\\python.exe -X utf8 -m scripts.serve_acceptance_backend --database "${resolve(directory, "ui.db")}"`,
      cwd: "..", url: "http://127.0.0.1:18021/health", reuseExistingServer: false, timeout: 60000,
      env: { APP_ENV: "testing" } },
    { command: "npm run dev -- --hostname localhost --port 3001", url: "http://localhost:3001",
      reuseExistingServer: false, timeout: 120000,
      env: { NEXT_PUBLIC_API_URL: "http://127.0.0.1:18021", NEXT_DIST_DIR: ".next-personal" } },
  ],
});
