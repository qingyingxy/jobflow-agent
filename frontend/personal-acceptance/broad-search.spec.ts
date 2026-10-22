import { expect, test } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

test("real broad results support reading, saving, restoring and clear conflict filters", async ({ page }) => {
  const directory = resolve(process.env.JOBFLOW_PERSONAL_TRIAL || "../artifacts/broad-search-20261019");
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByLabel("当前求职目标")).toContainText("2027");
  const filter = page.getByRole("combobox", { name: "筛选结果", exact: true });
  await expect(filter.locator("option:checked")).toHaveText("推荐＋值得看看");
  await expect(page.locator('tr[data-review-status="recommended"]').first()).toBeVisible({ timeout: 20000 });
  await expect(page.locator('tr[data-review-status="pending"]').first()).toBeVisible();
  await expect(page.locator('tr[data-review-status="excluded"]')).toHaveCount(0);
  const table = page.locator(".jobs-table-filters");
  await table.scrollIntoViewIfNeeded();
  await page.screenshot({ path: resolve(directory, `broad-${test.info().project.name}.png`) });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBeTruthy();
  await filter.selectOption("pending");
  const title = await page.locator(".jobs-title").first().innerText();
  await page.locator(".jobs-title").first().click();
  const detail = page.getByRole("dialog", { name: "岗位详情" });
  await expect(detail).toBeVisible();
  await expect(detail.getByText("岗位原文", { exact: true })).toBeVisible();
  await expect(detail.locator(".jobs-jd-text").last()).not.toBeEmpty();
  await expect(detail.getByRole("link", { name: "打开原始页面 ↗", exact: true })).toHaveAttribute("href", /^https?:\/\//);
  const save = detail.getByRole("button", { name: "收藏岗位", exact: true });
  if (await save.count()) await save.click();
  await expect(detail.getByRole("status")).toHaveText("已保存");
  await page.screenshot({ path: resolve(directory, `detail-${test.info().project.name}.png`) });
  await page.getByRole("button", { name: "关闭岗位详情" }).click();
  await page.getByRole("combobox", { name: "范围", exact: true }).selectOption("saved");
  await page.reload();
  await expect(filter).toHaveValue("pending");
  await expect(page.getByRole("button", { name: title, exact: true })).toBeVisible();
  await page.getByRole("button", { name: title, exact: true }).click();
  await detail.getByRole("button", { name: "忽略岗位", exact: true }).click();
  await expect(detail.getByRole("status")).toHaveText("已忽略");
  await detail.getByRole("button", { name: "收藏岗位", exact: true }).click();
  await expect(detail.getByRole("status")).toHaveText("已保存");
  await page.getByRole("button", { name: "关闭岗位详情" }).click();
  await page.getByRole("combobox", { name: "范围", exact: true }).selectOption("current");
  await filter.selectOption("excluded");
  await expect(page.locator('tr[data-review-status="excluded"]').first()).toBeVisible();
  await page.getByRole("button", { name: "清除筛选", exact: true }).click();
  await expect(filter.locator("option:checked")).toHaveText("推荐＋值得看看");
  await expect(page.locator('tr[data-review-status="excluded"]')).toHaveCount(0);
  expect(errors).toEqual([]);
  const path = resolve(directory, "ui-checks.json");
  let previous = {};
  try { previous = JSON.parse(readFileSync(path, "utf8")); } catch { /* first viewport */ }
  writeFileSync(path, JSON.stringify({ ...previous, [test.info().project.name]: {
    default_broad: true, pending_readable: true, explicit_conflicts_hidden: true,
    save_persists: true, ignore_restore: true, no_horizontal_page_overflow: true, no_page_errors: true,
  } }, null, 2));
});
