import { expect, test } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

test("real saved library survives a later visit while search workers continue", async ({ browser }, info) => {
  const directory = resolve(process.env.JOBFLOW_CONTINUOUS_TRIAL || "../artifacts/continuous-use-20261019");
  const phase = process.env.JOBFLOW_VISIT_PHASE || "first";
  const statePath = resolve(directory, `browser-${info.project.name}.json`);
  const receiptPath = resolve(directory, `saved-${info.project.name}.json`);
  const context = await browser.newContext({ ...info.project.use,
    ...(phase === "return" ? { storageState: statePath } : {}) });
  const page = await context.newPage();
  const errors: string[] = [];
  const requests: { path: string; status: number; milliseconds: number }[] = [];
  const starts = new Map<object, number>();
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => starts.set(request, Date.now()));
  page.on("response", response => {
    const url = new URL(response.url());
    if (url.pathname.startsWith("/api/")) requests.push({ path: url.pathname,
      status: response.status(), milliseconds: Date.now() - (starts.get(response.request()) || Date.now()) });
  });
  const started = Date.now();
  await page.goto("http://localhost:3001/");
  await expect(page.getByLabel("当前求职目标")).toContainText("2027", { timeout: 30000 });
  const filter = page.getByRole("combobox", { name: "筛选结果", exact: true });
  const scope = page.getByRole("combobox", { name: "范围", exact: true });
  let title: string;
  let url: string;
  let receipt: { title: string; url: string };
  if (phase === "first") {
    await expect(filter.locator("option:checked")).toHaveText("推荐＋值得看看");
    await expect(page.locator('tr[data-review-status="excluded"]')).toHaveCount(0);
    const first = page.locator('tr[data-review-status="recommended"] .jobs-title').first();
    await expect(first).toBeVisible({ timeout: 30000 });
    title = await first.innerText();
    await first.click();
    const dialog = page.getByRole("dialog", { name: "岗位详情" });
    await expect(dialog.locator(".jobs-jd-text").last()).not.toBeEmpty();
    url = (await dialog.getByRole("link", { name: "打开原始页面 ↗", exact: true }).getAttribute("href"))!;
    const save = dialog.getByRole("button", { name: "收藏岗位", exact: true });
    if (await save.count()) await save.click();
    await expect(dialog.getByRole("status")).toHaveText("已保存");
    await page.getByRole("button", { name: "关闭岗位详情" }).click();
    await scope.selectOption("saved");
    await filter.selectOption("recommended");
    await page.reload();
    await expect(scope).toHaveValue("saved");
    await expect(filter).toHaveValue("recommended");
    await expect(page.getByRole("button", { name: title, exact: true }).first()).toBeVisible({ timeout: 30000 });
    receipt = { title, url };
    writeFileSync(receiptPath, JSON.stringify(receipt, null, 2));
    await context.storageState({ path: statePath });
  } else {
    receipt = JSON.parse(readFileSync(receiptPath, "utf8"));
    ({ title, url } = receipt);
    await expect(scope).toHaveValue("saved");
    await expect(filter).toHaveValue("recommended");
    await expect(page.getByRole("button", { name: title, exact: true }).first()).toBeVisible({ timeout: 30000 });
    await page.getByRole("button", { name: title, exact: true }).first().click();
    const dialog = page.getByRole("dialog", { name: "岗位详情" });
    await expect(dialog.getByRole("status")).toHaveText("已保存");
    await expect(dialog.getByRole("link", { name: "打开原始页面 ↗", exact: true })).toHaveAttribute("href", url);
    await dialog.getByRole("button", { name: "忽略岗位", exact: true }).click();
    await expect(dialog.getByRole("status")).toHaveText("已忽略");
    await dialog.getByRole("button", { name: "收藏岗位", exact: true }).click();
    await expect(dialog.getByRole("status")).toHaveText("已保存");
    await page.getByRole("button", { name: "关闭岗位详情" }).click();
    await scope.selectOption("current");
    await page.getByRole("button", { name: "清除筛选", exact: true }).click();
    await expect(filter.locator("option:checked")).toHaveText("推荐＋值得看看");
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  await page.locator(".jobs-table-filters").scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(directory, `${phase}-${info.project.name}.png`) });
  expect(errors).toEqual([]);
  expect(requests.filter(r => r.status >= 500)).toEqual([]);
  writeFileSync(resolve(directory, `ui-${phase}-${info.project.name}.json`), JSON.stringify({
    phase, viewport: info.project.name, passed: true, saved: receipt,
    elapsed_seconds: (Date.now() - started) / 1000, errors, requests,
    persisted_filters: true, saved_content_available: true, no_horizontal_overflow: true,
  }, null, 2));
  await context.close();
});
