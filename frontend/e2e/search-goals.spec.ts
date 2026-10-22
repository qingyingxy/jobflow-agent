import { expect, test, type Page } from "@playwright/test";

async function installUpdateFixture(page: Page, version = 1) {
  const goal = { id: "goal", name: "上海后端校招", input_text: "上海后端校招", query: "上海后端校招", version,
    conditions: { locations: ["上海"], preferred_locations: [], excluded_locations: [], roles: ["后端"], excluded_roles: [],
      job_types: ["校招"], excluded_job_types: [], graduation_years: [], keywords: [], preferred_keywords: [], pending_conditions: [] },
    condition_sources: {}, company_ids: null };
  const run = { id: "run", source: "web_search", source_url: "https://example.com/search", search_query: goal.query,
    search_goal_id: goal.id, search_goal_version: version, status: "SUCCEEDED", max_results: 20,
    discovered_count: 1, new_count: 1, duplicate_count: 0, analysis_target_count: 0, analysis_completed_count: 0,
    analysis_failure_count: 0, analysis_status: "NOT_REQUESTED", search_plan: null, agent_trace: [],
    result_matches: [{ job_posting_id: "new", match_tier: "strict", filter_status: "matched", preference_score: 0,
      mismatch_reasons: [], mismatch_labels: [], checks: [] }], failure_summary: null,
    started_at: "2026-10-12T02:00:00Z", finished_at: "2026-10-12T02:00:01Z", created_at: "2026-10-12T02:00:00Z" };
  const calls: { bodies: Record<string, unknown>[]; schedules: number[] } = { bodies: [], schedules: [] };
  let interval = 0;
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id", "access-control-allow-methods": "GET,POST,PUT,PATCH,OPTIONS" };
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (path === "/api/profile") return route.fulfill({ headers, status: 404, json: {} });
    if (path === "/api/discovery/goals/goal/schedule") {
      interval = route.request().postDataJSON().interval_minutes;
      calls.schedules.push(interval);
      return route.fulfill({ headers, json: { ...goal, update_interval_minutes: interval, next_update_at: interval ? "2026-10-16T12:00:00Z" : null } });
    }
    if (path === "/api/discovery/goals") return route.fulfill({ headers, json: [{ ...goal, update_interval_minutes: interval }] });
    if (path === "/api/discovery/goals/goal/search") {
      calls.bodies.push(route.request().postDataJSON());
      return route.fulfill({ headers, status: 202, json: run });
    }
    if (path === "/api/discovery/runs/run") return route.fulfill({ headers, json: run });
    if (path === "/api/discovery/runs") return route.fulfill({ headers, json: calls.bodies.length ? [run]
      : version > 1 ? [{ ...run, id: "old-run", search_goal_version: 1,
        agent_trace: [{ phase: "search", tool: "multiround_search", outcome: "SUCCEEDED", observation: "旧条件进度", decision: "旧条件决策", source_id: null, company: null, url: null }] }] : [] });
    if (path.endsWith("/library")) return route.fulfill({ headers, json: { goal_id: goal.id, goal_version: version,
      query: goal.query, lead_ids: [], latest_run_id: calls.bodies.length ? run.id : null,
      result_matches: [run.result_matches[0], { ...run.result_matches[0], job_posting_id: "pending", filter_status: "pending" },
        { ...run.result_matches[0], job_posting_id: "closed", filter_status: "excluded", mismatch_reasons: ["closed"] }],
      counts: { matched: 1, pending: 1, excluded: 1, closed: 1 },
      updates: calls.bodies.length ? [{ kind: "new", job_posting_id: "new", title: "新岗位", company: "测试公司" }] : [] } });
    return route.fulfill({ headers, json: [] });
  });
  return calls;
}

test("condition editor preserves multi-city typing and current text overrides an old draft", async ({ page }) => {
  const conditions = { locations: ["上海"], preferred_locations: [], excluded_locations: [], roles: ["后端"], excluded_roles: [],
    job_types: ["校招"], excluded_job_types: [], graduation_years: [2027], keywords: [], pending_conditions: [] };
  let saved: Record<string, unknown> | null = null;
  let lastWrite: Record<string, unknown> = {};
  let interpretations = 0;
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id", "access-control-allow-methods": "GET,POST,PUT,PATCH,OPTIONS" };
    if (method === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (path === "/api/profile") return route.fulfill({ headers, status: 404, json: {} });
    if (path === "/api/discovery/goals/interpret") {
      interpretations++;
      return route.fulfill({ headers, json: { conditions, condition_sources: {}, notice: null } });
    }
    if ((path === "/api/discovery/goals" && method === "POST") || method === "PATCH") {
      lastWrite = route.request().postDataJSON();
      saved = { id: "goal", name: "我的目标", input_text: lastWrite.input_text, query: lastWrite.input_text,
        conditions: lastWrite.conditions || { ...conditions, locations: ["昆明"] }, condition_sources: {}, version: saved ? 2 : 1, company_ids: null };
      return route.fulfill({ headers, status: 201, json: saved });
    }
    if (path === "/api/discovery/goals") return route.fulfill({ headers, json: saved ? [saved] : [] });
    if (path === "/api/discovery/goals/goal/library") return route.fulfill({ headers,
      json: { goal_id: "goal", goal_version: saved?.version || 1, query: saved?.query, result_matches: [], lead_ids: [], latest_run_id: null, counts: {}, updates: [] } });
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  await expect(page.getByLabel("求职需求")).toHaveValue("");
  await page.getByLabel("求职需求").fill("2027届上海后端校招");
  await page.getByRole("button", { name: "修改条件", exact: true }).click();
  const locations = page.getByLabel("必须地点", { exact: true });
  await locations.fill("");
  await locations.pressSequentially("上海、深圳、湛江");
  await expect(locations).toHaveValue("上海、深圳、湛江");
  await page.locator(".search-more > summary").click();
  await page.getByRole("button", { name: "保存并筛选已有岗位", exact: true }).click();
  await page.locator(".search-more > summary").click();
  await expect(page.getByLabel("当前求职目标")).toContainText("地点：上海、深圳、湛江");
  expect((lastWrite.conditions as typeof conditions).locations).toEqual(["上海", "深圳", "湛江"]);
  await page.getByRole("button", { name: "修改条件", exact: true }).click();
  await expect(locations).toHaveValue("上海、深圳、湛江");
  expect(interpretations).toBe(1);
  await page.getByLabel("求职需求").fill("2027届昆明后端校招");
  await page.locator(".search-more > summary").click();
  await page.getByRole("button", { name: "保存并筛选已有岗位", exact: true }).click();
  await page.locator(".search-more > summary").click();
  await expect(page.getByLabel("当前求职目标")).toContainText("地点：昆明");
  expect(lastWrite.conditions).toBeNull();
});

test("saved jobs remain visible when the active target excludes their city", async ({ page }) => {
  const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id" };
  const goal = { id: "goal", name: "上海校招", input_text: "上海后端校招", query: "上海后端校招", version: 1,
    conditions: { locations: ["上海"], preferred_locations: [], excluded_locations: [], roles: ["后端"], excluded_roles: [], job_types: ["校招"], excluded_job_types: [], graduation_years: [], keywords: [], pending_conditions: [] }, condition_sources: {}, company_ids: null };
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (path === "/api/profile") return route.fulfill({ headers, status: 404, json: {} });
    if (path === "/api/discovery/goals") return route.fulfill({ headers, json: [goal] });
    if (path === "/api/candidates") return route.fulfill({ headers, json: [{ id: "saved", job_posting_id: "saved", status: "SAVED", available_transitions: ["IGNORED"],
      job: { id: "saved", title: "北京收藏岗位", company: "收藏公司", locations: ["北京"], job_type: "campus", source_url: "https://example.com/jobs/saved" }, analysis: null }] });
    if (path.endsWith("/library")) return route.fulfill({ headers, json: { goal_id: "goal", goal_version: 1, query: goal.query, lead_ids: [], updates: [], counts: { excluded: 1 },
      result_matches: [{ job_posting_id: "saved", filter_status: "excluded", preference_score: 0, mismatch_labels: ["地点不匹配"], mismatch_reasons: ["location"], checks: [] }], latest_run_id: null } });
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  await expect(page.getByLabel("当前求职目标")).toBeVisible();
  await expect(page.getByRole("button", { name: "北京收藏岗位", exact: true })).toHaveCount(0);
  await page.locator(".result-options > summary").click();
  await page.getByRole("combobox", { name: "岗位范围", exact: true }).selectOption("saved");
  await expect(page.getByRole("button", { name: "北京收藏岗位", exact: true })).toBeVisible();
});

test("automatic update is persisted by the server and never dispatched by a browser timer", async ({ page }) => {
  const calls = await installUpdateFixture(page);
  await page.clock.install();
  await page.goto("/");
  await expect(page.getByLabel("当前求职目标")).toBeVisible();
  await page.locator(".search-more > summary").click();
  await page.getByLabel("定期更新", { exact: true }).selectOption("30");
  await expect.poll(() => calls.schedules).toEqual([30]);
  await expect(page.getByLabel("定期更新", { exact: true })).toBeEnabled();
  await page.reload();
  await page.locator(".search-more > summary").click();
  await expect(page.getByLabel("定期更新", { exact: true })).toHaveValue("30");
  await page.clock.fastForward(60 * 60_000);
  expect(calls.bodies).toEqual([]);
  await page.getByLabel("定期更新", { exact: true }).selectOption("0");
  await expect.poll(() => calls.schedules).toEqual([30, 0]);
  await page.reload();
  await page.locator(".search-more > summary").click();
  await expect(page.getByLabel("定期更新", { exact: true })).toHaveValue("0");
  expect(calls.bodies).toEqual([]);
});

test("library totals and current search statistics do not use an older goal version", async ({ page }) => {
  await installUpdateFixture(page, 2);
  await page.goto("/");
  await expect(page.getByText("条件已更新，尚未按当前条件搜索。", { exact: false })).toBeVisible();
  await expect(page.getByLabel("本轮搜索统计")).toHaveCount(0);
  await expect(page.locator(".discovery-message").filter({ hasText: "旧条件决策" })).toHaveCount(0);
  await expect(page.getByLabel("岗位库统计")).toContainText("已核验 3 个岗位");
  await expect(page.getByLabel("岗位库统计")).toContainText("其中 1 个已关闭");
  await expect(page.getByText(/最近一轮更新：新增/)).toHaveCount(0);
  await page.getByRole("button", { name: "查找岗位", exact: true }).click();
  await expect(page.getByLabel("本轮搜索统计")).toContainText("1 个岗位正文已核验");
  await expect(page.getByLabel("岗位库统计")).toContainText("已核验 3 个岗位");
  await page.getByRole("button", { name: "搜索详情", exact: true }).click();
  await expect(page.getByText("最近一轮更新：新增 1 · 变更 0 · 关闭 0", { exact: true })).toBeVisible();
});
