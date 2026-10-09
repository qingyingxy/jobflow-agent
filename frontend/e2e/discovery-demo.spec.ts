import { expect, test, type Page } from "@playwright/test";

const now = "2026-08-09T10:00:00+08:00";

const resultMatches = [
  {
    job_posting_id: "job-strict",
    match_tier: "strict",
    filter_status: "matched",
    mismatch_reasons: [],
    mismatch_labels: [],
  },
  {
    job_posting_id: "job-expanded",
    match_tier: "expanded",
    filter_status: "excluded",
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
  search_plan: {
    version: "bounded-discovery-v1",
    planner: "deterministic_policy",
    query: "北京的 AI Agent 校招岗位",
    allowed_source_ids: ["bytedance", "tencent"],
    routes: [
      {
        source_id: "bytedance",
        company: "字节跳动",
        source_url: "https://jobs.bytedance.com/campus/",
        tool_sequence: ["bytedance_public_job_adapter", "json_ld_job_parser", "static_job_page_validator", "visible_job_link_reader"],
      },
      {
        source_id: "tencent",
        company: "腾讯",
        source_url: "https://careers.tencent.com/campusrecruit.html",
        tool_sequence: ["tencent_public_job_adapter", "json_ld_job_parser", "static_job_page_validator", "visible_job_link_reader"],
      },
    ],
    budget: {
      max_results: 20,
      max_analysis: 5,
      max_detail_links_per_source: 4,
      max_concurrency: 6,
      request_timeout_seconds: 8,
    },
    stop_conditions: ["max_results_reached", "source_route_exhausted", "no_verified_jobs_requires_human_input"],
  },
  agent_trace: [
    {
      phase: "plan",
      tool: "bounded_discovery_planner",
      outcome: "selected",
      observation: "已将 2 个用户选择的官方来源锁定为本次访问白名单。",
      decision: "2 个来源优先使用专用 Adapter；严格执行来源路线、结果上限和停止条件。",
      source_id: null,
      company: null,
      url: null,
      occurred_at: now,
      duration_ms: 0,
      error_code: null,
      details: { allowed_source_ids: ["bytedance", "tencent"] },
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
      occurred_at: now,
      duration_ms: 3,
      error_code: null,
      details: { output_count: 2, strict_count: 1, expanded_count: 1 },
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
      verification_status: "VERIFIED_OFFICIAL",
      availability_status: "ACTIVE",
      first_seen_at: now,
      last_seen_at: now,
      last_verified_at: now,
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
      verification_status: "VERIFIED_OFFICIAL",
      availability_status: "ACTIVE",
      first_seen_at: now,
      last_seen_at: now,
      last_verified_at: now,
    },
    analysis: null,
    created_at: now,
    updated_at: now,
  },
];

const leadCandidate = {
  id: "candidate-lead",
  user_id: "local-user",
  job_posting_id: "job-lead",
  status: "DISCOVERED",
  available_transitions: ["SAVED", "IGNORED", "CONVERTED"],
  job: {
    id: "job-lead",
    company: "示例科技",
    title: "AI Agent 工程师",
    source_url: "https://careers.example.com/jobs/123",
    source_id: "manual_url:careers.example.com",
    locations: ["上海"],
    job_type: "campus",
    published_at: now,
    verification_status: "VERIFIED_SOURCE",
    availability_status: "ACTIVE",
    first_seen_at: now,
    last_seen_at: now,
    last_verified_at: now,
  },
  analysis: null,
  created_at: now,
  updated_at: now,
};

const handoffAnalysis = {
  analysis_id: "analysis-handoff",
  job: {
    id: "job-lead",
    company: "示例科技",
    title: "AI Agent 工程师",
    source_url: "https://careers.example.com/jobs/dynamic-123",
  },
  structured_jd: {
    company: "示例科技",
    title: "AI Agent 工程师",
    job_type: null,
    locations: [],
    education_requirements: [],
    major_requirements: [],
    required_skills: ["Python", "LLM"],
    preferred_skills: [],
    internship_duration_months: null,
    weekly_days: null,
    deadline: null,
    requirements: [],
  },
  eligibility: { eligible: "unknown", checks: [] },
  matches: [],
  score: {
    score: null,
    recommendation: "insufficient_data",
    groups: [],
    missing_information: ["候选人资格信息"],
  },
  risks: [],
  missing_information: ["候选人资格信息"],
};

async function installApiFixture(page: Page) {
  let searchStarted = false;
  let leadVerified = false;
  let leads: Array<Record<string, unknown>> = [];
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
    if (url.pathname === "/api/discovery/leads" && request.method() === "POST") {
      const payload = request.postDataJSON() as Record<string, unknown>;
      const created = {
        id: "lead-demo-12345678",
        discovery_run_id: null,
        provider: payload.provider,
        source_id: null,
        source_job_id: null,
        source_url: payload.source_url,
        normalized_url: payload.source_url,
        company_hint: payload.company_hint,
        title_hint: payload.title_hint,
        search_snippet: payload.search_snippet,
        discovery_kind: "job",
        status: "NEW",
        job_posting_id: null,
        failure_code: null,
        failure_reason: null,
        discovered_at: now,
        verified_at: null,
        created_at: now,
        updated_at: now,
      };
      leads = [created];
      await route.fulfill({ status: 201, headers: jsonHeaders, json: created });
      return;
    }
    if (url.pathname === "/api/discovery/leads") {
      await route.fulfill({ headers: jsonHeaders, json: leads });
      return;
    }
    if (url.pathname === "/api/discovery/leads/lead-demo-12345678/verify") {
      if (String(leads[0]?.source_url).includes("dynamic-123")) {
        leads = leads.map((lead) => ({
          ...lead,
          status: "NEEDS_BROWSER",
          next_action: "open_in_browser",
          failure_code: "lead_requires_browser",
          failure_reason: "页面依赖 JavaScript，静态读取无法验证具体岗位",
          updated_at: now,
        }));
        await route.fulfill({
          status: 422,
          headers: jsonHeaders,
          json: {
            error: {
              code: "lead_requires_browser",
              message: "页面依赖 JavaScript，静态读取无法验证具体岗位",
            },
          },
        });
        return;
      }
      leadVerified = true;
      leads = leads.map((lead) => ({
        ...lead,
        status: "VERIFIED",
        job_posting_id: "job-lead",
        verified_at: now,
        updated_at: now,
      }));
      await route.fulfill({ headers: jsonHeaders, json: { ...leads[0], verifications: [] } });
      return;
    }
    if (url.pathname === "/api/discovery/leads/lead-demo-12345678/handoff/manual-jd") {
      const payload = request.postDataJSON() as Record<string, unknown>;
      if (typeof payload.raw_content !== "string" || payload.raw_content.length < 20) {
        await route.fulfill({ status: 422, headers: jsonHeaders, json: { detail: "invalid JD" } });
        return;
      }
      leadVerified = true;
      leads = leads.map((lead) => ({
        ...lead,
        status: "VERIFIED",
        next_action: "open_job",
        job_posting_id: "job-lead",
        failure_code: null,
        failure_reason: null,
        verified_at: now,
        updated_at: now,
      }));
      await route.fulfill({ headers: jsonHeaders, json: { ...leads[0], verifications: [] } });
      return;
    }
    if (url.pathname === "/api/discovery/leads/lead-demo-12345678/handoff/browser") {
      leadVerified = true;
      leads = leads.map((lead) => ({
        ...lead,
        status: "VERIFIED",
        next_action: "open_job",
        job_posting_id: "job-lead",
        failure_code: null,
        failure_reason: null,
        verified_at: now,
        updated_at: now,
      }));
      await route.fulfill({ headers: jsonHeaders, json: { ...leads[0], verifications: [] } });
      return;
    }
    if (url.pathname === "/api/jobs/job-lead/availability/check") {
      await route.fulfill({
        headers: jsonHeaders,
        json: {
          id: "availability-demo",
          job_posting_id: "job-lead",
          previous_status: "ACTIVE",
          result_status: "ACTIVE",
          evidence_type: "page_content",
          source_url: "https://careers.example.com/jobs/123",
          content_hash: "demo",
          failure_code: null,
          failure_reason: null,
          evidence: { concrete_job_page: true },
          checked_at: now,
        },
      });
      return;
    }
    if (url.pathname === "/api/jobs/job-lead/analyze") {
      await route.fulfill({ headers: jsonHeaders, json: handoffAnalysis });
      return;
    }
    if (url.pathname === "/api/jobs/job-strict/analysis" && request.method() === "GET") {
      await route.fulfill({
        headers: jsonHeaders,
        json: {
          ...handoffAnalysis,
          analysis_id: "analysis-strict",
          job: {
            id: "job-strict",
            company: "腾讯",
            title: "混元 AI Agent 工程师 - 校园招聘",
            source_url: "https://careers.tencent.com/jobdesc.html?postId=1001",
          },
        },
      });
      return;
    }
    if (url.pathname === "/api/jobs/job-strict" && request.method() === "GET") {
      await route.fulfill({
        headers: jsonHeaders,
        json: {
          id: "job-strict",
          company: "腾讯",
          title: "混元 AI Agent 工程师 - 校园招聘",
          raw_content: "岗位职责：负责 AI Agent 产品研发。任职要求：熟悉 Python、LLM 和软件工程。",
        },
      });
      return;
    }
    if (url.pathname === "/api/jobs/job-lead" && request.method() === "GET") {
      await route.fulfill({
        headers: jsonHeaders,
        json: {
          id: "job-lead",
          company: "示例科技",
          title: "AI Agent 工程师",
          raw_content: "岗位职责：负责 AI Agent 产品研发。任职要求：熟悉 Python、LLM 和软件工程。",
        },
      });
      return;
    }
    if (url.pathname === "/api/jobs/job-lead/analysis" && request.method() === "GET") {
      await route.fulfill({ headers: jsonHeaders, json: handoffAnalysis });
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
      await route.fulfill({
        headers: jsonHeaders,
        json: searchStarted ? candidates : leadVerified ? [leadCandidate] : [],
      });
      return;
    }
    await route.fulfill({ status: 404, headers: jsonHeaders, json: { detail: "not mocked" } });
  });
}

test("filter results hide explicit conflicts until requested", async ({ page }) => {
  await installApiFixture(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "搜索岗位" })).toBeVisible();

  await page.getByText("优先公司（可选）", { exact: true }).click();
  await page.getByRole("checkbox", { name: /腾讯/ }).check();
  await page.getByLabel("你想找什么").fill("北京的 AI Agent 校招岗位");
  if (process.env.UPDATE_DEMO_ASSETS === "1") {
    await page.screenshot({ path: "test-results/demo-01-search.png" });
  }
  await page.getByRole("button", { name: "搜索并筛选" }).click();

  await expect(page.locator(".discovery-message")).toContainText("找到 2 个具体岗位");
  const table = page.locator(".jobs-table");
  await expect(table.getByRole("button", { name: "混元 AI Agent 工程师 - 校园招聘" })).toBeVisible();
  await expect(table.getByRole("button", { name: "Senior Platform Architect - Enterprise AI Agent" })).toHaveCount(0);
  await page.getByRole("checkbox", { name: "显示明确不符或已关闭的岗位" }).check();
  await table.getByRole("button", { name: "展开字节跳动" }).click();
  await expect(table.getByRole("button", { name: "Senior Platform Architect - Enterprise AI Agent" })).toBeVisible();
  await expect(table.locator(".jobs-company-rows").first()).toContainText("腾讯");
  await expect(table.getByText("地点不匹配；非校招")).toBeVisible();
  if (process.env.UPDATE_DEMO_ASSETS === "1") {
    await table.scrollIntoViewIfNeeded();
    await page.screenshot({ path: "test-results/demo-02-strict.png" });
  }

  await page.getByRole("checkbox", { name: "只看符合本次条件的岗位" }).check();
  await expect(table.getByRole("button", { name: "Senior Platform Architect - Enterprise AI Agent" })).toHaveCount(0);
  await expect(table.getByRole("button", { name: "混元 AI Agent 工程师 - 校园招聘" })).toBeVisible();
  await page.getByRole("checkbox", { name: "只看符合本次条件的岗位" }).uncheck();
  await expect(table.getByRole("button", { name: "Senior Platform Architect - Enterprise AI Agent" })).toBeVisible();

  await page.locator("summary.discovery-history-heading").click();
  const trace = page.locator("details.discovery-agent-trace");
  await trace.locator("summary").click();
  await expect(trace.getByText("来源 2 · 岗位上限 20 · 简历匹配按需进行")).toBeVisible();
  await expect(trace.getByText("tencent_public_job_adapter", { exact: false })).toBeVisible();
  await expect(trace.getByText("无事实时人工接管")).toBeVisible();

  if (process.env.UPDATE_DEMO_ASSETS === "1") {
    await table.getByRole("button", { name: "Senior Platform Architect - Enterprise AI Agent" }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: "test-results/demo-03-expanded.png" });
    await page.locator(".discovery-shell").screenshot({
      path: "../docs/assets/jobflow-discovery-demo.png",
    });
  }
});

test("existing analysis opens as a discovery detail and returns to the list", async ({ page }) => {
  await installApiFixture(page);
  await page.goto("/");
  const searchRequestPromise = page.waitForRequest((request) => (
    new URL(request.url()).pathname === "/api/discovery/search"
  ));
  await page.getByRole("button", { name: "搜索并筛选" }).click();
  const searchRequest = await searchRequestPromise;
  expect(searchRequest.postDataJSON()).toEqual({
    query: "北京 / 上海的 AI Agent、LLM、算法校招岗位",
    source_mode: "web",
    company_ids: null,
  });

  await page.locator(".jobs-table").getByRole("button", { name: "混元 AI Agent 工程师 - 校园招聘" }).click();
  const detail = page.getByRole("dialog", { name: "岗位详情" });
  await expect(detail.getByRole("heading", { name: "混元 AI Agent 工程师 - 校园招聘" })).toBeVisible();
  await expect(detail.getByText("岗位职责：负责 AI Agent 产品研发", { exact: false })).toBeVisible();
  await detail.getByRole("button", { name: "打开完整匹配与申请" }).click();

  await expect(page.getByRole("heading", { name: "岗位匹配详情" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "混元 AI Agent 工程师 - 校园招聘" })).toBeVisible();
  await page.getByRole("button", { name: "返回岗位列表" }).click();

  await expect(page.getByRole("heading", { name: "发现适合你的岗位" })).toBeVisible();
  await expect(page.locator(".jobs-table").getByRole("button", { name: "混元 AI Agent 工程师 - 校园招聘" })).toBeVisible();
});

test("submitted job lead stays untrusted until verification succeeds", async ({ page }, testInfo) => {
  await installApiFixture(page);
  await page.goto("/");
  await page.locator("summary.job-lead-heading").click();

  await page.getByLabel("具体岗位 URL").fill("https://careers.example.com/jobs/123");
  await page.getByLabel("公司提示（可选）").fill("示例科技");
  await page.getByLabel("岗位提示（可选）").fill("AI Agent 工程师");
  await page.getByRole("button", { name: /保存线索/ }).click();

  await expect(page.getByText("岗位线索已保存")).toBeVisible();
  const table = page.locator(".jobs-table");
  const leadRow = table.getByRole("row", { name: /AI Agent 工程师/ });
  await expect(leadRow).toContainText("待验证");
  await expect(leadRow).toContainText("条件尚未确认");
  await expect(table.getByRole("button", { name: "AI Agent 工程师" })).toBeVisible();
  if (process.env.UPDATE_M13_ASSETS === "1") {
    await page.locator(".job-lead-section").screenshot({
      path: `test-results/m13-lead-queue-${testInfo.project.name}.png`,
    });
  }

  await leadRow.getByRole("button", { name: "验证正文" }).click();

  await expect(page.getByText("岗位已进入可信候选池", { exact: false })).toBeVisible();
  const candidateRow = table.getByRole("row", { name: /AI Agent 工程师/ });
  await expect(candidateRow).toContainText("正文已核验");
  await candidateRow.getByRole("button", { name: "AI Agent 工程师" }).click();
  await expect(page.getByRole("dialog", { name: "岗位详情" }).getByText("岗位职责：负责 AI Agent 产品研发", { exact: false })).toBeVisible();
  if (process.env.UPDATE_M13_ASSETS === "1") {
    await page.locator(".job-lead-section").screenshot({
      path: `test-results/m13-lead-verified-${testInfo.project.name}.png`,
    });
  }
});

test("dynamic lead manual handoff remains linked through analysis", async ({ page }) => {
  await installApiFixture(page);
  await page.goto("/");
  await page.locator("summary.job-lead-heading").click();
  await page.getByLabel("具体岗位 URL").fill("https://careers.example.com/jobs/dynamic-123");
  await page.getByLabel("公司提示（可选）").fill("示例科技");
  await page.getByLabel("岗位提示（可选）").fill("AI Agent 工程师");
  await page.getByRole("button", { name: /保存线索/ }).click();
  const leadRow = page.locator(".jobs-table").getByRole("row", { name: /AI Agent 工程师/ });
  await leadRow.getByRole("button", { name: "验证正文" }).click();

  await expect(leadRow).toContainText("需要浏览器");
  await expect(leadRow).toContainText("页面依赖 JavaScript");
  await leadRow.getByRole("button", { name: "粘贴 JD 接管" }).click();

  await expect(page.getByRole("heading", { name: "补充岗位原文" })).toBeVisible();
  await expect(page.getByText("正在补充一条无法自动读取的岗位", { exact: true })).toBeVisible();
  await page.getByLabel("岗位描述").fill(
    "岗位职责：负责 AI Agent 产品研发和评测平台建设。任职要求：熟悉 Python、LLM 和软件工程。",
  );
  await page.getByRole("button", { name: "补充并分析" }).click();

  await expect(page.getByText("示例科技 · AI Agent 工程师", { exact: true })).toBeVisible();
  await expect(page.getByText("信息不足", { exact: true }).first()).toBeVisible();
});

test("dynamic lead can use read-only browser verification", async ({ page }) => {
  await installApiFixture(page);
  await page.goto("/");
  await page.locator("summary.job-lead-heading").click();
  await page.getByLabel("具体岗位 URL").fill("https://careers.example.com/jobs/dynamic-123");
  await page.getByLabel("公司提示（可选）").fill("示例科技");
  await page.getByLabel("岗位提示（可选）").fill("AI Agent 工程师");
  await page.getByRole("button", { name: /保存线索/ }).click();
  const table = page.locator(".jobs-table");
  const leadRow = table.getByRole("row", { name: /AI Agent 工程师/ });
  await leadRow.getByRole("button", { name: "验证正文" }).click();

  await expect(leadRow.getByRole("button", { name: "浏览器验证" })).toBeVisible();
  await leadRow.getByRole("button", { name: "浏览器验证" }).click();

  await expect(page.getByText("浏览器验证完成", { exact: false })).toBeVisible();
  await table.getByRole("button", { name: "AI Agent 工程师" }).click();
  await page.getByRole("dialog", { name: "岗位详情" }).getByRole("button", { name: "检查开放状态" }).click();
  await expect(page.getByText("开放状态检查完成：开放中", { exact: false })).toBeVisible();
});
