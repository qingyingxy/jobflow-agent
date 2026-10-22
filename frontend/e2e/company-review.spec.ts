import { expect, test } from "@playwright/test";

test("manual review is available without a saved goal and persists with distinct provenance", async ({ page }, testInfo) => {
  let source = { id: "pending", company: "新星科技", homepage_url: "https://nova.example/", career_url: "https://nova.example/old",
    status: "pending", reason: "旧入口未找到官方链接", attempts: 1, review_revision: "a".repeat(64), verification_method: null as string | null };
  const writes: Record<string, unknown>[] = [];
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id", "access-control-allow-methods": "GET,POST,OPTIONS" };
    if (request.method() === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (path === "/api/profile") return route.fulfill({ headers, status: 404, json: {} });
    if (path === "/api/discovery/companies") return route.fulfill({ headers, json: [source] });
    if (path === "/api/discovery/companies/pending/confirm") {
      const body = request.postDataJSON(); writes.push(body);
      source = { ...source, homepage_url: body.homepage_url, career_url: body.career_url,
        status: "manually_confirmed", verification_method: "manual", reason: "用户已人工确认入口，已加入后续分批查询", review_revision: "b".repeat(64) };
      return route.fulfill({ headers, json: source });
    }
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  const panel = page.getByLabel("新公司发现");
  await panel.locator("summary").first().click();
  const card = page.getByRole("article", { name: "新星科技公司入口" });
  await card.getByRole("button", { name: "确认或修改入口" }).click();
  const submit = card.getByRole("button", { name: "确认并加入公司库" });
  await expect(submit).toBeDisabled();
  await card.getByRole("checkbox").check();
  await card.getByLabel("招聘入口", { exact: true }).fill("https://app.mokahr.com/campus-recruitment/nova/100");
  await expect(card.getByRole("checkbox")).not.toBeChecked();
  await expect(submit).toBeDisabled();
  await card.getByRole("checkbox").check();
  await card.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("company-review.png"), fullPage: true });
  await submit.click();
  await expect(card.getByText("人工确认 · 已加入公司库", { exact: true })).toBeVisible();
  expect(writes).toEqual([{ homepage_url: "https://nova.example/", career_url: "https://app.mokahr.com/campus-recruitment/nova/100", confirmed: true, expected_revision: "a".repeat(64) }]);
  await page.reload();
  await panel.locator("summary").first().click();
  await expect(card.getByText("人工确认 · 已加入公司库", { exact: true })).toBeVisible();
  await expect(card.getByText("官方入口已核验 · 已加入公司库", { exact: true })).toHaveCount(0);
  await expect(card.getByRole("link", { name: "招聘入口 ↗", exact: true })).toHaveAttribute("href", "https://app.mokahr.com/campus-recruitment/nova/100");
});

test("a stale candidate remains pending and shows the review error", async ({ page }) => {
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id", "access-control-allow-methods": "GET,POST,OPTIONS" };
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (path === "/api/profile") return route.fulfill({ headers, status: 404, json: {} });
    if (path.endsWith("/confirm")) return route.fulfill({ headers, status: 409, json: { detail: "候选已更新，请刷新后重新查看并确认" } });
    if (path === "/api/discovery/companies") return route.fulfill({ headers, json: [{ id: "pending", company: "待核公司", homepage_url: "https://nova.example/", career_url: "https://nova.example/jobs", status: "pending", reason: "入口待核实", attempts: 1, review_revision: "a".repeat(64) }] });
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  const panel = page.getByLabel("新公司发现");
  await panel.locator("summary").first().click();
  await panel.getByRole("button", { name: "确认或修改入口" }).click();
  await panel.getByRole("checkbox").check();
  await panel.getByRole("button", { name: "确认并加入公司库" }).click();
  await expect(panel.getByRole("alert")).toHaveText("候选已更新，请刷新后重新查看并确认");
  await expect(panel.getByText("待核实 · 尚未加入查询队列", { exact: true })).toBeVisible();
});
