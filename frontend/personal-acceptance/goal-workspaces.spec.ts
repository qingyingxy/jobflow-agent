import { expect, test } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";

const primaryId = "goal_510142e137774f3ea1f7";
const javaId = "goal_e34b3c1d59e84092ac86";
const api = "http://127.0.0.1:18021/api/discovery/goals";
const headers = { "X-User-ID": "local-user" };

test("independent goal cards retain results, filters and bookmarks; only explicit edits replace a target", async ({ page, request }, info) => {
  const directory = resolve(process.env.JOBFLOW_CONTINUOUS_TRIAL!);
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const initial = await (await request.get(api, { headers })).json();
  const original = initial.find((g: { id: string }) => g.id === primaryId);
  await page.goto("/");
  const cards = page.getByLabel("我的求职目标", { exact: true });
  const primary = cards.locator(`[data-goal-id="${primaryId}"]`);
  const java = cards.locator(`[data-goal-id="${javaId}"]`);
  await expect(primary).toBeVisible({ timeout: 30000 });
  await expect(java).toBeVisible();
  const query = page.getByRole("textbox", { name: "你想找什么", exact: true });
  const keyword = page.getByRole("textbox", { name: "公司 / 岗位", exact: true });
  const scope = page.getByRole("combobox", { name: "范围", exact: true });
  const filter = page.getByRole("combobox", { name: "筛选结果", exact: true });
  await primary.locator(".goal-card-open").click();
  await expect(page.getByLabel("当前求职目标")).toContainText("北京");
  await keyword.fill("Agent");
  await java.locator(".goal-card-open").click();
  await expect(page.getByLabel("当前求职目标")).toContainText("杭州");
  await expect(keyword).toHaveValue("");
  await keyword.fill("Java");
  await filter.selectOption("recommended");
  const title = "【2027校招】Java平台开发工程师";
  await expect(page.getByRole("button", { name: title, exact: true })).toBeVisible({ timeout: 30000 });
  await primary.locator(".goal-card-open").click();
  await expect(keyword).toHaveValue("Agent");
  await java.locator(".goal-card-open").click();
  await expect(keyword).toHaveValue("Java");
  await expect(filter).toHaveValue("recommended");
  await page.reload();
  await expect(java.locator(".goal-card-open")).toHaveAttribute("aria-pressed", "true", { timeout: 30000 });
  await expect(keyword).toHaveValue("Java");
  await expect(primary).toBeVisible();
  await page.getByRole("button", { name: title, exact: true }).click();
  const detail = page.getByRole("dialog", { name: "岗位详情" });
  await expect(detail.locator(".jobs-jd-text").last()).toContainText("Java");
  const save = detail.getByRole("button", { name: "收藏岗位", exact: true });
  if (await save.count()) await save.click();
  await expect(detail.getByRole("status")).toHaveText("已保存");
  await page.getByRole("button", { name: "关闭岗位详情" }).click();
  await primary.locator(".goal-card-open").click();
  await scope.selectOption("saved");
  await filter.selectOption("");
  await keyword.fill(title);
  await expect(page.getByRole("button", { name: title, exact: true })).toBeVisible({ timeout: 30000 });
  // Typing a different direction is a POST. The server can reuse the already
  // existing equivalent Java workspace, but the AI workspace must be untouched.
  await query.fill("杭州/深圳，2027届校招，Java后端开发");
  const created = page.waitForResponse(r => r.url() === api && r.request().method() === "POST");
  await page.getByRole("button", { name: "保存并筛选已有岗位", exact: true }).click();
  const javaGoal = await (await created).json();
  expect(javaGoal.id).toBe(javaId);
  expect(javaGoal.conditions.pending_conditions).toEqual([]);
  expect(javaGoal.conditions.keywords).toEqual(["java"]);
  const currentGoals = await (await request.get(api, { headers })).json();
  expect(currentGoals.find((g: { id: string }) => g.id === primaryId)).toMatchObject({
    input_text: original.input_text, version: original.version, conditions: original.conditions,
  });
  await expect(cards.locator(".goal-card")).toHaveCount(initial.length);
  // An explicit edit changes only this target. Restore the test preference so
  // both real target conditions remain available for the next viewport run.
  const versions: number[] = [];
  for (const preference of ["Kafka", ""]) {
    await java.getByRole("button", { name: "编辑此目标", exact: true }).click();
    await page.getByRole("textbox", { name: "优先关键词", exact: true }).fill(preference);
    const updated = page.waitForResponse(r => r.url() === `${api}/${javaId}` && r.request().method() === "PATCH");
    await page.getByRole("button", { name: "保存并筛选已有岗位", exact: true }).click();
    const goal = await (await updated).json();
    expect(goal.id).toBe(javaId);
    versions.push(goal.version);
  }
  expect(versions).toEqual([javaGoal.version + 1, javaGoal.version + 2]);
  const finalGoals = await (await request.get(api, { headers })).json();
  expect(finalGoals.find((g: { id: string }) => g.id === primaryId)).toMatchObject({
    version: original.version, conditions: original.conditions,
  });
  await expect(java).toContainText("推荐 3", { timeout: 30000 });
  await expect(primary).toContainText("推荐 98", { timeout: 30000 });
  await cards.evaluate(el => window.scrollTo({ top: window.scrollY + el.getBoundingClientRect().top - 90, behavior: "instant" }));
  await cards.screenshot({ path: resolve(directory, `workspace-${info.project.name}.png`) });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  expect(errors).toEqual([]);
  writeFileSync(resolve(directory, `workspace-${info.project.name}.json`), JSON.stringify({ passed: true,
    cards_visible: initial.length, default_save_method: "POST", original_goal_unchanged: true,
    independent_filters: true, global_bookmark_retained: true, explicit_edit_versions: versions,
    parser_pending_conditions: javaGoal.conditions.pending_conditions, errors,
  }, null, 2));
});
