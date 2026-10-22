import { expect, test } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const directory = resolve(process.env.JOBFLOW_CONTINUOUS_TRIAL!);
const replay = JSON.parse(readFileSync(resolve(directory, "replay.json"), "utf8"));
const api = "http://127.0.0.1:18021/api";
const headers = { "X-User-ID": "local-user" };

test("real saved jobs distinguish incomplete reads, waiting analysis, source omissions and personal conflicts", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  const goal = replay.goals[0];
  const cards = page.getByLabel("我的求职目标", { exact: true });
  await cards.locator(`[data-goal-id="${goal.id}"] .goal-card-open`).click();
  const filter = page.getByRole("combobox", { name: "筛选结果", exact: true });
  await filter.selectOption("");
  const keyword = page.getByRole("textbox", { name: "公司 / 岗位", exact: true });
  for (const sample of goal.samples) {
    await keyword.fill(sample.title);
    const title = page.getByRole("button", { name: sample.title, exact: true }).first();
    await expect(title).toBeVisible({ timeout: 30000 });
    const row = title.locator("xpath=ancestor::tr");
    const stages = row.getByLabel("岗位判断进度");
    await expect(stages).toContainText(sample.result_status.personal.label);
    if (sample.value === "reading_required") {
      await expect(stages).toContainText("读取未完成");
      await expect(stages).not.toContainText("原文未说明");
      await expect(row).toHaveAttribute("data-review-status", "pending");
    } else if (sample.value === "waiting") {
      await expect(stages).toContainText("等待分析");
      await expect(stages).not.toContainText("原文未说明");
    } else {
      await expect(stages).toContainText(sample.result_status.search.label);
    }
    await title.click();
    const dialog = page.getByRole("dialog", { name: "岗位详情" });
    await expect(dialog.getByLabel("岗位判断进度")).toContainText(sample.result_status.personal.label);
    await expect(dialog.getByLabel("岗位判断进度")).toContainText("未提取到门槛也不代表已通过");
    if (sample.value === "conflict") {
      await expect(dialog.getByLabel("个人门槛提示")).toContainText("明确门槛冲突");
      await dialog.screenshot({ path: resolve(directory, `personal-conflict-${info.project.name}.png`) });
    }
    await page.getByRole("button", { name: "关闭岗位详情" }).click();
  }
  await keyword.fill("Agent Harness");
  await page.locator(".jobs-table-section").evaluate(el => el.scrollIntoView({ behavior: "instant" }));
  await page.screenshot({ path: resolve(directory, `status-${info.project.name}.png`), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  expect(errors).toEqual([]);
  writeFileSync(resolve(directory, `status-${info.project.name}.json`), JSON.stringify({ passed: true,
    samples: goal.samples.map((s: { stage: string; value: string }) => `${s.stage}:${s.value}`), errors }, null, 2));
});

test("dedup retains two goals and a bookmark through target switches and reload", async ({ page, request }, info) => {
  await page.goto("/");
  const cards = page.getByLabel("我的求职目标", { exact: true });
  await expect(cards.locator(".goal-card")).toHaveCount(2, { timeout: 30000 });
  const javaGoal = replay.goals[1];
  await cards.locator(`[data-goal-id="${javaGoal.id}"] .goal-card-open`).click();
  await page.getByRole("combobox", { name: "筛选结果", exact: true }).selectOption("recommended");
  const keyword = page.getByRole("textbox", { name: "公司 / 岗位", exact: true });
  const title = "【2027校招】Java平台开发工程师";
  await keyword.fill(title);
  await page.getByRole("button", { name: title, exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "岗位详情" });
  const save = dialog.getByRole("button", { name: "收藏岗位", exact: true });
  if (await save.count()) await save.click();
  await expect(dialog.getByRole("status")).toHaveText("已保存");
  await page.getByRole("button", { name: "关闭岗位详情" }).click();
  await cards.locator(`[data-goal-id="${replay.goals[0].id}"] .goal-card-open`).click();
  await page.getByRole("combobox", { name: "范围", exact: true }).selectOption("saved");
  await page.getByRole("combobox", { name: "筛选结果", exact: true }).selectOption("");
  await keyword.fill(title);
  await expect(page.getByRole("button", { name: title, exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("button", { name: title, exact: true })).toBeVisible({ timeout: 30000 });
  const candidates = await (await request.get(`${api}/candidates`, { headers })).json();
  expect(candidates).toHaveLength(replay.unique_jobs);
  const normalized = candidates.filter((c: { job: { source_url: string } }) => c.job.source_url?.includes("199907720043"));
  expect(normalized).toHaveLength(1);
  writeFileSync(resolve(directory, `bookmark-${info.project.name}.json`), JSON.stringify({ passed: true,
    unique_jobs: candidates.length, alias_count: normalized.length, bookmark_retained: true }, null, 2));
});
