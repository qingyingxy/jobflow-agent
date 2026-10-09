import { expect, test } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

test("real live results render with their saved analysis and original evidence", async ({ page, request }) => {
  const directory = resolve(process.env.JOBFLOW_ACCEPTANCE_DIR!);
  const reportPath = resolve(directory, "report.json");
  const report = JSON.parse(readFileSync(reportPath, "utf8"));
  expect(report.status).toBe("passed");
  await page.goto("/");
  await page.getByRole("combobox", { name: "范围", exact: true }).selectOption("saved");
  await page.getByRole("checkbox", { name: "显示明显不符或已关闭的岗位" }).check();
  await page.getByRole("button", { name: "全部展开", exact: true }).click();
  const shots: string[] = [];
  for (const source of report.sources) {
    const job = source.jobs[0];
    const expand = page.getByRole("button", { name: `展开${job.company}`, exact: true });
    if (await expand.isVisible()) await expand.click();
    await page.getByRole("button", { name: job.title, exact: true }).click();
    await expect(page.getByRole("heading", { name: "匹配依据", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "打开完整匹配与申请", exact: true }).click();
    await expect(page.getByRole("heading", { name: "资格检查", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "要求 × 经历证据", exact: true })).toBeVisible();
    const response = await request.get(`http://127.0.0.1:18021/api/jobs/${job.job_id}/analysis`, { headers: { "X-User-ID": "local-user" } });
    expect(response.ok()).toBeTruthy();
    expect((await response.json()).analysis_id).toBe(job.analysis.analysis_id);
    const shot = `${source.source}-analysis.png`;
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: resolve(directory, shot), fullPage: true, animations: "disabled" });
    shots.push(shot);
    await page.getByRole("button", { name: "返回岗位列表", exact: true }).click();
    await page.getByRole("combobox", { name: "范围", exact: true }).selectOption("saved");
    await page.getByRole("checkbox", { name: "显示明显不符或已关闭的岗位" }).check();
    await page.getByRole("button", { name: "全部展开", exact: true }).click();
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: resolve(directory, "saved-candidates.png"), fullPage: true, animations: "disabled" });
  report.frontend_verification = {
    status: "passed", checked_at: new Date().toISOString(), mocked_jobflow_api: false,
    screenshots: [...shots, "saved-candidates.png"], source_count: report.sources.length,
  };
  writeFileSync(reportPath, JSON.stringify(report, null, 2));
});
