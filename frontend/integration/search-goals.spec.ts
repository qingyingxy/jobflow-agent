import { expect, test } from "@playwright/test";

const api = "http://127.0.0.1:18021";
const headers = { "X-User-ID": "local-user" };

test("saved goal searches once, reuses the library, and editable preferences survive reload", async ({ page, request }, testInfo) => {
  let searchCalls = 0;
  let analysisCalls = 0;
  page.on("request", r => {
    if (/\/goals\/[^/]+\/search$/.test(r.url()) && r.method() === "POST") searchCalls++;
    if (r.url().endsWith("/analyze")) analysisCalls++;
  });
  await page.goto("/");
  await page.getByRole("button", { name: "新建目标", exact: true }).click();
  await page.getByLabel("你想找什么").fill("2027届上海优先的Python后端校招");
  const started = page.waitForResponse(r => /\/goals\/[^/]+\/search$/.test(r.url()) && r.request().method() === "POST");
  await page.getByRole("button", { name: "搜索并筛选", exact: true }).click();
  const run = await (await started).json();
  expect(run.goal_conditions.preferred_locations).toEqual(["上海"]);
  expect(run.goal_conditions.locations).toEqual([]);
  await expect.poll(async () => (await (await request.get(`${api}/api/discovery/runs/${run.id}`, { headers })).json()).status,
    { timeout: 30_000 }).not.toBe("RUNNING");
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await page.getByRole("button", { name: "全部展开", exact: true }).click();
  await expect(page.getByRole("button", { name: "Python 开发工程师（北京）", exact: true })).toBeVisible();
  await expect(page.getByLabel("当前求职目标")).toContainText("优先地点：上海");

  // Applying structured fields updates existing results without another search.
  await page.getByRole("button", { name: "编辑此目标", exact: true }).click();
  await page.getByLabel("必须地点", { exact: true }).fill("上海");
  await page.getByLabel("优先地点", { exact: true }).fill("");
  await page.getByLabel("排除地点", { exact: true }).fill("北京");
  await expect(page.getByText("修改仅应用于当前目标；下方仍为已保存结果。", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Python 开发工程师（北京）", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "保存并筛选已有岗位", exact: true }).click();
  await expect(page.getByLabel("当前求职目标")).toContainText("必须地点：上海");
  await expect(page.getByRole("button", { name: "Python 开发工程师（北京）", exact: true })).toHaveCount(0);
  await expect(page.getByText("条件已更新，尚未按当前条件搜索。", { exact: false })).toBeVisible();
  await expect(page.getByLabel("本轮搜索统计")).toHaveCount(0);
  const library = await (await request.get(`${api}/api/discovery/goals/${run.search_goal_id}/library`, { headers })).json();
  expect(library.latest_run_id).toBeNull();
  expect(library.updates).toEqual([]);
  expect(searchCalls).toBe(1);
  expect(analysisCalls).toBe(0);

  const goals = await (await request.get(`${api}/api/discovery/goals`, { headers })).json();
  const goal = goals.find((g: { id: string }) => g.id === run.search_goal_id);
  expect(goal.version).toBe(2);
  await page.reload();
  await expect(page.getByLabel("当前求职目标")).toContainText("条件版本 2");
  await expect(page.getByLabel("当前求职目标")).toContainText("排除地点：北京");
  await expect(page.getByLabel("本轮搜索统计")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Python 开发工程师（上海）", exact: true })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath("saved-goal-library.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByLabel("当前求职目标")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath("saved-goal-library-mobile.png"), fullPage: true });
});
