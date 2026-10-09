import { expect, test } from "@playwright/test";

test("filter categories ignore resume recommendations and keep unknowns visible during search", async ({ page }) => {
  const query = "只要2027届上海后端校招，不考虑北京";
  const checks = (status: string, reason: string) => [{ field: "location", status, reason, evidence: ["上海"], source_url: "https://example.com/jobs/1" }];
  const results = [
    { job_posting_id: "matched", filter_status: "matched", match_tier: "strict", mismatch_reasons: [], mismatch_labels: [], checks: checks("matched", "地点符合条件") },
    { job_posting_id: "pending", filter_status: "pending", match_tier: "expanded", mismatch_reasons: ["graduation_year"], mismatch_labels: ["届别待核实"], checks: checks("pending", "届别待核实") },
    { job_posting_id: "excluded", filter_status: "excluded", match_tier: "expanded", mismatch_reasons: ["excluded_location"], mismatch_labels: ["地点在排除范围"], checks: checks("excluded", "地点在排除范围") },
  ];
  const run = { id: "run", search_query: query, status: "RUNNING", discovered_count: 4, analysis_status: "NOT_REQUESTED", analysis_target_count: 0, analysis_completed_count: 0, result_matches: results, agent_trace: [], filter_conditions: { locations: ["上海"], graduation_years: [2027], excluded_locations: ["北京"] } };
  const candidates = results.map(r => ({ id: r.job_posting_id, job_posting_id: r.job_posting_id, status: "DISCOVERED", available_transitions: ["SAVED", "IGNORED"], job: { id: r.job_posting_id, title: `${r.job_posting_id}后端工程师`, company: "筛选公司", locations: r.filter_status === "excluded" ? ["北京"] : ["上海"], job_type: "campus", source_url: `https://example.com/jobs/${r.job_posting_id}` }, analysis: { recommendation: r.filter_status === "matched" ? "not_recommended" : "recommended_application" } }));
  const lead = { id: "slow", discovery_run_id: "run", status: "DEFERRED", discovery_kind: "job", provider: "external_agent", title_hint: "暂缓核验岗位", company_hint: "筛选公司", source_url: "https://example.com/jobs/slow", failure_code: "verification_budget_exhausted", failure_reason: "本次核验预算已用尽，可继续核验", next_action: "retry_verification", job_posting_id: null };
  const closedLead = { ...lead, id: "closed", status: "CLOSED", title_hint: "已下线岗位线索", source_url: "https://example.com/jobs/closed", failure_code: "job_closed", failure_reason: "原始岗位页面明确显示：该职位已下线", next_action: "open_in_browser" };
  let analyses = 0;
  let retries = 0;
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id", "access-control-allow-methods": "GET,POST,OPTIONS" };
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (path.endsWith("/analyze")) analyses++;
    if (path.endsWith("/slow/verify")) { retries++; return route.fulfill({ headers, json: lead }); }
    if (path === "/api/profile") return route.fulfill({ headers, status: 404, json: {} });
    if (path === "/api/candidates") return route.fulfill({ headers, json: candidates });
    if (path === "/api/discovery/runs") return route.fulfill({ headers, json: [run] });
    if (path === "/api/discovery/runs/run") return route.fulfill({ headers, json: run });
    if (path === "/api/discovery/leads") return route.fulfill({ headers, json: [lead, closedLead] });
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "matched后端工程师", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "pending后端工程师", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "excluded后端工程师", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "已下线岗位线索", exact: true })).toHaveCount(0);
  await expect(page.getByRole("checkbox", { name: "只看符合本次条件的岗位" })).not.toBeChecked();
  await expect(page.getByLabel("本次筛选条件")).toContainText("排除地点：北京");
  const row = page.getByRole("row").filter({ has: page.getByRole("button", { name: "暂缓核验岗位", exact: true }) });
  await expect(row).toContainText("暂缓核验，可重试");
  await expect(row.getByRole("button", { name: "粘贴 JD 接管" })).toHaveCount(0);
  await row.getByRole("button", { name: "验证正文" }).click();
  await expect.poll(() => retries).toBe(1);
  await page.getByRole("combobox", { name: "筛选结果", exact: true }).selectOption("excluded");
  await expect(page.getByRole("button", { name: "excluded后端工程师", exact: true })).toBeVisible();
  const closedRow = page.getByRole("row").filter({ has: page.getByRole("button", { name: "已下线岗位线索", exact: true }) });
  await expect(closedRow).toContainText("原页面确认已下线");
  await expect(closedRow).toContainText("明确不符");
  expect(analyses).toBe(0);
});

test("matched jobs from every company precede pending jobs and recruitment entries", async ({ page }) => {
  const rows = [
    { id: "a-pending", company: "甲公司", status: "pending" },
    { id: "a-matched", company: "甲公司", status: "matched" },
    { id: "b-matched", company: "乙公司", status: "matched" },
    { id: "a-excluded", company: "甲公司", status: "excluded" },
    { id: "unknown-matched", company: null, status: "matched" },
  ];
  const candidates = rows.map(r => ({ id: r.id, job_posting_id: r.id, status: "DISCOVERED", available_transitions: ["SAVED", "IGNORED"],
    job: { id: r.id, title: r.id, company: r.company, locations: ["上海"], job_type: "campus", source_url: `https://example.com/jobs/${r.id}` }, analysis: null }));
  const run = { id: "status-order", search_query: "上海Agent校招", status: "SUCCEEDED", analysis_status: "NOT_REQUESTED", agent_trace: [],
    result_matches: rows.map(r => ({ job_posting_id: r.id, filter_status: r.status, mismatch_labels: [], mismatch_reasons: [], checks: [] })) };
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id" };
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (path === "/api/profile") return route.fulfill({ headers, status: 404, json: {} });
    if (path === "/api/candidates") return route.fulfill({ headers, json: candidates });
    if (path === "/api/discovery/runs") return route.fulfill({ headers, json: [run] });
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  // All confirmed company groups are open without user interaction.
  for (const id of ["a-matched", "b-matched", "unknown-matched"]) {
    await expect(page.getByRole("button", { name: id, exact: true })).toBeVisible();
  }
  await page.getByRole("button", { name: "全部展开", exact: true }).click();
  await expect(page.locator(".jobs-title")).toHaveText(["a-matched", "b-matched", "unknown-matched", "a-pending"]);
  await page.getByRole("checkbox", { name: "显示明确不符或已关闭的岗位" }).check();
  await page.getByRole("button", { name: "全部展开", exact: true }).click();
  await expect(page.locator(".jobs-title")).toHaveText(["a-matched", "b-matched", "unknown-matched", "a-pending", "a-excluded"]);
  await page.getByRole("button", { name: "全部收起", exact: true }).click();
  await expect(page.locator(".jobs-title")).toHaveCount(0);
  await page.getByRole("button", { name: "全部展开", exact: true }).click();
  await page.getByRole("checkbox", { name: "只看符合本次条件的岗位" }).check();
  await expect(page.locator(".jobs-title")).toHaveText(["a-matched", "b-matched", "unknown-matched"]);
});
