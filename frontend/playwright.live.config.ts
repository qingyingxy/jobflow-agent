import { defineConfig, devices } from "@playwright/test";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

const directory = process.env.JOBFLOW_ACCEPTANCE_DIR;
if (!directory || !existsSync(resolve(directory, "report.json"))) {
  throw new Error("Set JOBFLOW_ACCEPTANCE_DIR to an existing live acceptance directory");
}
const database = resolve(directory, "acceptance.db");
export default defineConfig({
  testDir: "./live-acceptance",
  workers: 1, retries: 0, timeout: 120_000, reporter: "line",
  use: { baseURL: "http://localhost:3001", trace: "retain-on-failure", ...devices["Desktop Chrome"], viewport: { width: 1920, height: 1080 }, contextOptions: { reducedMotion: "reduce" } },
  webServer: [
    { command: `uv run python -m scripts.serve_acceptance_backend --database "${database}"`, cwd: "..", url: "http://127.0.0.1:18021/health", reuseExistingServer: false, timeout: 60_000 },
    { command: "npm run dev -- --hostname localhost --port 3001", url: "http://localhost:3001", reuseExistingServer: false, timeout: 120_000,
      env: { NEXT_PUBLIC_API_URL: "http://127.0.0.1:18021", NEXT_DIST_DIR: ".next-integration" } },
  ],
});
