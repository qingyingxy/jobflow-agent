import { expect, test, type Page } from "@playwright/test";

const input = "27届，想找后端校招，最好上海，其他城市也可以。不做销售，工资最好20k以上。";
const initialConditions = {
  locations: [], preferred_locations: ["上海"], excluded_locations: [],
  roles: ["后端"], preferred_roles: [], excluded_roles: ["销售"],
  job_types: ["校招"], excluded_job_types: [], graduation_years: [2027],
  keywords: [], preferred_keywords: [], pending_conditions: ["工资最好20k以上"],
};

async function fixture(page: Page, { saved = true, failure = "" } = {}) {
  let goal: Record<string, any> | null = saved ? makeGoal(initialConditions) : null;
  const calls = { interpret: 0, writes: [] as any[], searches: [] as any[] };
  function makeGoal(conditions: typeof initialConditions, text = input, version = 1) {
    return { id: "intent", name: "后端校招", input_text: text, query: text, version,
      conditions, condition_sources: {}, company_ids: null };
  }
  const run = { id: "run", source: "web_search", source_url: "https://example.com", search_query: input,
    search_goal_id: "intent", search_goal_version: 1, status: "SUCCEEDED", max_results: 20,
    discovered_count: 0, new_count: 0, duplicate_count: 0, analysis_target_count: 0,
    analysis_completed_count: 0, analysis_failure_count: 0, analysis_status: "NOT_REQUESTED",
    search_plan: null, agent_trace: [], result_matches: [], failure_summary: null,
    started_at: "2026-10-21T02:00:00Z", finished_at: "2026-10-21T02:00:01Z", created_at: "2026-10-21T02:00:00Z" };
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const req = route.request(), path = new URL(req.url()).pathname, method = req.method();
    const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id", "access-control-allow-methods": "GET,POST,PATCH,OPTIONS" };
    if (method === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (path === "/api/profile") return route.fulfill({ headers, status: 404, json: {} });
    if (path === "/api/discovery/goals/interpret") {
      calls.interpret++;
      return route.fulfill({ headers, json: { conditions: initialConditions, condition_sources: {}, notice: null } });
    }
    if (path === "/api/discovery/goals/intent/search") {
      calls.searches.push(req.postDataJSON());
      return route.fulfill({ headers, status: 202, json: run });
    }
    if ((path === "/api/discovery/goals" && method === "POST") || (path === "/api/discovery/goals/intent" && method === "PATCH")) {
      const body = req.postDataJSON();
      calls.writes.push(body);
      if (failure) return route.fulfill({ headers, status: 422, json: { error: { message: failure } } });
      goal = makeGoal(body.conditions || initialConditions, body.input_text, goal ? goal.version + 1 : 1);
      return route.fulfill({ headers, status: 201, json: goal });
    }
    if (path === "/api/discovery/goals") return route.fulfill({ headers, json: goal ? [goal] : [] });
    if (path.endsWith("/library")) return route.fulfill({ headers, json: {
      goal_id: "intent", goal_version: goal?.version || 1, query: goal?.query,
      lead_ids: [], result_matches: [], counts: {}, updates: [], latest_run_id: null,
    } });
    if (path === "/api/discovery/runs/run") return route.fulfill({ headers, json: run });
    return route.fulfill({ headers, json: [] });
  });
  return calls;
}

test("summary separates execution scope, preferences, exclusions and pending requirements", async ({ page }, testInfo) => {
  const calls = await fixture(page);
  await page.goto("/");
  const summary = page.getByLabel("当前求职目标");
  await expect(summary).toContainText("后端 · 2027届 · 校招 · 地点不限");
  await expect(summary).toContainText("优先：上海");
  await expect(summary).toContainText("排除：销售");
  await expect(summary).toContainText("待确认：工资最好20k以上");
  await expect(page.getByLabel("求职需求", { exact: true })).toHaveValue(input);
  await page.screenshot({ path: `../artifacts/search-intent-20261021/conditions-${testInfo.project.name}.png`, fullPage: true });
  await page.getByRole("button", { name: "修改条件", exact: true }).click();
  await expect(page.getByLabel("必须地点", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("优先地点", { exact: true })).toHaveValue("上海");
  await page.getByLabel("必须地点", { exact: true }).fill("北京、上海");
  await page.getByRole("button", { name: "保存条件", exact: true }).click();
  await expect(summary).toContainText("地点：北京、上海");
  await expect(summary).not.toContainText("地点不限");
  expect(calls.writes[0].conditions.locations).toEqual(["北京", "上海"]);
  expect(calls.writes[0].conditions.preferred_locations).toEqual(["上海"]);
  expect(calls.interpret).toBe(0);
  await page.reload();
  await expect(summary).toContainText("地点：北京、上海");
  await expect(summary).toContainText("优先：上海");
  expect(calls.interpret).toBe(0);
  await page.getByRole("button", { name: "修改条件", exact: true }).click();
  await page.screenshot({ path: `../artifacts/search-intent-20261021/editor-${testInfo.project.name}.png`, fullPage: true });
});

test("a new request saves and searches without a separate interpretation or confirmation step", async ({ page }) => {
  const calls = await fixture(page, { saved: false });
  await page.goto("/");
  await page.getByLabel("求职需求", { exact: true }).fill(input);
  await page.getByRole("button", { name: "查找岗位", exact: true }).click();
  await expect.poll(() => calls.searches.length).toBe(1);
  expect(calls.writes).toHaveLength(1);
  expect(calls.writes[0].conditions).toBeNull();
  expect(calls.writes[0].input_text).toBe(input);
  expect(calls.searches[0].expected_version).toBe(1);
  expect(calls.interpret).toBe(0);
  await expect(page.getByLabel("修改搜索条件")).toHaveCount(0);
  await expect(page.getByLabel("当前求职目标")).toContainText("优先：上海");
});

for (const failure of ["这些要求存在冲突，请修改后再搜索：只考虑上海，上海不要", "暂时未能理解这段需求，已保留原文。请重试，或点击“修改条件”填写搜索条件。"]) {
  test(`invalid or unavailable interpretation never dispatches search: ${failure.slice(0, 8)}`, async ({ page }) => {
    const calls = await fixture(page, { saved: false, failure });
    await page.goto("/");
    await page.getByLabel("求职需求", { exact: true }).fill(input);
    await page.getByRole("button", { name: "查找岗位", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: failure })).toBeVisible();
    expect(calls.searches).toEqual([]);
    await expect(page.getByLabel("求职需求", { exact: true })).toHaveValue(input);
    await expect(page.getByRole("button", { name: "修改条件", exact: true })).toBeEnabled();
  });
}
