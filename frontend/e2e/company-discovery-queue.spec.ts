import { expect, test } from "@playwright/test";

test("company discovery runs independently and retained progress survives reload", async ({ page }) => {
  let starts = 0, searches = 0;
  const goal = { id: "company-queue", version: 3, query: "北京 上海 Agent RAG AI产品 校招", input_text: "个人目标", name: "个人目标", conditions: {}, condition_sources: {}, company_ids: null };
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id", "access-control-allow-methods": "GET,POST,OPTIONS" };
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (path.endsWith("/discover")) {
      starts++;
      expect(route.request().postDataJSON()).toEqual({ expected_version: 3 });
      return route.fulfill({ headers, status: 202, json: {} });
    }
    if (path.endsWith("/search")) searches++;
    if (path === "/api/discovery/goals") return route.fulfill({ headers, json: [goal] });
    if (path === "/api/profile") return route.fulfill({ headers, status: 404, json: {} });
    if (path.endsWith("/library")) return route.fulfill({ headers, json: {
      goal_id: goal.id, goal_version: 3, query: goal.query, result_matches: [], lead_ids: [], updates: [], counts: {},
      company_discovery_queue: { status: starts ? "queued" : "idle", stage: starts ? "extract" : "search", enabled: true,
        queries_completed: starts ? 1 : 0, queries_total: 3, links_saved: starts ? 33 : 0, companies_pending: 0, companies_verified: 0, next_run_at: "2026-10-19T05:14:10Z" },
    } });
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  const progress = page.getByLabel("公司发现进度");
  await progress.getByRole("button", { name: "发现更多公司", exact: true }).click();
  await expect(progress).toContainText("已保存线索 33 条");
  await expect(progress).toContainText("从来源提取公司");
  await expect(progress).toContainText("下次自动续接");
  await expect(progress.getByRole("button", { name: "发现更多公司", exact: true })).toBeDisabled();
  await page.reload();
  await expect(progress).toContainText("已保存线索 33 条");
  await expect(progress).toContainText("已处理查询 1/3");
  expect(starts).toBe(1);
  expect(searches).toBe(0);
});
