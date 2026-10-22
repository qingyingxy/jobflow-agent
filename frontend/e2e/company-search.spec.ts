import { expect, test } from "@playwright/test";

test("local pagination and company continuation use separate actions", async ({ page }) => {
  const goal = { id: "goal", name: "北京上海 Agent 校招", input_text: "北京上海 Agent 校招", query: "北京上海 Agent 校招", version: 1,
    conditions: { locations: ["北京", "上海"], roles: ["agent"], preferred_locations: [], preferred_roles: [], excluded_locations: [], excluded_roles: [], job_types: ["校招"], excluded_job_types: [], graduation_years: [2027], keywords: [], preferred_keywords: [], pending_conditions: [] },
    condition_sources: {}, company_ids: ["bytedance"] };
  const matches = Array.from({ length: 35 }, (_, i) => ({ job_posting_id: `job-${i}`, filter_status: "matched", match_tier: "strict", mismatch_reasons: [], mismatch_labels: [], checks: [] }));
  const candidates = matches.map((match, i) => ({ id: `candidate-${i}`, job_posting_id: match.job_posting_id, status: "DISCOVERED", available_transitions: ["SAVED", "IGNORED"],
    job: { id: match.job_posting_id, title: `Agent 开发岗位 ${i + 1}`, company: "字节跳动", locations: ["北京"], job_type: "campus", source_url: `https://jobs.bytedance.com/campus/position/${i}/detail`, availability_status: "ACTIVE", last_verified_at: "2026-10-16T09:00:00Z" } }));
  const run = { id: "run", source: "web_search", source_url: "https://example.com", search_query: goal.query, search_goal_id: "goal", search_goal_version: 1,
    status: "SUCCEEDED", max_results: 20, discovered_count: 3, new_count: 3, duplicate_count: 0, analysis_target_count: 0, analysis_completed_count: 0, analysis_failure_count: 0,
    analysis_status: "NOT_REQUESTED", search_plan: null, agent_trace: [], result_matches: matches.slice(0, 3), failure_summary: null,
    started_at: "2026-10-16T09:00:00Z", finished_at: "2026-10-16T09:00:10Z", created_at: "2026-10-16T09:00:00Z" };
  const writes: unknown[] = [];
  const reads: string[] = [];
  let started = false;
  let detailPolls = 0;
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname;
    const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id", "access-control-allow-methods": "GET,POST,OPTIONS" };
    if (request.method() === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (request.method() === "GET") reads.push(path + url.search);
    if (path === "/api/profile") return route.fulfill({ headers, status: 404, json: {} });
    if (path === "/api/discovery/goals") return route.fulfill({ headers, json: [goal] });
    if (path.endsWith("/library")) return route.fulfill({ headers, json: { goal_id: "goal", goal_version: 1, query: goal.query, lead_ids: [], latest_run_id: "run", result_matches: matches, updates: [], counts: { matched: 35 },
      company_progress: [{ source_id: "bytedance", company: "字节跳动", official_url: "https://jobs.bytedance.com/campus/", status: "paused", matched_count: started ? 6 : 3, checked_count: started ? 6 : 3, pages_checked: 1, can_continue: true }] } });
    if (path === "/api/candidates") return route.fulfill({ headers, json: candidates });
    if (path === "/api/discovery/runs") return route.fulfill({ headers, json: [run] });
    if (path === "/api/discovery/goals/goal/search") {
      writes.push(request.postDataJSON()); started = true;
      return route.fulfill({ headers, status: 202, json: { ...run, status: "RUNNING" } });
    }
    if (path === "/api/discovery/runs/run") { detailPolls++; return route.fulfill({ headers, json: run }); }
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  const rows = page.locator('.job-list tbody tr .job-title');
  await expect(rows).toHaveCount(30);
  await page.getByRole("button", { name: "显示更多岗位（还有 5 个）", exact: true }).click();
  await expect(rows).toHaveCount(35);
  expect(writes).toEqual([]);
  await page.getByLabel("搜索操作").getByRole("button", { name: "继续查找", exact: true }).click();
  await expect(page.locator('.company-continue')).toContainText('官网尚未查完');
  const fullHistoryReads = reads.filter(url => url.startsWith('/api/discovery/runs?')).length;
  await page.locator('.company-continue').getByRole('button', { name: '继续查找', exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toEqual({ expected_version: 1, continue_company_id: 'bytedance' });
  await expect.poll(() => detailPolls).toBeGreaterThan(0);
  await expect.poll(() => reads.some(url => url === '/api/candidates?discovery_run_id=run')).toBe(true);
  expect(reads.filter(url => url.startsWith('/api/discovery/runs?')).length).toBe(fullHistoryReads);
  await expect(page.locator('.company-continue').getByRole('button', { name: '继续查找', exact: true })).toBeEnabled();
  await page.reload();
  await expect(rows).toHaveCount(30);
  await expect(page.getByLabel("搜索操作").getByRole("button", { name: "继续查找", exact: true })).toBeVisible();
});

test("coverage separates next batch from a company's partial supplementary search", async ({ page }) => {
  const goal = { id: "coverage", name: "上海 Agent 校招", input_text: "上海 Agent 校招", query: "上海 Agent 校招", version: 1,
    conditions: { locations: ["上海"], roles: ["agent"], preferred_locations: [], excluded_locations: [], excluded_roles: [],
      job_types: ["校招"], excluded_job_types: [], graduation_years: [2027], keywords: [], pending_conditions: [] },
    condition_sources: {}, company_ids: null };
  const run = { id: "coverage-run", source: "web_search", source_url: "https://example.com", search_query: goal.query,
    search_goal_id: goal.id, search_goal_version: 1, status: "SUCCEEDED", max_results: 20, discovered_count: 0,
    new_count: 0, duplicate_count: 0, analysis_status: "NOT_REQUESTED", result_matches: [], agent_trace: [],
    started_at: "2026-10-17T02:00:00Z", finished_at: "2026-10-17T02:00:10Z", created_at: "2026-10-17T02:00:00Z" };
  const writes: Record<string, unknown>[] = [];
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id", "access-control-allow-methods": "GET,POST,OPTIONS" };
    if (request.method() === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (path === "/api/profile") return route.fulfill({ headers, status: 404, json: {} });
    if (path === "/api/discovery/goals") return route.fulfill({ headers, json: [goal] });
    if (path.endsWith("/library")) return route.fulfill({ headers, json: {
      goal_id: goal.id, goal_version: 1, query: goal.query, lead_ids: [], result_matches: [], counts: {}, updates: [], latest_run_id: null,
      company_progress: [
        { source_id: "alibaba", company: "阿里巴巴", official_url: "https://campus-talent.alibaba.com/", status: "paused",
          strategy: "web_search", search_attempts: writes.length + 1, matched_count: 0, checked_count: 0, pages_checked: 0, can_continue: true },
        { source_id: "baidu", company: "百度", official_url: "https://talent.baidu.com/", status: "not_checked",
          matched_count: 0, checked_count: 0, pages_checked: 0, can_continue: false },
      ],
    } });
    if (path === "/api/discovery/goals/coverage/search") {
      writes.push(request.postDataJSON());
      return route.fulfill({ headers, status: 202, json: run });
    }
    if (path === "/api/discovery/runs/coverage-run") return route.fulfill({ headers, json: run });
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "搜索详情", exact: true }).click();
  const progress = page.getByLabel("官网查询进度");
  await expect(progress.locator("summary")).toHaveText("官网查询进度 · 共 2 家 · 1 家已尝试 · 1 家待查询");
  await progress.locator("summary").click();
  await expect(progress.getByText("已补搜，官网未查全", { exact: true })).toBeVisible();
  await expect(progress.getByText("尚未查询", { exact: true })).toBeVisible();
  await expect(progress.getByText(/已检查 0 页/)).toHaveCount(0);
  await progress.getByRole("button", { name: "继续扩大搜索", exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toEqual({ expected_version: 1 });
  await expect(progress.getByRole("button", { name: "继续查找", exact: true })).toBeEnabled();
  await progress.getByRole("button", { name: "继续查找", exact: true }).click();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[1]).toEqual({ expected_version: 1, continue_company_id: "alibaba" });
});

test("discovered companies distinguish verified queue entries from pending candidates after reload", async ({ page }) => {
  const goal = { id: "discovery", name: "北京 Agent 校招", input_text: "北京 Agent 校招", query: "北京 Agent 校招", version: 1,
    conditions: { locations: ["北京"], roles: ["agent"], job_types: ["校招"], graduation_years: [2027], keywords: [] },
    condition_sources: {}, company_ids: null };
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id", "access-control-allow-methods": "GET,POST,OPTIONS" };
    if (request.method() === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (path === "/api/profile") return route.fulfill({ headers, status: 404, json: {} });
    if (path === "/api/discovery/goals") return route.fulfill({ headers, json: [goal] });
    if (path.endsWith("/library")) return route.fulfill({ headers, json: {
      goal_id: goal.id, goal_version: 1, query: goal.query, lead_ids: [], result_matches: [], counts: {}, updates: [], latest_run_id: null,
      company_discovery: [
        { id: "new-company", company: "新星科技", homepage_url: "https://nova.example/", career_url: "https://nova.example/careers",
          status: "verified", attempts: 1, reason: "已核验公司主页及官方招聘链接，已加入后续分批查询", evidence_url: "https://career.example.edu.cn/nova" },
        { id: "pending-company", company: "待核公司", homepage_url: "https://pending.example/", career_url: "https://pending.example/jobs",
          status: "pending", attempts: 1, reason: "公司主页尚未找到指向该招聘入口的实际链接" },
      ],
      company_progress: [{ source_id: "new-company", company: "新星科技", official_url: "https://nova.example/careers",
        status: "not_checked", matched_count: 0, checked_count: 0, pages_checked: 0, can_continue: false }],
    } });
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  for (let visit = 0; visit < 2; visit++) {
    await page.getByRole("button", { name: "搜索详情", exact: true }).click();
    const discovery = page.getByLabel("新公司发现");
    await expect(discovery.locator("summary")).toHaveText("新公司发现 · 1 家已入库 · 1 家待核实");
    await discovery.locator("summary").click();
    await expect(discovery.getByText("官方入口已核验 · 已加入公司库", { exact: true })).toBeVisible();
    await expect(discovery.getByText("待核实 · 尚未加入查询队列", { exact: true })).toBeVisible();
    await expect(discovery.getByRole("link", { name: "核验来源 ↗" })).toHaveAttribute("href", "https://career.example.edu.cn/nova");
    const progress = page.getByLabel("官网查询进度");
    await progress.locator("summary").click();
    await expect(progress.getByText("新星科技", { exact: true })).toBeVisible();
    await expect(progress.getByText("待核公司", { exact: true })).toHaveCount(0);
    if (visit === 0) await page.reload();
  }
});
