import { expect, test } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const folder = resolve(process.env.JOBFLOW_CONTINUOUS_TRIAL!);
const primaryId = "goal_510142e137774f3ea1f7";
const phase = process.env.JOBFLOW_SWITCH_PHASE || "return";
const query = "杭州/深圳，2027届校招，Java后端开发";

test("continue an unfinished official source through its visible button", async ({ page, request }, info) => {
  test.skip(phase !== "continue");
  test.setTimeout(420000);
  await page.goto("/");
  await expect(page.getByLabel("当前求职目标")).toContainText("2027", { timeout: 30000 });
  const button = page.locator(".jobs-company-cell").getByRole("button", { name: "继续查找", exact: true }).first();
  await expect(button).toBeEnabled({ timeout: 30000 });
  const before = await button.locator("..").innerText();
  const dispatched = page.waitForResponse(r => r.url().endsWith(`/goals/${primaryId}/search`) && r.request().method() === "POST");
  await button.click();
  const response = await dispatched;
  expect(response.status()).toBe(202);
  const input = response.request().postDataJSON();
  expect(input.continue_company_id).toBeTruthy();
  const started = await response.json();
  let result = started;
  await expect.poll(async () => {
    const read = await request.get(`http://127.0.0.1:18021/api/discovery/runs/${started.id}`, { headers: { "X-User-ID": "local-user" } });
    expect(read.ok()).toBeTruthy();
    result = await read.json();
    return result.status;
  }, { timeout: 360000, intervals: [5000] }).not.toBe("RUNNING");
  writeFileSync(resolve(folder, "ui-continuation.json"), JSON.stringify({ input, before, result }, null, 2));
  expect(result.status).toBe("SUCCEEDED");
  await expect(page.getByRole("button", { name: "更新岗位", exact: true })).toBeEnabled({ timeout: 30000 });
  await page.screenshot({ path: resolve(folder, `continue-${info.project.name}.png`) });
});

test("create a different goal with natural language through the UI", async ({ page }) => {
  test.skip(phase !== "create");
  await page.goto("/");
  await expect(page.getByRole("button", { name: "新建目标", exact: true })).toBeEnabled({ timeout: 30000 });
  await page.getByRole("button", { name: "新建目标", exact: true }).click();
  await page.getByRole("textbox", { name: "你想找什么", exact: true }).fill(query);
  const saved = page.waitForResponse(r => r.url().endsWith("/api/discovery/goals") && r.request().method() === "POST");
  await page.getByRole("button", { name: "保存并筛选已有岗位", exact: true }).click();
  const response = await saved;
  expect(response.ok()).toBeTruthy();
  const goal = await response.json();
  writeFileSync(resolve(folder, "alternate-goal.json"), JSON.stringify(goal, null, 2));
  expect(goal.id).not.toBe(primaryId);
  expect(goal.conditions.locations.sort()).toEqual(["杭州", "深圳"]);
  expect(goal.conditions.graduation_years).toEqual([2027]);
  expect(goal.conditions.job_types).toEqual(["校招"]);
  expect(JSON.stringify(goal.conditions)).toMatch(/java/i);
  expect(JSON.stringify(goal.conditions)).toContain("后端");
  const current = page.getByLabel("当前求职目标");
  await expect(current).toContainText("杭州");
  await expect(current).toContainText("深圳");
  await expect(current).not.toContainText("ai agent");
  await page.screenshot({ path: resolve(folder, "new-goal-desktop.png") });
});

test("apply the exact selected wording after recording an ambiguous parser result", async ({ page }) => {
  test.skip(phase !== "exact-input");
  const previous = JSON.parse(readFileSync(resolve(folder, "alternate-goal.json"), "utf8"));
  await page.goto("/");
  const selector = page.getByRole("combobox", { name: "求职目标", exact: true });
  await expect(selector).toBeEnabled({ timeout: 30000 });
  await selector.selectOption(previous.id);
  await page.getByRole("textbox", { name: "你想找什么", exact: true }).fill("杭州/深圳，2027届校招，Java后端");
  const saved = page.waitForResponse(r => r.url().endsWith(`/goals/${previous.id}`) && r.request().method() === "PATCH");
  await page.getByRole("button", { name: "保存并筛选已有岗位", exact: true }).click();
  const response = await saved;
  expect(response.ok()).toBeTruthy();
  const goal = await response.json();
  writeFileSync(resolve(folder, "alternate-goal.json"), JSON.stringify(goal, null, 2));
  expect(goal.conditions.pending_conditions).toEqual([]);
  expect(goal.conditions.keywords).toContain("java");
  expect(goal.conditions.roles).toContain("后端");
  await expect(page.getByLabel("当前求职目标")).not.toContainText("意图待核实");
});

test("switch targets, inspect current evidence, preserve bookmarks, and return later", async ({ page }, info) => {
  test.skip(phase !== "return");
  const alternate = JSON.parse(readFileSync(resolve(folder, "alternate-goal.json"), "utf8"));
  const bookmark = JSON.parse(readFileSync(resolve(folder, `../primary/saved-${info.project.name}.json`), "utf8"));
  const errors: string[] = [];
  const views: object[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  const goals = page.getByRole("combobox", { name: "求职目标", exact: true });
  await expect(goals).toBeEnabled({ timeout: 30000 });
  const current = page.getByLabel("当前求职目标");
  const keyword = page.getByRole("textbox", { name: "公司 / 岗位", exact: true });
  const scope = page.getByRole("combobox", { name: "范围", exact: true });
  const filter = page.getByRole("combobox", { name: "筛选结果", exact: true });
  for (const [goalId, city] of [[primaryId, "北京"], [alternate.id, "杭州"], [primaryId, "北京"], [alternate.id, "杭州"]]) {
    const loaded = page.waitForResponse(r => r.url().includes(`/goals/${goalId}/library?`) && r.ok());
    await goals.selectOption(goalId);
    await expect(current).toContainText(city);
    const library = await (await loaded).json();
    await expect(page.locator(".jobs-table-count")).toBeVisible({ timeout: 30000 });
    views.push({ goal_id: goalId, counts: library.counts, conditions_visible: await current.innerText(),
      recommended: library.result_matches.filter((m: { review_status: string }) => m.review_status === "recommended").map((m: { job_posting_id: string }) => m.job_posting_id) });
  }
  // The first goal's saved job stays in the global bookmark view after switching.
  await scope.selectOption("saved");
  await filter.selectOption("");
  await keyword.fill(bookmark.title);
  await expect(page.getByRole("button", { name: bookmark.title, exact: true }).first()).toBeVisible({ timeout: 30000 });
  await page.reload();
  await expect(goals).toHaveValue(alternate.id, { timeout: 30000 });
  await expect(scope).toHaveValue("saved");
  await expect(page.getByRole("button", { name: bookmark.title, exact: true }).first()).toBeVisible({ timeout: 30000 });
  await page.getByRole("button", { name: bookmark.title, exact: true }).first().click();
  const detail = page.getByRole("dialog", { name: "岗位详情" });
  await expect(detail.getByRole("status")).toHaveText("已保存");
  await expect(detail.getByRole("link", { name: "打开原始页面 ↗", exact: true })).toHaveAttribute("href", bookmark.url);
  await expect(detail.locator(".jobs-jd-text").last()).not.toBeEmpty();
  await page.getByRole("button", { name: "关闭岗位详情" }).click();
  await scope.selectOption("current");
  await keyword.fill("");
  await filter.selectOption("");
  const recommended = page.locator('tr[data-review-status="recommended"] .jobs-title').first();
  // This trial has two confirmed recommendations. Wait for the goal library
  // after reload instead of silently skipping inspection while it is loading.
  await expect(recommended).toBeVisible({ timeout: 30000 });
  let inspected: object | null = null;
  if (await recommended.count()) {
    const title = await recommended.innerText();
    await recommended.click();
    const evidence = detail.getByLabel("筛选依据");
    await expect(evidence).not.toBeEmpty();
    await expect(detail.locator(".jobs-jd-text").last()).not.toBeEmpty();
    inspected = { title, evidence: await evidence.innerText() };
    await page.screenshot({ path: resolve(folder, `alternate-detail-${info.project.name}.png`) });
    await page.getByRole("button", { name: "关闭岗位详情" }).click();
  }
  await page.locator(".jobs-table-filters").scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(folder, `switch-${info.project.name}.png`) });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  expect(errors).toEqual([]);
  writeFileSync(resolve(folder, `switch-${info.project.name}.json`), JSON.stringify({
    passed: true, views, inspected, saved_job_retained: true, active_goal_retained: true, errors,
  }, null, 2));
});
