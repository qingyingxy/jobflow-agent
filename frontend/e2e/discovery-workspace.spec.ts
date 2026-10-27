import { expect, test, type Page } from "@playwright/test";

async function workspaceFixture(page: Page, compact = false) {
  const input = "27届，北京上海都可以，想找 Agent / RAG 相关开发岗。\n实习和校招都看看，优先应用开发。";
  const conditions = { locations: ["北京", "上海"], roles: ["Agent", "RAG"], job_types: ["校招", "实习"], graduation_years: [2027], preferred_roles: ["应用开发"], preferred_locations: [], excluded_locations: [], excluded_roles: [], excluded_job_types: [], keywords: [], pending_conditions: ["是否接受转专业"] };
  const goals = [{ id: "agent", name: "不应展示这个生成标题", input_text: input, query: input, version: 1, conditions, condition_sources: {}, company_ids: null },
    { id: "other", name: "历史需求", input_text: "深圳产品实习", query: "深圳产品实习", version: 1, conditions: { ...conditions, locations: ["深圳"], roles: ["产品"], job_types: ["实习"], pending_conditions: [] }, condition_sources: {}, company_ids: null }];
  const jobs = [
    { id: "one", company: "字节跳动", title: "Agent 开发工程师 · AI Platform", locations: ["上海", "北京"], job_type: "campus" },
    { id: "two", company: "字节跳动", title: "Agent 基础系统研发工程师 · 火山方舟", locations: ["北京", "上海"], job_type: "campus" },
    { id: "three", company: "MiniMax", title: "可观测平台研发工程师", locations: ["上海"], job_type: "campus" },
    { id: "four", company: "月之暗面", title: "大模型应用开发实习生", locations: ["北京"], job_type: "internship" },
    { id: "unknown", company: "智谱", title: "Agent 应用工程师", locations: [], job_type: null },
    { id: "closed", company: "历史公司", title: "已关闭的岗位", locations: ["上海"], job_type: "campus", availability_status: "CLOSED" },
    { id: "unrelated", company: "历史公司", title: "深圳产品实习生", locations: ["深圳"], job_type: "internship" },
  ].map(job => ({ ...job, source_url: `https://example.com/jobs/${job.id}` }));
  const candidates = jobs.map(job => ({ id: job.id, job_posting_id: job.id, status: "DISCOVERED", available_transitions: ["SAVED", "IGNORED"], job, analysis: null }));
  const check = (field: string, status: string, reason: string, evidence: string[] = []) => ({ field, status, reason, evidence, source_url: "https://example.com/jobs/two" });
  const matches = jobs.filter(j => j.id !== "unrelated").map(job => ({
    job_posting_id: job.id,
    filter_status: job.id === "closed" ? "excluded" : ["two", "three", "unknown"].includes(job.id) ? "pending" : "matched",
    review_status: ["one", "two", "four"].includes(job.id) ? "recommended" : "pending",
    mismatch_labels: [], mismatch_reasons: [],
    checks: job.id === "unknown" ? [check("location", "pending", "原文未写地点"), check("job_type", "pending", "原文未写招聘类型")]
      : job.id === "three" ? [{ ...check("role", "pending", "可观测平台与目标方向相关"), role_relation: "adjacent" }]
      : [check("role", "matched", "职责包含 Agent 应用开发", ["负责 Agent 应用开发与检索增强系统建设"]), check("location", "matched", "工作地点符合需求"),
        ...(job.id === "two" ? [check("graduation_year", "pending", "原文未说明毕业届别")] : [])],
    // Deliberately retain an old recommendation to verify conflict precedence.
    personal_gate_conflict: job.id === "four",
    personal_requirements: job.id === "four" ? [{ category: "education", status: "attention", label: "学历要求", reason: "要求硕士及以上，当前资料为本科", evidence: "硕士及以上学历", source_url: job.source_url }]
      : job.id === "one" ? [
        { category: "education", status: "unknown", label: "学历要求", reason: "原文有此要求，个人资料尚未核对", evidence: "2027届本科及以上学历", source_url: job.source_url },
        { category: "skill", status: "unknown", label: "技术要求", reason: "原文有此要求，个人资料尚未核对", evidence: "掌握 Python 或 Golang，熟悉 React 或 Vue", source_url: job.source_url },
      ] : [],
    result_status: job.id === "one" ? {
      reading: { status: "readable" }, analysis: { state: "completed", label: "搜索条件已分析", reason: "搜索判断与个人资格分别核对" },
      search: { state: "matched", label: "搜索条件符合", missing_fields: [] },
      personal: { state: "profile_missing", label: "个人资料待补充", reason: "搜索条件符合不代表全部任职资格符合" },
    } : undefined,
  }));
  const run = { id: "run", source: "web_search", source_url: "https://example.com", search_query: input, search_goal_id: "agent", search_goal_version: 1, status: "SUCCEEDED", max_results: 20, discovered_count: 6, new_count: 6, duplicate_count: 0, analysis_target_count: 0, analysis_completed_count: 0, analysis_failure_count: 0, analysis_status: "NOT_REQUESTED", search_plan: null, agent_trace: [], result_matches: matches, failure_summary: null, started_at: "2026-10-21T02:00:00Z", finished_at: "2026-10-21T02:00:10Z", created_at: "2026-10-21T02:00:00Z" };
  const lead = { id: "lead", created_at: "2026-10-21T02:00:00Z", updated_at: "2026-10-21T02:00:00Z", discovered_at: "2026-10-21T02:00:00Z", discovery_run_id: "run", status: "DEFERRED", discovery_kind: "job", provider: "external_agent", title_hint: "RAG 研发工程师", company_hint: "百川智能", source_url: "https://example.com/jobs/lead", normalized_url: "https://example.com/jobs/lead", job_posting_id: null, failure_reason: "等待核验", next_action: "retry_verification" };
  const entry = { ...lead, id: "entry", discovery_kind: "entry", title_hint: "官方招聘入口", source_url: "https://example.com/careers", normalized_url: "https://example.com/careers" };
  const writes: { path: string; body: Record<string, unknown> }[] = [];
  const detailReads: string[] = [];
  await page.addInitScript(() => localStorage.setItem("jobflow:job-filters:local-user:agent:1", JSON.stringify({ viewVersion: 2, scope: "all", city: "昆明", kind: "full_time", keyword: "过期筛选", strictOnly: true })));
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const req = route.request(), path = new URL(req.url()).pathname;
    const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id", "access-control-allow-methods": "GET,POST,PATCH,OPTIONS" };
    if (req.method() === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (req.method() !== "GET") writes.push({ path, body: req.postDataJSON() });
    if (path === "/api/profile" || path.endsWith("/analysis")) return route.fulfill({ headers, status: 404, json: {} });
    if (path === "/api/discovery/goals") return route.fulfill({ headers, json: goals });
    if (path.startsWith("/api/discovery/goals/agent/jobs/")) {
      detailReads.push(path);
      if (detailReads.length === 1) return route.fulfill({ headers, status: 503, json: { detail: "筛选依据暂时不可用" } });
      return route.fulfill({ headers, json: matches.find(m => path.endsWith("/" + m.job_posting_id)) });
    }
    if (path.endsWith("/library")) {
      const other = path.includes("/other/");
      return route.fulfill({ headers, json: { goal_id: other ? "other" : "agent", goal_version: 1, query: other ? goals[1].query : input, lead_ids: other ? [] : ["lead", "entry"], result_matches: other ? [{ ...matches[0], job_posting_id: "unrelated" }] : compact ? matches.map(m => ({ ...m, details_compact: true, checks: m.checks.map(c => ({ ...c, evidence: [] })) })) : matches, counts: {}, updates: [], latest_run_id: other ? null : "run", company_progress: other ? [] : [{ source_id: "bytedance", company: "字节跳动", official_url: "https://jobs.bytedance.com", status: "paused", checked_count: 3, matched_count: 2, pages_checked: 1, remaining_count: 7, can_continue: true }] } });
    }
    if (path === "/api/candidates") return route.fulfill({ headers, json: candidates });
    if (path.startsWith("/api/candidates/")) {
      const candidate = candidates.find(c => path.includes(c.id))!;
      candidate.status = String(req.postDataJSON().status);
      return route.fulfill({ headers, json: candidate });
    }
    if (path === "/api/discovery/leads") return route.fulfill({ headers, json: [lead, entry] });
    if (path.endsWith("/lead/verify")) return route.fulfill({ headers, json: lead });
    if (path === "/api/discovery/runs") return route.fulfill({ headers, json: [run] });
    if (path === "/api/discovery/runs/run" || path.endsWith("/search")) return route.fulfill({ headers, json: run });
    if (path.startsWith("/api/jobs/")) return route.fulfill({ headers, json: { raw_content: "负责 Agent 应用开发与检索增强系统建设。岗位要求：熟悉 Python，有相关项目经验。", availability_status: "ACTIVE" } });
    return route.fulfill({ headers, json: [] });
  });
  return { writes, input, detailReads };
}

test("result categories and compact details load independently and can retry", async ({ page }) => {
  const { detailReads } = await workspaceFixture(page, true);
  await page.goto("/");
  await expect(page.getByLabel("结果分类")).toContainText("符合搜索条件 2 · 条件待确认 3 · 正文待核验 1");
  await page.getByLabel("结果类别", { exact: true }).selectOption("unread");
  await expect(page.locator(".job-title")).toHaveText(["RAG 研发工程师"]);
  await page.getByLabel("结果类别", { exact: true }).selectOption("matched");
  await expect(page.locator(".job-list tbody tr")).toHaveCount(2);
  expect(detailReads).toEqual([]);
  await page.getByRole("button", { name: "Agent 开发工程师 · AI Platform", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "岗位详情" });
  await dialog.getByRole("tab", { name: "筛选依据" }).click();
  await expect(dialog.getByRole("alert")).toContainText("请求失败（503）");
  await dialog.getByRole("button", { name: "重试读取依据" }).click();
  await dialog.locator(".job-detail-check .job-detail-quote summary").first().click();
  await expect(dialog.getByText("负责 Agent 应用开发与检索增强系统建设", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("combobox", { name: "岗位范围", exact: true }).selectOption("all");
  await expect(page.getByLabel("结果类别", { exact: true })).toHaveValue("all");
  await page.getByRole("button", { name: "Agent 基础系统研发工程师 · 火山方舟", exact: true }).click();
  await dialog.getByRole("tab", { name: "筛选依据" }).click();
  await expect(dialog.getByText("原文未说明毕业届别", { exact: true })).toBeVisible();
  expect(detailReads).toHaveLength(3);
});

test("compact white job list keeps actual fields, ignores obsolete filters and searches locally", async ({ page }, testInfo) => {
  const { writes, input } = await workspaceFixture(page);
  await page.goto("/");
  await expect(page.getByLabel("求职需求", { exact: true })).toHaveValue(input);
  await expect(page.locator(".job-list tbody tr")).toHaveCount(6);
  await expect(page.locator(".job-company").filter({ hasText: "字节跳动" })).toHaveCount(2);
  await expect(page.locator(".job-list [rowspan]")).toHaveCount(0);
  await expect(page.locator(".job-results .company-continue, .job-results .job-lead-section, .search-process")).toHaveCount(0);
  const activity = await page.locator(".search-activity").boundingBox();
  const results = await page.locator(".job-results").boundingBox();
  expect(activity!.y + activity!.height).toBeLessThan(results!.y);
  await expect(page.getByRole("combobox", { name: "地点", exact: true })).toHaveCount(0);
  await expect(page.getByRole("combobox", { name: "招聘类型", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "深圳产品实习生", exact: true })).toHaveCount(0);
  const unknown = page.locator(".job-list tr").filter({ hasText: "Agent 应用工程师" });
  await expect(unknown).toContainText("待核实");
  await expect(unknown).toContainText("未注明");
  await expect(page.getByLabel("当前求职目标")).toContainText("是否接受转专业");
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe("rgb(255, 255, 255)");
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  if (testInfo.project.name === "chromium") {
    expect((await page.locator(".job-list tbody tr").first().boundingBox())!.height).toBeLessThanOrEqual(72);
    expect((await page.locator(".workspace-topbar").boundingBox())!.height).toBeLessThanOrEqual(70);
  }
  await page.screenshot({ path: `../artifacts/search-intent-20261021/jobflow-${testInfo.project.name}.png`, fullPage: true });
  await page.getByLabel("在结果中搜索").fill("MiniMax");
  await expect(page.locator(".job-list tbody tr")).toHaveCount(1);
  await expect(page.getByLabel("岗位数量")).toHaveText("1");
  expect(writes).toEqual([]);
  await page.getByLabel("在结果中搜索").fill("不存在的岗位");
  await expect(page.getByText("没有找到匹配的公司或岗位。", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "清除关键词" }).click();
  await expect(page.locator(".job-list tbody tr")).toHaveCount(6);
});

test("history switches result scope and a new request does not mix historical jobs", async ({ page }, testInfo) => {
  await workspaceFixture(page);
  await page.goto("/");
  await expect(page.locator(".job-list tbody tr")).toHaveCount(6);
  await page.getByRole("button", { name: "搜索记录", exact: true }).click();
  const history = page.getByRole("dialog", { name: "搜索记录" });
  await expect(history).toBeVisible();
  await page.screenshot({ path: `../artifacts/search-intent-20261021/history-${testInfo.project.name}.png` });
  await expect(history.getByText("不应展示这个生成标题", { exact: true })).toHaveCount(0);
  await history.getByRole("button", { name: /深圳产品实习 查看结果/ }).click();
  await expect(history).not.toBeVisible();
  await expect(page.locator(".job-list tbody tr")).toHaveCount(1);
  await expect(page.locator(".job-title")).toHaveText(["深圳产品实习生"]);
  await expect(page.locator(".company-continue")).toHaveCount(0);
  await page.getByRole("button", { name: "搜索记录", exact: true }).click();
  await history.getByRole("button", { name: "新建搜索" }).click();
  await expect(page.getByLabel("求职需求", { exact: true })).toHaveValue("");
  await expect(page.locator(".job-list tbody tr")).toHaveCount(0);
  await expect(page.getByLabel("搜索操作")).toHaveCount(0);
});

test("whole row and keyboard open detail; save and reading recovery stay available", async ({ page }, testInfo) => {
  const { writes } = await workspaceFixture(page);
  await page.goto("/");
  await expect(page.locator(".job-list tbody tr")).toHaveCount(6);
  await page.locator(".job-company").first().click();
  const detail = page.getByRole("dialog", { name: "岗位详情" });
  await expect(detail.getByRole("tab", { name: "岗位描述" })).toHaveAttribute("aria-selected", "true");
  await expect(detail.getByRole("tabpanel", { name: "岗位描述" })).toContainText("负责 Agent 应用开发");
  await expect(detail.getByRole("heading", { name: "岗位原文" })).toBeInViewport();
  await expect(detail.getByLabel("岗位状态")).toContainText("个人资料待补充");
  await expect(detail.getByLabel("任职要求")).toHaveCount(0);
  await page.screenshot({ path: `../artifacts/job-detail-tabs-20261021/description-${testInfo.project.name}.png` });
  await detail.getByRole("tab", { name: "岗位描述" }).focus();
  await page.keyboard.press("ArrowRight");
  const evidence = detail.getByRole("tabpanel", { name: "筛选依据" });
  await expect(evidence).toBeVisible();
  await expect(detail.getByRole("tab", { name: "筛选依据" })).toBeFocused();
  await expect(evidence.getByText("原文有此要求，个人资料尚未核对", { exact: true })).toHaveCount(0);
  await expect(evidence.getByText("补充个人资料后，可核对以下任职要求。", { exact: true })).toBeVisible();
  const quote = evidence.locator(".job-detail-check .job-detail-quote").first();
  await expect(quote.locator("blockquote")).not.toBeVisible();
  await quote.locator("summary").click();
  await expect(quote.locator("blockquote")).toBeVisible();
  await page.screenshot({ path: `../artifacts/job-detail-tabs-20261021/evidence-${testInfo.project.name}.png` });
  expect(await detail.evaluate(e => e.scrollWidth - e.clientWidth)).toBeLessThanOrEqual(1);
  await detail.getByRole("button", { name: "收藏岗位" }).click();
  await expect.poll(() => writes.some(w => w.body.status === "SAVED")).toBe(true);
  await page.keyboard.press("Escape");
  const title = page.getByRole("button", { name: "RAG 研发工程师", exact: true });
  await title.focus();
  await page.keyboard.press("Enter");
  await expect(detail).toBeVisible();
  await expect(detail.getByRole("tab", { name: "岗位描述" })).toHaveAttribute("aria-selected", "true");
  await expect(detail.getByRole("tabpanel", { name: "岗位描述" })).toContainText("搜索摘要（未经正文核验）");
  await detail.getByRole("button", { name: "继续核验正文" }).click();
  await expect.poll(() => writes.some(w => w.path.endsWith("/lead/verify"))).toBe(true);
});

test("company continuation is explicit and uses the saved goal version", async ({ page }) => {
  const { writes } = await workspaceFixture(page);
  await page.goto("/");
  await page.getByLabel("搜索操作").getByRole("button", { name: "继续查找", exact: true }).click();
  await expect(page.locator(".company-continue")).toContainText("至少 7 个线索待检查");
  await page.locator(".company-continue").getByRole("button", { name: "继续查找", exact: true }).click();
  await expect.poll(() => writes.filter(w => w.path.endsWith("/search"))).toEqual([{ path: "/api/discovery/goals/agent/search", body: { expected_version: 1, continue_company_id: "bytedance" } }]);
});

test("search details retains recruitment pages and recovery independently of local job filtering", async ({ page }, testInfo) => {
  const { writes } = await workspaceFixture(page);
  await page.goto("/");
  const detailsButton = page.getByRole("button", { name: "搜索详情", exact: true });
  const continueButton = page.getByLabel("搜索操作").getByRole("button", { name: "继续查找", exact: true });
  await expect(detailsButton).toHaveAttribute("aria-expanded", "false");
  await continueButton.click();
  await expect(page.getByRole("region", { name: "选择公司继续查找" })).toBeVisible();
  await page.screenshot({ path: `../artifacts/search-intent-20261021/continue-${testInfo.project.name}.png`, fullPage: true });
  await detailsButton.click();
  await expect(continueButton).toHaveAttribute("aria-expanded", "false");
  const details = page.getByRole("region", { name: "搜索详情", exact: true });
  await expect(details.getByLabel("本轮详细统计")).toContainText("1 个招聘页面");
  await expect(details.getByRole("heading", { name: "已找到的招聘页面" })).toBeVisible();
  await page.screenshot({ path: `../artifacts/search-intent-20261021/search-details-${testInfo.project.name}.png`, fullPage: true });
  await page.getByLabel("在结果中搜索").fill("MiniMax");
  await expect(page.locator(".job-list tbody tr")).toHaveCount(1);
  await details.locator(".job-lead-section > summary").click();
  await expect(details.getByRole("link", { name: "打开原页 ↗" })).toHaveAttribute("href", "https://example.com/careers");
  await details.getByRole("button", { name: "继续寻找职位", exact: true }).click();
  await expect.poll(() => writes.some(w => w.path === "/api/discovery/leads/entry/expand")).toBe(true);
  await expect(details.getByText("本次未读取到具体职位链接，原入口已保留，可打开官网查看。", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await details.locator(".job-lead-section > summary").focus();
  await page.keyboard.press("Escape");
  await expect(detailsButton).toBeFocused();
  await expect(detailsButton).toHaveAttribute("aria-expanded", "false");
});

test("review advice keeps uncertainty and personal conflicts visible with source evidence in detail", async ({ page }) => {
  await workspaceFixture(page);
  await page.goto("/");
  const row = (title: string) => page.locator(".job-list tbody tr").filter({ has: page.getByRole("button", { name: title, exact: true }) });
  const recommended = row("Agent 基础系统研发工程师 · 火山方舟");
  await expect(recommended.locator(".job-advice-label")).toHaveText("推荐查看");
  await expect(recommended.locator(".job-advice-reason")).toHaveText("方向、地点符合 · 届别待确认");
  const conflict = row("大模型应用开发实习生");
  await expect(conflict.locator(".job-advice-label")).toHaveText("存在门槛冲突");
  await expect(conflict.locator(".job-advice-reason")).toHaveText("要求硕士及以上，当前资料为本科");
  await expect(row("RAG 研发工程师").locator(".job-advice-label")).toHaveText("待核验");
  await expect(row("Agent 应用工程师").locator(".job-advice-reason")).toHaveText("地点待确认 · 招聘类型待确认");
  await conflict.locator(".job-title").click();
  const detail = page.getByRole("dialog", { name: "岗位详情" });
  await expect(detail.getByLabel("岗位状态")).toContainText("要求硕士及以上，当前资料为本科");
  await expect(detail.getByRole("heading", { name: "岗位原文" })).toBeInViewport();
  await detail.getByRole("tab", { name: "筛选依据" }).click();
  await expect(detail.getByLabel("任职要求")).toContainText("硕士及以上学历");
  const quotedCheck = detail.locator(".job-detail-check .job-detail-quote").first();
  await quotedCheck.locator("summary").click();
  await expect(quotedCheck.locator("blockquote")).toHaveText("负责 Agent 应用开发与检索增强系统建设");
  await page.keyboard.press("Escape");
  await page.locator(".result-options > summary").click();
  await page.getByRole("checkbox", { name: "显示不符或已关闭的岗位" }).check();
  await expect(row("已关闭的岗位").locator(".job-advice-label")).toHaveText("已关闭");
  await page.getByRole("combobox", { name: "岗位范围", exact: true }).selectOption("all");
  await expect(row("深圳产品实习生").locator(".job-advice-reason")).toHaveText("尚未按当前需求核对");
});
