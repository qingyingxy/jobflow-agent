import { expect, test, type Page } from "@playwright/test";

const now = "2026-08-09T10:00:00+08:00";

const resultMatches = [
  {
    job_posting_id: "job-strict",
    match_tier: "strict",
    mismatch_reasons: [],
    mismatch_labels: [],
  },
  {
    job_posting_id: "job-expanded",
    match_tier: "expanded",
    mismatch_reasons: ["location", "job_type"],
    mismatch_labels: ["地点不匹配", "非校招"],
  },
];

const completedRun = {
  id: "discovery-demo-run",
  source: "official-registry:ai-campus-40",
  source_url: "registry://ai-campus-target-companies-40",
  search_query: "北京的 AI Agent 校招岗位",
  max_results: 20,
  status: "SUCCEEDED",
  discovered_count: 2,
  new_count: 2,
  duplicate_count: 0,
  analysis_target_count: 1,
  analysis_completed_count: 1,
  analysis_failure_count: 0,
  analysis_status: "SUCCEEDED",
  agent_trace: [
    {
      phase: "plan",
      tool: "discovery_orchestrator",
      outcome: "selected",
      observation: "已登记 2 个本次允许访问的公开来源。",
      decision: "按专用 Adapter 和受控页面读取顺序执行。",
      source_id: null,
      company: null,
      url: null,
    },
    {
      phase: "observe",
      tool: "candidate_validator",
      outcome: "succeeded",
      observation: "严格匹配 1 条，拓展候选 1 条。",
      decision: "只自动分析严格匹配岗位。",
      source_id: null,
      company: null,
      url: null,
    },
  ],
  result_matches: resultMatches,
  failure_summary: null,
  started_at: now,
  finished_at: now,
  created_at: now,
};

const candidates = [
  {
    id: "candidate-strict",
    user_id: "local-user",
    job_posting_id: "job-strict",
    status: "DISCOVERED",
    available_transitions: ["SAVED", "IGNORED", "CONVERTED"],
    job: {
      id: "job-strict",
      company: "腾讯",
      title: "混元 AI Agent 工程师 - 校园招聘",
      source_url: "https://careers.tencent.com/jobdesc.html?postId=1001",
      source_id: "tencent:public-careers",
      locations: ["北京"],
      job_type: "campus",
      published_at: now,
      last_seen_at: now,
    },
    analysis: {
      status: "ready",
      score: 86,
      recommendation: "recommended",
      eligibility: "pass",
    },
    created_at: now,
    updated_at: now,
  },
  {
    id: "candidate-expanded",
    user_id: "local-user",
    job_posting_id: "job-expanded",
    status: "DISCOVERED",
    available_transitions: ["SAVED", "IGNORED", "CONVERTED"],
    job: {
      id: "job-expanded",
      company: "字节跳动",
      title: "Senior Platform Architect - Enterprise AI Agent",
      source_url: "https://joinbytedance.com/search/1002",
      source_id: "bytedance:public-supplier",
      locations: ["圣何塞"],
      job_type: "full_time",
      published_at: now,
      last_seen_at: now,
    },
    analysis: null,
    created_at: now,
    updated_at: now,
  },
];

async function installApiFixture(page: Page) {
  let searchStarted = false;
  const jsonHeaders = {
    "access-control-allow-origin": "http://localhost:3000",
    "access-control-allow-headers": "content-type,x-user-id",
    "access-control-allow-methods": "GET,POST,PATCH,OPTIONS",
    "content-type": "application/json",
  };

  await page.route("http://127.0.0.1:18001/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 200, headers: jsonHeaders, body: "" });
      return;
    }
    if (url.pathname === "/api/discovery/sources") {
      await route.fulfill({
        headers: jsonHeaders,
        json: [
          { id: "bytedance", company: "字节跳动", priority: "A", search_mode: "dedicated_adapter" },
          { id: "tencent", company: "腾讯", priority: "A", search_mode: "dedicated_adapter" },
        ],
      });
      return;
    }
    if (url.pathname === "/api/discovery/search" && request.method() === "POST") {
      searchStarted = true;
      await route.fulfill({
        status: 202,
        headers: jsonHeaders,
        json: { ...completedRun, status: "RUNNING", result_matches: [], finished_at: null },
      });
      return;
    }
    if (url.pathname === `/api/discovery/runs/${completedRun.id}`) {
      await route.fulfill({ headers: jsonHeaders, json: completedRun });
      return;
    }
    if (url.pathname === "/api/discovery/runs") {
      await route.fulfill({ headers: jsonHeaders, json: searchStarted ? [completedRun] : [] });
      return;
    }
    if (url.pathname === "/api/candidates") {
      await route.fulfill({ headers: jsonHeaders, json: searchStarted ? candidates : [] });
      return;
    }
    await route.fulfill({ status: 404, headers: jsonHeaders, json: { detail: "not mocked" } });
  });
}

test("strict and expanded discovery results stay visibly separated", async ({ page }) => {
  await installApiFixture(page);
  await page.goto("/");
  await page.getByRole("button", { name: /岗位发现/ }).click();
  await expect(page.getByRole("heading", { name: /把模糊目标交给/ })).toBeVisible();

  await page.getByRole("checkbox", { name: /腾讯/ }).check();
  await page.getByLabel("你想找什么").fill("北京的 AI Agent 校招岗位");
  if (process.env.UPDATE_DEMO_ASSETS === "1") {
    await page.screenshot({ path: "test-results/demo-01-search.png" });
  }
  await page.getByRole("button", { name: "搜索并分析" }).click();

  await expect(page.locator(".discovery-message")).toContainText("严格匹配 1 条");
  await expect(page.getByText("混元 AI Agent 工程师 - 校园招聘")).toBeVisible();
  await expect(page.getByText("Senior Platform Architect - Enterprise AI Agent")).toBeHidden();
  if (process.env.UPDATE_DEMO_ASSETS === "1") {
    await page.getByRole("heading", { name: "严格匹配" }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: "test-results/demo-02-strict.png" });
  }

  const expanded = page.locator("details.discovery-expanded-results");
  await expect(expanded.getByText("拓展候选 / 01", { exact: false })).toBeVisible();
  await expanded.locator("summary").click();
  await expect(page.getByText("Senior Platform Architect - Enterprise AI Agent")).toBeVisible();
  await expect(expanded.getByText("地点不匹配", { exact: true })).toBeVisible();
  await expect(expanded.getByText("非校招", { exact: true })).toBeVisible();
  await expect(expanded.getByRole("button", { name: "手动分析 ↗" })).toBeVisible();

  if (process.env.UPDATE_DEMO_ASSETS === "1") {
    await page.getByText("Senior Platform Architect - Enterprise AI Agent").scrollIntoViewIfNeeded();
    await page.screenshot({ path: "test-results/demo-03-expanded.png" });
    await page.locator(".discovery-shell").screenshot({
      path: "../docs/assets/jobflow-discovery-demo.png",
    });
  }
});
