import { expect, test } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve("..");
const directory = resolve(process.env.JOBFLOW_CONTINUOUS_TRIAL!);
const final = JSON.parse(readFileSync(resolve(directory, "../final.json"), "utf8")) as {
  tracked: { id: string; title: string; source_url: string; decisions: Record<string, { evidence: string[] }> }[];
};

// Replay recorded real-model checkpoints, without changing the personal DB or
// calling a model. All API reads and frontend polling remain real.
function checkpoint(phase: "before" | "after") {
  execFileSync(resolve(root, ".venv/Scripts/python.exe"), ["-X", "utf8", "-c", `
import sqlite3, sys
from pathlib import Path
root, target, phase, *ids = sys.argv[1:]
root, target = Path(root), Path(target).resolve()
assert target.parent == (root / 'artifacts/queue-recovery-20261019/ui').resolve()
source = root / ('artifacts/generic-personal-repairs-20261019/trial.db' if phase == 'before' else 'artifacts/queue-recovery-20261019/trial.db')
with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src, sqlite3.connect(target) as dst:
    for identifier in ids:
        row = src.execute('select recruitment_context from job_postings where id=?', (identifier,)).fetchone()
        assert row is not None
        assert dst.execute('update job_postings set recruitment_context=? where id=?', (row[0], identifier)).rowcount == 1
`, root, resolve(directory, "trial.db"), phase, ...final.tracked.map(job => job.id)]);
}

test("recorded AI recovery appears automatically with evidence and separate queues", async ({ page }, info) => {
  checkpoint("before");
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByLabel("当前求职目标")).toContainText("2027", { timeout: 30000 });
  const keyword = page.getByRole("textbox", { name: "公司 / 岗位", exact: true });
  const queue = page.getByLabel("正文复核进度");
  await expect(queue).toContainText("岗位判断：", { timeout: 15000 });
  await expect(queue).toContainText("任职条件补全：");
  const rowFor = (title: string) => page.locator(".jobs-table-section tr").filter({
    has: page.getByRole("button", { name: title, exact: true }),
  });
  for (const job of final.tracked) {
    await keyword.fill(job.title);
    await expect(rowFor(job.title)).toContainText("等待AI分析", { timeout: 15000 });
  }
  const changed = Date.now();
  checkpoint("after");
  // Keep this page open: no reload, refresh button, or API route mocking.
  await expect(rowFor(final.tracked[1].title)).toHaveAttribute("data-review-status", "recommended", { timeout: 20000 });
  await expect(rowFor(final.tracked[1].title)).not.toContainText("等待AI分析");
  const automaticUpdateMs = Date.now() - changed;
  await expect(queue).toContainText("岗位判断：等待 92 个");
  await expect(queue).toContainText("任职条件补全：等待 142 个");
  await queue.scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(directory, `queue-${info.project.name}.png`) });
  const records = [];
  for (const [index, job] of final.tracked.entries()) {
    await keyword.fill(job.title);
    const row = rowFor(job.title);
    await expect(row).toHaveAttribute("data-review-status", "recommended");
    await expect(row).not.toContainText("等待AI分析");
    await row.getByRole("button", { name: job.title, exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "岗位详情" });
    await expect(dialog.locator(".jobs-jd-text").last()).toContainText("2027");
    await expect(dialog.getByRole("link", { name: "打开原始页面 ↗", exact: true })).toHaveAttribute("href", job.source_url);
    const evidence = dialog.getByLabel("筛选依据");
    for (const decision of Object.values(job.decisions)) {
      await expect(evidence).toContainText(decision.evidence[0]);
    }
    const hints = dialog.getByLabel("个人门槛提示");
    await expect(hints).not.toContainText("适用于「方向三");
    await expect(hints).not.toContainText("成员大多来自国内外名校");
    if (index === 0) await expect(evidence).toContainText("开放状态未知");
    await page.screenshot({ path: resolve(directory, `job-${index + 1}-${info.project.name}.png`) });
    records.push({ id: job.id, title: job.title, recommended: true, evidence_visible: true, full_body_visible: true });
    await page.getByRole("button", { name: "关闭岗位详情" }).click();
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  expect(errors).toEqual([]);
  writeFileSync(resolve(directory, `receipt-${info.project.name}.json`), JSON.stringify({
    mode: "recorded real AI results replayed through actual database/API/UI", passed: true,
    automatic_update_ms: automaticUpdateMs, no_manual_refresh: true,
    separate_queues: true, no_horizontal_overflow: true, records, errors,
  }, null, 2));
});
