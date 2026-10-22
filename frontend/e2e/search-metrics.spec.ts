import { expect, test } from "@playwright/test";

test("search history distinguishes cached evidence, recovery and newly useful jobs", async ({ page }) => {
  const run = {
    id: "measured", source: "web", source_url: "https://example.com", search_query: "北京上海 Agent 校招",
    status: "SUCCEEDED", discovered_count: 4, new_count: 1, duplicate_count: 3,
    result_matches: [], agent_trace: [], search_plan: null, failure_summary: null,
    started_at: "2026-10-17T08:00:00Z", finished_at: "2026-10-17T08:00:30Z", created_at: "2026-10-17T08:00:00Z",
    usage_metrics: { first_result_ms: 10442, first_useful_ms: 13605, read_attempts: 3, read_successes: 2,
      read_success_rate: 0.6667, cache_hits: 1, retry_attempts: 2, retry_recovered: 1,
      first_recommended_ms: 10500, first_fresh_recommended_ms: 12000, new_recommended_jobs: 2, resolved_recommended_jobs: 1,
      first_fresh_useful_ms: 18500, source_read_attempts: 4, source_read_successes: 2,
      source_read_success_rate: 0.5, source_retry_attempts: 3, source_retry_recovered: 2,
      new_effective_jobs: 1, resolved_effective_jobs: 1, effective_job_gain: 2 },
  };
  const legacyMetrics = { ...run.usage_metrics, first_recommended_ms: undefined, first_fresh_recommended_ms: undefined, new_recommended_jobs: undefined, resolved_recommended_jobs: undefined, first_fresh_useful_ms: undefined,
    source_read_attempts: undefined, source_read_successes: undefined,
    source_read_success_rate: undefined, source_retry_attempts: undefined, source_retry_recovered: undefined };
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = [];
    if (path === "/api/profile") body = { degree: "本科", major: "计算机科学", graduation_year: 2027 };
    if (path === "/api/discovery/runs") body = [run, { ...run, id: "legacy", usage_metrics: legacyMetrics },
      { ...run, id: "old", usage_metrics: null }];
    await route.fulfill({ headers: { "access-control-allow-origin": "http://localhost:3000",
      "access-control-allow-headers": "content-type,x-user-id", "access-control-allow-methods": "GET,POST,OPTIONS" }, json: body });
  });
  await page.goto("/");
  await page.locator("summary.discovery-history-heading").click();
  await expect(page.getByLabel("搜索实际效果")).toHaveCount(2);
  const metrics = page.getByLabel("搜索实际效果").first();
  await expect(metrics).toContainText("首次出结果 10.4 秒");
  await expect(metrics).toContainText("首次全部条件确认（含缓存）13.6 秒");
  await expect(metrics).toContainText("本轮新读首次全部条件确认 18.5 秒");
  await expect(metrics).toContainText("官网列表读取 2/4 家（50%）");
  await expect(metrics).toContainText("官网续查恢复 2/3 家");
  await expect(metrics).toContainText("正文读取 2/3（67%）");
  await expect(metrics).toContainText("复用缓存 1");
  await expect(metrics).toContainText("正文续查恢复 1/2");
  await expect(metrics).toContainText("新增全部条件确认 1");
  await expect(metrics).toContainText("已有岗位转全部条件确认 1");
  await expect(metrics).toContainText("首次优先查看（含缓存）10.5 秒");
  await expect(metrics).toContainText("本轮新读首次优先查看 12.0 秒");
  await expect(metrics).toContainText("新增优先查看 2");
  await expect(metrics).toContainText("已有岗位转优先查看 1");
  const legacy = page.getByLabel("搜索实际效果").nth(1);
  await expect(legacy).toContainText("正文读取 2/3（67%）");
  await expect(legacy).not.toContainText(/官网列表读取|本轮新读首次全部条件确认|优先查看|NaN|undefined/);
});
