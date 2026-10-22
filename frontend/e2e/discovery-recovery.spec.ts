import { expect, test, type Page } from "@playwright/test";

test.use({ timezoneId: "Asia/Shanghai", locale: "zh-CN" });

const headers = {
  "access-control-allow-origin": "http://localhost:3000",
  "access-control-allow-headers": "content-type,x-user-id",
  "access-control-allow-methods": "GET,POST,PUT,PATCH,OPTIONS",
};
const goals = ["北京", "上海"].map((city, i) => ({
  id: `goal-${i}`, name: `${city} Agent 校招`, input_text: `${city} Agent 校招`, query: `${city} Agent 校招`, version: 1,
  conditions: { locations: [city], roles: ["agent"], preferred_locations: [], preferred_roles: [],
    excluded_locations: [], excluded_roles: [], job_types: ["校招"], excluded_job_types: [],
    graduation_years: [2027], keywords: [], preferred_keywords: [], pending_conditions: [] },
  condition_sources: {}, company_ids: null,
  next_update_at: "2026-10-16T09:30:00", update_interval_minutes: 30,
}));
const candidates = goals.map((goal, i) => ({
  id: `candidate-${i}`, job_posting_id: `job-${i}`, status: "DISCOVERED", available_transitions: ["SAVED", "IGNORED"],
  job: { id: `job-${i}`, title: `${goal.conditions.locations[0]} Agent 工程师`, company: "示例公司",
    locations: goal.conditions.locations, job_type: "campus", source_url: `https://example.com/jobs/${i}`,
    availability_status: "ACTIVE", last_verified_at: "2026-10-16T09:30:00" },
}));

function deferred() {
  let release!: () => void;
  const promise = new Promise<void>(resolve => { release = resolve; });
  return { promise, release };
}

async function fixture(page: Page) {
  const state = { failures: new Set<string>(), waits: new Map<string, Promise<void>>(),
    reads: new Map<string, number>(), timestamp: "2026-10-16T09:30:00" };
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers, status: 200 });
    state.reads.set(path, (state.reads.get(path) || 0) + 1);
    const fail = state.failures.has(path);
    const wait = state.waits.get(path);
    let body: unknown = [];
    if (path === "/api/profile") body = { degree: "本科", major: "计算机科学", graduation_year: 2027 };
    if (path === "/api/resumes/versions") body = [{ id: "resume" }];
    if (path === "/api/evidence") body = [{ id: "evidence", type: "project" }];
    if (path === "/api/discovery/goals") body = goals.map(goal => ({ ...goal, next_update_at: state.timestamp }));
    if (path === "/api/candidates") body = candidates.map(candidate => ({ ...candidate,
      job: { ...candidate.job, last_verified_at: state.timestamp } }));
    const goalIndex = goals.findIndex(goal => path === `/api/discovery/goals/${goal.id}/library`);
    if (goalIndex >= 0) body = {
      goal_id: goals[goalIndex].id, goal_version: 1, query: goals[goalIndex].query, lead_ids: [], latest_run_id: null,
      result_matches: candidates.map((candidate, i) => ({ job_posting_id: candidate.job_posting_id,
        filter_status: i === goalIndex ? "matched" : "excluded", match_tier: "strict", preference_score: 0,
        mismatch_reasons: i === goalIndex ? [] : ["location"], mismatch_labels: [], checks: [] })),
      counts: { matched: 1, excluded: 1 }, updates: [],
    };
    if (wait) await wait;
    if (fail) return route.fulfill({ headers, status: 503, json: { detail: "测试连接中断" } });
    return route.fulfill({ headers, json: body });
  });
  return state;
}

const goalSelect = (page: Page) => page.getByRole("combobox", { name: "求职目标", exact: true });
const jobRows = (page: Page) => page.locator(".jobs-unified-table tbody tr .jobs-title");

test("running search survives connection failures and reload without hiding saved jobs or restarting", async ({ page }) => {
  await fixture(page);
  let polls = 0;
  let finish = false;
  let starts = 0;
  const run = { id: "live-run", search_goal_id: "goal-0", search_goal_version: 1, search_query: goals[0].query,
    source: "web_search", source_url: "https://example.com", status: "RUNNING", discovered_count: 1,
    result_matches: [{ job_posting_id: "job-0", filter_status: "matched", review_status: "recommended", checks: [], mismatch_labels: [], mismatch_reasons: [] }],
    agent_trace: [], started_at: new Date().toISOString(), finished_at: null, created_at: new Date().toISOString(),
    new_count: 0, duplicate_count: 1, analysis_status: "NOT_REQUESTED", analysis_target_count: 0, analysis_completed_count: 0 };
  await page.route("**/api/discovery/runs*", route => route.fulfill({ headers, json: [run] }));
  await page.route("**/api/discovery/runs/live-run?*", route => {
    polls++;
    return polls <= 2 ? route.fulfill({ headers, status: 503, json: { detail: "temporary" } })
      : route.fulfill({ headers, json: { ...run, status: finish ? "SUCCEEDED" : "RUNNING" } });
  });
  await page.route("**/api/discovery/goals/*/search", route => { starts++; return route.fulfill({ headers, status: 202, json: run }); });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "搜索中…", exact: false })).toBeDisabled();
  await expect(jobRows(page)).toHaveText(["北京 Agent 工程师"]);
  const progress = page.getByLabel("本轮搜索统计");
  await expect(progress).toContainText("1 个岗位可优先查看");
  await expect(progress).toContainText("自动重连", { timeout: 12000 });
  await expect(jobRows(page)).toHaveText(["北京 Agent 工程师"]);
  await expect.poll(() => polls, { timeout: 20000 }).toBeGreaterThanOrEqual(3);
  await expect(progress).not.toContainText("自动重连");
  await page.reload();
  await expect(page.getByRole("button", { name: "搜索中…", exact: false })).toBeDisabled();
  await expect(jobRows(page)).toHaveText(["北京 Agent 工程师"]);
  await page.screenshot({ path: `../artifacts/personal-flow-20261019/search-${test.info().project.name}.png`, fullPage: true });
  finish = true;
  await expect(progress).toContainText("本轮已完成");
  await expect(page.getByRole("button", { name: "更新岗位", exact: true })).toBeEnabled();
  expect(starts).toBe(0);
});

test("one retry restores jobs, saved goals and the profile after initial connection failure", async ({ page }) => {
  const state = await fixture(page);
  ["/api/candidates", "/api/discovery/goals", "/api/profile"].forEach(path => state.failures.add(path));
  await page.goto("/");
  await expect(page.locator(".profile-status-trigger")).toContainText("个人资料状态暂不可用");
  await expect(goalSelect(page)).toContainText("求职目标读取失败");
  await expect(page.getByRole("button", { name: "搜索并筛选", exact: true })).toBeDisabled();
  state.failures.clear();
  await page.getByRole("button", { name: "重试 ↗", exact: true }).click();
  await expect(goalSelect(page)).toHaveValue("goal-0");
  await expect(page.getByLabel("你想找什么")).toHaveValue("北京 Agent 校招");
  await expect(jobRows(page)).toHaveText(["北京 Agent 工程师"]);
  await expect(page.locator(".profile-status-trigger")).toContainText("简历与经历已载入");
  await expect(page.locator(".discovery-error")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "重新连接", exact: true })).toHaveCount(0);
});

test("an independent section failure keeps successful data and retained data survives failed refresh", async ({ page }) => {
  const state = await fixture(page);
  state.failures.add("/api/discovery/leads");
  await page.goto("/");
  await expect(jobRows(page)).toHaveText(["北京 Agent 工程师"]);
  await expect(page.locator(".discovery-error")).toContainText("岗位线索读取失败");
  state.failures.clear();
  await page.getByRole("button", { name: "重试 ↗", exact: true }).click();
  await expect(page.locator(".discovery-error")).toHaveCount(0);
  ["/api/candidates", "/api/discovery/goals", "/api/discovery/goals/goal-0/library"].forEach(path => state.failures.add(path));
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(page.getByRole("button", { name: "重新连接", exact: true })).toBeVisible();
  await expect(page.locator(".discovery-error")).toBeVisible();
  await expect(goalSelect(page)).toHaveValue("goal-0");
  await expect(jobRows(page)).toHaveText(["北京 Agent 工程师"]);
  await expect(page.getByLabel("岗位库统计")).toContainText("1 个优先查看");
  state.failures.clear();
  await page.getByRole("button", { name: "重新连接", exact: true }).click();
  await expect(page.locator(".discovery-error")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "重新连接", exact: true })).toHaveCount(0);
});

test("retry retains a new draft typed during initial failure and still recovers saved choices", async ({ page }) => {
  const state = await fixture(page);
  state.failures.add("/api/discovery/goals");
  await page.goto("/");
  await expect(page.getByRole("button", { name: "重新连接", exact: true })).toBeVisible();
  await page.getByLabel("你想找什么").fill("北京上海 RAG 校招");
  state.failures.clear();
  await page.getByRole("button", { name: "重新连接", exact: true }).click();
  await expect(goalSelect(page)).toBeEnabled();
  await expect(goalSelect(page).locator("option")).toHaveCount(3);
  await expect(page.getByLabel("你想找什么")).toHaveValue("北京上海 RAG 校招");
  await expect(goalSelect(page)).toHaveValue("");
});

test("refresh retains unsaved condition edits", async ({ page }) => {
  await fixture(page);
  await page.goto("/");
  await expect(goalSelect(page)).toHaveValue("goal-0");
  await page.getByRole("button", { name: "整理 / 修改条件", exact: true }).click();
  await page.getByLabel("必须地点", { exact: true }).fill("北京、上海");
  const recovered = page.waitForResponse(response => response.url().endsWith("/api/discovery/goals"));
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await recovered;
  await expect(page.getByRole("button", { name: "刷新", exact: true })).toBeEnabled();
  await expect(page.getByLabel("必须地点", { exact: true })).toHaveValue("北京、上海");
  await expect(page.getByText("条件尚未应用；下方仍按已保存目标筛选。")).toBeVisible();
});

test("a late goal list cannot reset a newly selected goal", async ({ page }) => {
  const state = await fixture(page);
  await page.goto("/");
  await expect(jobRows(page)).toHaveText(["北京 Agent 工程师"]);
  const gate = deferred();
  const listPath = "/api/discovery/goals";
  const listReads = state.reads.get(listPath) || 0;
  state.waits.set(listPath, gate.promise);
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect.poll(() => state.reads.get(listPath)).toBeGreaterThan(listReads);
  await goalSelect(page).selectOption("goal-1");
  await expect(jobRows(page)).toHaveText(["上海 Agent 工程师"]);
  const response = page.waitForResponse(response => response.url().endsWith(listPath));
  gate.release();
  await response;
  await expect(page.getByRole("button", { name: "刷新", exact: true })).toBeEnabled();
  await expect(goalSelect(page)).toHaveValue("goal-1");
  await expect(page.getByLabel("你想找什么")).toHaveValue("上海 Agent 校招");
  await expect(jobRows(page)).toHaveText(["上海 Agent 工程师"]);
});

test("a late library response cannot replace the new goal's jobs", async ({ page }) => {
  const state = await fixture(page);
  const gate = deferred();
  const libraryPath = "/api/discovery/goals/goal-0/library";
  state.waits.set(libraryPath, gate.promise);
  await page.goto("/");
  await expect(goalSelect(page)).toHaveValue("goal-0");
  await expect.poll(() => state.reads.get(libraryPath) || 0).toBeGreaterThan(0);
  await goalSelect(page).selectOption("goal-1");
  await expect(jobRows(page)).toHaveText(["上海 Agent 工程师"]);
  await expect(page.getByLabel("岗位库统计")).toBeVisible();
  const response = page.waitForResponse(response => response.url().endsWith(libraryPath));
  gate.release();
  await response;
  await expect(goalSelect(page)).toHaveValue("goal-1");
  await expect(jobRows(page)).toHaveText(["上海 Agent 工程师"]);
});

test("Shanghai displays legacy naive UTC and explicit timezone timestamps consistently", async ({ page }) => {
  const state = await fixture(page);
  await page.goto("/");
  const verified = page.locator('td[data-label="最近核验"]');
  await expect(verified).toHaveText(/17:30/);
  await expect(page.getByText(/下次更新：/)).toContainText("17:30");
  for (const timestamp of ["2026-10-16T09:30:00Z", "2026-10-16T17:30:00+08:00"]) {
    state.timestamp = timestamp;
    await page.reload();
    await expect(verified).toHaveText(/17:30/);
    await expect(page.getByText(/下次更新：/)).toContainText("17:30");
  }
});
