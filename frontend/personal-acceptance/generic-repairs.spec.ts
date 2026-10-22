import { expect, test } from "@playwright/test";
import { resolve } from "node:path";

const folder = resolve(process.env.JOBFLOW_CONTINUOUS_TRIAL!);

test("saved view waits for saved leads as well as verified candidates", async ({ page }) => {
  let release!: () => void;
  let entered!: () => void;
  const held = new Promise<void>(resolve => { release = resolve; });
  const started = new Promise<void>(resolve => { entered = resolve; });
  await page.route("**/api/discovery/leads", async route => {
    const response = await route.fetch();
    entered();
    await held;
    await route.fulfill({ response });
  });
  await page.goto("/");
  await started;
  await page.getByRole("combobox", { name: "范围", exact: true }).selectOption("saved");
  await expect(page.getByText("正在读取已保存的岗位和收藏…", { exact: true })).toBeVisible();
  await expect(page.locator(".jobs-no-results,.jobs-table-count")).toHaveCount(0);
  release();
  await expect(page.locator(".jobs-table-count")).toBeVisible({ timeout: 15000 });
});

test("slow library shows loading, saved rows survive stale refresh and filters", async ({ page }, info) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  let releaseLibrary!: () => void;
  let libraryEntered!: () => void;
  const libraryHeld = new Promise<void>(resolve => { releaseLibrary = resolve; });
  const libraryStarted = new Promise<void>(resolve => { libraryEntered = resolve; });
  await page.route("**/api/discovery/goals/*/library?*", async route => {
    const response = await route.fetch();
    libraryEntered();
    await libraryHeld;
    await route.fulfill({ response });
  });
  await page.goto("/");
  await libraryStarted;
  await expect(page.getByText("正在读取已保存的岗位和收藏…", { exact: true })).toBeVisible();
  await expect(page.getByText("正在查找具体职位，已发现的链接会陆续显示。", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /搜索中/ })).toHaveCount(0);
  await expect(page.locator(".jobs-no-results,.jobs-table-count")).toHaveCount(0);
  releaseLibrary();
  await expect(page.locator(".jobs-table-count")).toBeVisible({ timeout: 15000 });
  await page.unroute("**/api/discovery/goals/*/library?*");
  const row = page.locator(".jobs-table-section tr").filter({ has: page.getByRole("button", { name: "保存", exact: true }) }).first();
  await expect(row).toBeVisible();
  const title = await row.locator(".jobs-title").innerText();
  let releaseCandidates!: () => void;
  let candidateEntered!: () => void;
  const candidateHeld = new Promise<void>(resolve => { releaseCandidates = resolve; });
  const candidateStarted = new Promise<void>(resolve => { candidateEntered = resolve; });
  await page.route("**/api/candidates", async route => {
    const response = await route.fetch();
    candidateEntered();
    await candidateHeld;
    await route.fulfill({ response });
  });
  await page.getByRole("button", { name: "刷新", exact: true }).first().click();
  await candidateStarted;
  const saved = page.waitForResponse(r => r.url().includes("/status") && r.request().method() === "PATCH");
  await row.getByRole("button", { name: "保存", exact: true }).click();
  expect((await saved).ok()).toBeTruthy();
  releaseCandidates();
  await expect(page.getByRole("button", { name: "刷新", exact: true }).first()).toBeEnabled();
  const scope = page.getByRole("combobox", { name: "范围", exact: true });
  await scope.selectOption("saved");
  const keyword = page.getByRole("textbox", { name: "公司 / 岗位", exact: true });
  await keyword.fill(title);
  await expect(page.getByRole("button", { name: title, exact: true }).first()).toBeVisible();
  await keyword.fill("不存在的筛选条件-acceptance");
  await expect(page.getByText(/个收藏被当前筛选隐藏/)).toBeVisible();
  await page.getByRole("button", { name: "清除收藏夹筛选", exact: true }).click();
  await expect(scope).toHaveValue("saved");
  await keyword.fill(title);
  await page.unroute("**/api/candidates");
  await page.reload();
  await expect(scope).toHaveValue("saved");
  await expect(page.getByRole("button", { name: title, exact: true }).first()).toBeVisible({ timeout: 15000 });
  await expect(page.getByRole("button", { name: "刷新", exact: true }).first()).toBeEnabled({ timeout: 15000 });
  expect(errors).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  await page.locator(".jobs-table-scroll").scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(folder, `saved-${info.project.name}.png`) });
});

test("failed initial library does not claim the saved collection is empty", async ({ page }) => {
  await page.route("**/api/discovery/goals/*/library?*", route => route.fulfill({ status: 503, json: { detail: "验收模拟读取失败" } }));
  await page.goto("/");
  await expect(page.getByText("岗位读取失败，请点击刷新重试。已保存的收藏不会因此删除。", { exact: true })).toBeVisible({ timeout: 15000 });
  await expect(page.locator(".jobs-no-results,.jobs-table-count")).toHaveCount(0);
  await page.unroute("**/api/discovery/goals/*/library?*");
  await page.getByRole("button", { name: "刷新", exact: true }).first().click();
  await expect(page.locator(".jobs-table-count")).toBeVisible({ timeout: 15000 });
});

test("failed save rolls back its optimistic state", async ({ page }) => {
  await page.goto("/");
  const row = page.locator(".jobs-table-section tr").filter({ has: page.getByRole("button", { name: "保存", exact: true }) }).first();
  await expect(row).toBeVisible({ timeout: 15000 });
  const title = await row.locator(".jobs-title").innerText();
  await page.route("**/api/candidates/*/status", route => route.fulfill({ status: 503, json: { detail: "验收模拟保存失败" } }));
  await row.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByText("收藏状态更新失败，请重试。", { exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "范围", exact: true }).selectOption("saved");
  await page.getByRole("textbox", { name: "公司 / 岗位", exact: true }).fill(title);
  await expect(page.getByRole("button", { name: title, exact: true })).toHaveCount(0);
});
