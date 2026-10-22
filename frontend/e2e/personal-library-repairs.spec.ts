import { expect, test } from "@playwright/test";

test("details save persists, filters survive reload, and personal gates stay visible without horizontal scrolling", async ({ page }) => {
  let status = "DISCOVERED";
  const goal = { id: "repairs", version: 1, query: "上海Agent校招", input_text: "上海Agent校招", name: "个人目标", conditions: {}, condition_sources: {}, company_ids: null };
  const candidate = () => ({ id: "c", user_id: "local-user", job_posting_id: "j", status,
    available_transitions: status === "SAVED" ? ["IGNORED"] : ["SAVED", "IGNORED"],
    job: { id: "j", company: "验收公司", title: "Agent算法工程师", source_url: "https://example.com/position/1/detail", locations: ["上海"], job_type: "campus" }, analysis: null });
  const match = { job_posting_id: "j", filter_status: "matched", review_status: "recommended", checks: [], mismatch_labels: [], mismatch_reasons: [],
    personal_requirements: [{ category: "degree", status: "attention", label: "学历要求", reason: "原文要求博士，当前资料最高学历为硕士；投递前需核对", evidence: "计算机相关专业，博士研究生学历。" }] };
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id", "access-control-allow-methods": "GET,POST,PATCH,OPTIONS" };
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (path === "/api/candidates/c/status") { status = route.request().postDataJSON().status; return route.fulfill({ headers, json: candidate() }); }
    if (path === "/api/candidates") return route.fulfill({ headers, json: [candidate()] });
    if (path === "/api/discovery/goals") return route.fulfill({ headers, json: [goal] });
    if (path.endsWith("/library")) return route.fulfill({ headers, json: { goal_id: goal.id, goal_version: 1, query: goal.query, result_matches: [match], lead_ids: ["alias"], updates: [], counts: { excluded: 0, closed: 0 } } });
    if (path === "/api/discovery/leads") return route.fulfill({ headers, json: [{ id: "alias", job_posting_id: null, title_hint: "重复推广链接", discovery_kind: "job", status: "DEFERRED", source_url: "https://example.com/position/1/detail?spread=campaign", normalized_url: "https://example.com/position/1/detail" }] });
    if (path === "/api/jobs/j") return route.fulfill({ headers, json: { raw_content: "岗位职责：开发Agent。任职要求：博士研究生学历。" } });
    if (path === "/api/profile" || path.endsWith("/analysis")) return route.fulfill({ headers, status: 404, json: {} });
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Agent算法工程师", exact: true })).toBeVisible();
  await expect(page.getByText("学历要求需核对", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "重复推广链接", exact: true })).toHaveCount(0);
  expect(await page.locator(".jobs-table-scroll").evaluate(e => e.scrollWidth <= e.clientWidth + 1)).toBeTruthy();
  await page.getByRole("button", { name: "Agent算法工程师", exact: true }).click();
  const detail = page.getByRole("dialog", { name: "岗位详情" });
  await expect(detail).toContainText("原文要求博士，当前资料最高学历为硕士");
  await detail.getByRole("button", { name: "收藏岗位", exact: true }).click();
  await expect(detail.getByRole("status")).toHaveText("已保存");
  await expect(detail.getByRole("button", { name: "收藏岗位", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "关闭岗位详情" }).click();
  await page.getByRole("combobox", { name: "岗位范围", exact: true }).selectOption("saved");
  await page.getByRole("combobox", { name: "筛选结果", exact: true }).selectOption("recommended");
  await page.reload();
  await expect(page.getByRole("combobox", { name: "岗位范围", exact: true })).toHaveValue("saved");
  await expect(page.getByRole("combobox", { name: "筛选结果", exact: true })).toHaveValue("recommended");
  await expect(page.getByRole("button", { name: "Agent算法工程师", exact: true })).toBeVisible();
});

test("slow library refresh remains visible and does not stack polling requests", async ({ page }) => {
  await page.clock.install();
  let requests = 0;
  let release!: () => void;
  const delayed = new Promise<void>(resolve => { release = resolve; });
  const goal = { id: "slow", version: 1, query: "上海Agent校招", input_text: "上海Agent校招", name: "个人目标", conditions: {}, condition_sources: {} };
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id" };
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (path === "/api/profile") return route.fulfill({ headers, status: 404, json: {} });
    if (path === "/api/discovery/goals") return route.fulfill({ headers, json: [goal] });
    if (path.endsWith("/library")) {
      const request = ++requests;
      if (request > 1) await delayed;
      return route.fulfill({ headers, json: { goal_id: "slow", goal_version: 1, query: goal.query,
        result_matches: [], lead_ids: [], updates: [], counts: {},
        review_queue: { status: request === 1 ? "running" : "completed", enabled: true,
          remaining: request === 1 ? 2 : 0, waiting: request === 1 ? 2 : 0,
          processed: request === 1 ? 0 : 2, completed: request === 1 ? 0 : 2, cooldown: 0, blocked: 0 } } });
    }
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  await expect(page.getByLabel("正文复核进度")).toContainText("已完成理解 0 个");
  const initial = requests;
  await page.clock.fastForward(4000);
  await expect.poll(() => requests).toBe(initial + 1);
  await page.clock.fastForward(8000);
  expect(requests).toBe(initial + 1);
  release();
  await expect(page.getByLabel("正文复核进度")).toContainText("已完成理解 2 个");
});

test("saved body review starts without another web search and shows persisted progress", async ({ page }) => {
  let reviews = 0, searches = 0;
  const goal = { id: "queue", version: 2, query: "上海Agent校招", input_text: "上海Agent校招", name: "个人目标", conditions: {}, condition_sources: {}, company_ids: null };
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id", "access-control-allow-methods": "GET,POST,OPTIONS" };
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (path.endsWith("/review")) { reviews++; expect(route.request().postDataJSON()).toEqual({ expected_version: 2 }); return route.fulfill({ headers, status: 202, json: {} }); }
    if (path.endsWith("/search")) searches++;
    if (path === "/api/discovery/goals") return route.fulfill({ headers, json: [goal] });
    if (path === "/api/profile") return route.fulfill({ headers, status: 404, json: {} });
    if (path.endsWith("/library")) return route.fulfill({ headers, json: { goal_id: goal.id, goal_version: 2, query: goal.query, result_matches: [], lead_ids: [], updates: [], counts: {},
      review_queue: { status: reviews ? "completed" : "idle", enabled: true, waiting: reviews ? 0 : 2, remaining: reviews ? 0 : 2, completed: reviews ? 2 : 0, processed: reviews ? 2 : 0, cooldown: 0, blocked: 0 } } });
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "复核已有正文", exact: true }).click();
  await expect(page.getByLabel("正文复核进度")).toContainText("已完成理解 2 个");
  expect(reviews).toBe(1); expect(searches).toBe(0);
});
