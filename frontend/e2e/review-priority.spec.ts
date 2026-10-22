import { expect, test } from "@playwright/test";

test("priority keeps AI product and cohort unknowns visible without claiming full confirmation", async ({ page }, testInfo) => {
  const check = (field: string, status: string, reason: string) => ({ field, status, reason, evidence: [], source_url: "https://example.com/jobs/1" });
  const rows = [
    { id: "confirmed", title: "Agent研发工程师", filter_status: "matched", review_status: "recommended", checks: [check("location", "matched", "上海"), check("job_type", "matched", "校园招聘"), check("role", "matched", "Agent研发"), check("graduation_year", "matched", "面向2027届毕业生")] },
    { id: "product", title: "AI产品经理", filter_status: "pending", review_status: "recommended", checks: [check("graduation_year", "pending", "未写届别"), check("availability", "pending", "开放状态未知")] },
    { id: "type", title: "招聘类型待确认", filter_status: "pending", review_status: "pending", checks: [check("job_type", "pending", "招聘类型待确认")] },
    { id: "city", title: "城市待确认", filter_status: "pending", review_status: "pending", checks: [check("location", "pending", "城市待确认")] },
    { id: "role", title: "方向待确认", filter_status: "pending", review_status: "pending", checks: [check("role", "pending", "方向待确认")] },
    { id: "excluded", title: "深圳岗位", filter_status: "excluded", review_status: "excluded", checks: [] },
    { id: "closed", title: "已经关闭的岗位", filter_status: "excluded", review_status: "excluded", checks: [] },
  ];
  const matches = rows.map(r => ({ ...r, job_posting_id: r.id, match_tier: r.filter_status === "matched" ? "strict" : "expanded", mismatch_reasons: [], mismatch_labels: [] }));
  const goal = { id: "goal", name: "北京上海AI校招", query: "北京上海AI产品 Agent RAG 2027届校招", input_text: "北京上海AI产品 Agent RAG 2027届校招", version: 1,
    conditions: { locations: ["北京", "上海"], roles: ["AI产品", "Agent", "RAG"], job_types: ["校招"], graduation_years: [2027], preferred_locations: [], excluded_locations: [], excluded_roles: [], excluded_job_types: [], keywords: [], pending_conditions: [] }, condition_sources: {} };
  const run = { started_at: "2026-10-18T05:00:00Z", created_at: "2026-10-18T05:00:00Z", id: "run", search_goal_id: "goal", search_goal_version: 1, search_query: goal.query, status: "SUCCEEDED", result_matches: matches.filter(r => r.id !== "confirmed"),
    discovered_count: 6, analysis_status: "NOT_REQUESTED", analysis_target_count: 0, analysis_completed_count: 0, agent_trace: [], search_plan: null };
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const headers = { "access-control-allow-origin": route.request().headers()["origin"] || "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id" };
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (path === "/api/profile") return route.fulfill({ headers, status: 404, json: {} });
    if (path === "/api/discovery/goals") return route.fulfill({ headers, json: [goal] });
    if (path.endsWith("/library")) return route.fulfill({ headers, json: { goal_id: "goal", goal_version: 1, query: goal.query, result_matches: matches, latest_run_id: "run", lead_ids: [], updates: [], counts: { matched: 1, pending: 4, recommended: 2, needs_review: 3, excluded: 2, closed: 1 } } });
    if (path === "/api/candidates") return route.fulfill({ headers, json: rows.map(r => ({ id: r.id, job_posting_id: r.id, status: "DISCOVERED", available_transitions: ["SAVED", "IGNORED"], analysis: null,
      job: { id: r.id, title: r.title, company: "验收公司", locations: ["上海"], job_type: "campus", last_verified_at: "2026-10-18T05:00:00Z", availability_status: r.id === "closed" ? "CLOSED" : r.id === "confirmed" ? "ACTIVE" : "UNKNOWN", source_url: `https://example.com/jobs/${r.id}` } })) });
    if (path === "/api/discovery/runs") return route.fulfill({ headers, json: [run] });
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  if (testInfo.project.name === "chromium") await expect(page.getByRole("columnheader", { name: "查看建议", exact: true })).toBeVisible();
  const product = page.getByRole("row").filter({ has: page.getByRole("button", { name: "AI产品经理", exact: true }) });
  await expect(product.locator(".job-advice-label")).toHaveText("推荐查看");
  await expect(product).toContainText("届别待确认");
  await expect(product).toContainText("开放状态未知");
  await expect(product).not.toContainText("搜索条件已确认");
  await expect(page.getByRole("button", { name: "已经关闭的岗位", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "深圳岗位", exact: true })).toHaveCount(0);
  for (const title of ["招聘类型待确认", "城市待确认", "方向待确认"]) {
    await expect(page.getByRole("button", { name: title, exact: true })).toBeVisible();
  }
  await expect(page.locator(".job-title")).toHaveText(["Agent研发工程师", "AI产品经理", "招聘类型待确认", "城市待确认", "方向待确认"]);
  await page.locator(".job-results").screenshot({ path: testInfo.outputPath("priority-jobs.png") });
  await page.locator(".result-options > summary").click();
  await page.getByRole("checkbox", { name: "显示不符或已关闭的岗位" }).check();
  await expect(page.locator(".job-list tbody tr").filter({ hasText: "深圳岗位" }).locator(".job-advice-label")).toHaveText("不符搜索条件");
  await expect(page.locator(".job-list tbody tr").filter({ hasText: "已经关闭的岗位" }).locator(".job-advice-label")).toHaveText("已关闭");
});

test("broad default restores hidden possibilities and ranks relevant evidence before cohort completeness", async ({ page }) => {
  const query = "北京上海Agent RAG AI产品2027届校招";
  const rows = [
    { id: "cohort", company: "甲公司", title: "届别已知但方向待确认", fields: ["graduation_year"], status: "pending" },
    { id: "role", company: "甲公司", title: "Agent职责明确但届别未知", fields: ["role", "location"], status: "pending" },
    { id: "another", company: "乙公司", title: "相邻方向产品岗", fields: ["location"], status: "pending" },
    { id: "conflict", company: "丙公司", title: "明确仅限2026届", fields: [], status: "excluded" },
  ];
  await page.addInitScript(({ query }) => localStorage.setItem(`jobflow:job-filters:local-user:${query}`,
    JSON.stringify({ decision: "matched", strictOnly: true })), { query });
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const headers = { "access-control-allow-origin": route.request().headers()["origin"] || "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id" };
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (path === "/api/profile") return route.fulfill({ headers, status: 404, json: {} });
    if (path === "/api/candidates") return route.fulfill({ headers, json: rows.map(r => ({ id: r.id, job_posting_id: r.id,
      status: "DISCOVERED", available_transitions: ["SAVED", "IGNORED"], analysis: null,
      job: { id: r.id, title: r.title, company: r.company, locations: ["上海"], source_url: `https://example.com/jobs/${r.id}` } })) });
    if (path === "/api/discovery/runs") return route.fulfill({ headers, json: [{ id: "broad", search_query: query, started_at: "2026-10-19T05:00:00Z", created_at: "2026-10-19T05:00:00Z",
      status: "SUCCEEDED", analysis_status: "NOT_REQUESTED", agent_trace: [], result_matches: rows.map(r => ({
        job_posting_id: r.id, filter_status: r.status, review_status: r.status, mismatch_labels: [],
        checks: r.fields.map(field => ({ field, status: "matched", reason: "原文支持", evidence: [] })),
      })) }] });
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  await expect(page.locator(".job-title")).toHaveText(["Agent职责明确但届别未知", "相邻方向产品岗", "届别已知但方向待确认"]);
  await expect(page.getByRole("button", { name: "相邻方向产品岗", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "明确仅限2026届", exact: true })).toHaveCount(0);
  await page.locator(".result-options > summary").click();
  await page.getByRole("checkbox", { name: "显示不符或已关闭的岗位" }).check();
  await expect(page.getByRole("button", { name: "明确仅限2026届", exact: true })).toBeVisible();
  await page.getByRole("checkbox", { name: "显示不符或已关闭的岗位" }).uncheck();
  await expect(page.locator(".job-title")).toHaveCount(3);
});

test("review advice distinguishes unread, queued, retrying and unresolved conditions", async ({ page }) => {
  const rows = [
    { id: "queued", title: "尚未完成理解", checks: [
      { field: "role", diagnosis: "not_extracted" }, { field: "location", diagnosis: "not_extracted" }] },
    { id: "recheck", title: "方向排除复核", checks: [{ field: "role", review_required: true }] },
    { id: "adjacent", title: "智能体数据研究", checks: [{ field: "role", role_relation: "adjacent", diagnosis: "ambiguous" }] },
    { id: "unread", title: "正文仍待读取", checks: [], analysis: "reading_required", review: "recommended" },
    { id: "retrying", title: "分析等待重试", checks: [{ field: "role", diagnosis: "not_extracted" }], analysis: "retrying" },
    { id: "blocked", title: "分析多次失败", checks: [{ field: "role", diagnosis: "not_extracted" }], analysis: "blocked" },
  ];
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const headers = { "access-control-allow-origin": route.request().headers()["origin"] || "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id" };
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (path === "/api/profile") return route.fulfill({ headers, status: 404, json: {} });
    if (path === "/api/candidates") return route.fulfill({ headers, json: rows.map(r => ({ id: r.id, job_posting_id: r.id,
      status: "DISCOVERED", available_transitions: ["SAVED", "IGNORED"], analysis: null,
      job: { id: r.id, title: r.title, company: "验收公司", locations: ["上海"], source_url: `https://example.com/jobs/${r.id}` } })) });
    if (path === "/api/discovery/runs") return route.fulfill({ headers, json: [{ id: "pending-states", search_query: "上海Agent校招",
      started_at: "2026-10-19T05:00:00Z", created_at: "2026-10-19T05:00:00Z", status: "SUCCEEDED", analysis_status: "NOT_REQUESTED",
      agent_trace: [], result_matches: rows.map(r => ({ job_posting_id: r.id, filter_status: "pending", review_status: r.review || "pending",
        result_status: r.analysis ? { reading: { status: r.id === "unread" ? "incomplete" : "readable" }, analysis: { state: r.analysis, label: "分析状态", reason: "" }, search: { state: "pending", label: "待判断", missing_fields: [] }, personal: { state: "unreviewed", label: "待核对", reason: "" } } : undefined,
        mismatch_labels: [], checks: r.checks.map(c => ({ ...c, status: "pending", reason: "原文判断状态", evidence: [] })) })) }] });
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  await expect(page.getByText("正文已保存，等待分析", { exact: true })).toHaveCount(1);
  await expect(page.getByText("方向判断待复核", { exact: true })).toBeVisible();
  await expect(page.getByText("相邻方向，值得看看", { exact: true })).toBeVisible();
  const unread = page.locator(".job-list tbody tr").filter({ hasText: "正文仍待读取" });
  await expect(unread.locator(".job-advice-label")).toHaveText("待核验");
  await expect(page.getByText("正文已保存，分析待重试", { exact: true })).toBeVisible();
  await expect(page.getByText("正文已保存，分析失败待重试", { exact: true })).toBeVisible();
  const titles = await page.locator(".job-title").allTextContents();
  expect(titles.indexOf("智能体数据研究")).toBeLessThan(titles.indexOf("尚未完成理解"));
});
