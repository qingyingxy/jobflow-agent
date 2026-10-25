import { expect, test, type Page } from "@playwright/test";
import type { Campaign, CampaignCompanyCard } from "../app/campaign-workspace";

const now = "2026-10-22T08:00:00Z";
async function fixture(page: Page, withJudgment = false) {
  const mutations: { path: string; body: Record<string, unknown> }[] = [];
  const presenceOverrides = new Map<string, "empty" | "unknown">();
  const discovery = { enabled: true, status: "idle", stage: "search", queries_completed: 0, queries_total: 0,
    companies_found: 0, companies_verified: 0, companies_queued: 0,
    pending_companies: [] as { company: string; reason: string }[], next_run_at: null, error: null };
  const companies = ["百度", "小米"].map((company, i) => ({ company_id: ["baidu", "xiaomi"][i], company,
    career_url: "https://example.com/campus", followed: false, status: "ready", checked_at: now,
    succeeded_at: now, next_check_at: null as string | null, error: null }));
  const campaigns: Campaign[] = companies.map((c, i) => ({ ...c, id: `campaign-${i}`, year: 2027,
    title: `${c.company}2027届秋季校园招聘启动`, batch: "autumn", batch_label: "秋招",
    source_url: "https://example.com/notice", status: "open", first_seen_at: now,
    last_seen_at: now, changed_at: now, latest_event: { kind: "first_seen", at: now },
    facts: { year_quote: "面向2027届毕业生", batch_quote: "2027届秋季校园招聘", status_quote: i ? "网申进行中" : "秋招正式启动",
      published: i === 0 ? { value: "2026-10-20", quote: "发布日期2026年10月20日" } : null,
      starts: i === 0 ? { value: "2026-10-20", quote: "网申开始2026年10月20日" } : null,
      deadline: i === 0 ? { value: "2026-11-30", quote: "网申截止2026年11月30日" } : null,
      directions: i ? ["研发", "设计"] : ["算法", "产品"] } }));
  const goals = [{ id: "existing", name: "AI校招", input_text: "2027届AI Agent校招，地点不限", query: "2027届AI Agent校招", version: 1,
    company_ids: null, condition_sources: {}, conditions: { roles: ["AI Agent"], graduation_years: [2027],
      locations: [], preferred_locations: [], excluded_locations: [], excluded_roles: [], job_types: ["校招"],
      excluded_job_types: [], keywords: [], pending_conditions: [] } }];
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const url = new URL(route.request().url()), path = url.pathname, method = route.request().method();
    const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id", "access-control-allow-methods": "GET,POST,PUT,PATCH,OPTIONS" };
    const json = (data: unknown, status = 200) => route.fulfill({ headers, json: data, status });
    if (method === "OPTIONS") return json({});
    const body = method === "GET" ? {} : route.request().postDataJSON();
    if (method !== "GET") mutations.push({ path, body });
    if (path.startsWith("/api/campaigns")) {
      if (path.endsWith("/watch")) {
        const source = companies.find(c => path.includes(c.company_id))!;
        source.followed = body.followed; source.next_check_at = body.followed ? "2026-10-22T09:00:00Z" : null;
      }
      const year = Number(url.searchParams.get("year") || body.year || 2027);
      if (path.endsWith("/discover")) Object.assign(discovery, { status: "queued", queries_total: 4 });
      const companyCards: CampaignCompanyCard[] = companies.map(company => {
        const evidence = year === 2027 ? campaigns.filter(c => c.company_id === company.company_id) : [];
        const sample = evidence.find(c => c.status === "open") || evidence[0];
        return { ...company, year, recruitment_status: presenceOverrides.get(company.company_id) || (sample?.status === "open" ? "open" : "unknown"),
          recruitment_url: company.career_url, status_note: sample ? "官网已发现校招岗位" : "尚未检查校招岗位",
          cohort_status: sample?.cohort_status || "confirmed", availability_checked_at: sample?.availability_checked_at || now,
          availability_stale: sample?.availability_stale || false, first_seen_at: sample?.first_seen_at || null,
          job_titles: sample?.status === "open" && !presenceOverrides.has(company.company_id) ? ["软件工程师"] : [],
          opening_date: sample?.facts.starts?.value || null, directions: sample?.facts.directions || [],
          evidence_ids: evidence.map(c => c.id), evidence_count: evidence.length,
          ...(withJudgment ? { judgment_reason: "已读官方校招列表中有实际软件工程师岗位。",
            citations: [{ url: "https://example.com/campus/jobs", quote: "2027届校园招聘：软件工程师" }] } : {}) };
      });
      return json({ year, companies, company_cards: companyCards, campaigns: year === 2027 ? campaigns : [], discovery },
        ["refresh", "discover"].some(s => path.endsWith(s)) ? 202 : 200);
    }
    if (path === "/api/tracking/summary") return json({ checked_at: now, scheduler_running: true, searches: [], tasks: [],
      campaign_watches: companies.filter(c => c.followed).map(c => ({ ...c, year: 2027 })), counts: { today: 0, overdue: 0, attention: 0, scheduled_goals: 0 } });
    if (path === "/api/discovery/goals") {
      if (method === "POST") return json({ ...goals[0], ...body, id: "company-goal", query: "2027届 AI Agent 校招", version: 1 });
      return json(goals);
    }
    if (path.endsWith("/search")) return json({ id: "campaign-run", status: "SUCCEEDED", search_goal_id: "company-goal", search_goal_version: 1,
      result_matches: [], agent_trace: [], created_at: now, started_at: now, finished_at: now, new_count: 0, discovered_count: 0, analysis_target_count: 0, source_mode: "web", search_query: "2027届 AI Agent 校招" });
    if (path.endsWith("/library")) return json({ goal_id: "existing", goal_version: 1, query: goals[0].query, latest_run_id: null, result_matches: [], lead_ids: [], counts: {}, updates: [] });
    return json([]);
  });
  return { mutations, campaigns, discovery, presenceOverrides };
}

test("company card shows the agent judgment and cited source", async ({ page }) => {
  await fixture(page, true);
  await page.goto("/");
  await page.getByRole("tab", { name: "看秋招", exact: true }).click();
  const card = page.getByRole("article", { name: "百度校招", exact: true });
  await card.getByText("判断依据", { exact: true }).click();
  await expect(card.getByText("已读官方校招列表中有实际软件工程师岗位。", { exact: true })).toBeVisible();
  await expect(card.getByText("2027届校园招聘：软件工程师", { exact: true })).toBeVisible();
  await expect(card.getByRole("link", { name: "查看来源 ↗", exact: true })).toHaveAttribute("href", "https://example.com/campus/jobs");
});

test("two discovery modes show announcement dates and grounded details", async ({ page }, testInfo) => {
  const { mutations } = await fixture(page);
  await page.goto("/");
  await expect(page.getByRole("tab", { name: "找岗位", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "看秋招", exact: true }).click();
  await expect(page.getByRole("heading", { name: "哪些公司有校招岗位" })).toBeVisible();
  await expect(page.getByText("有校招岗位优先 · 2 家公司", { exact: true })).toBeVisible();
  await expect(page.getByText("已知网申开始：2026-10-20", { exact: true })).toBeVisible();
  await expect(page.getByText("开放时间未确认", { exact: true })).toHaveCount(0);
  await expect(page.getByText("新开放", { exact: true })).toHaveCount(0);
  await page.getByRole("article", { name: "百度校招", exact: true }).locator("summary").click();
  await page.getByRole("button", { name: "百度2027届秋季校园招聘启动", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "公告依据" });
  await expect(dialog.getByText("面向2027届毕业生", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "关闭公告依据" }).click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await page.screenshot({ path: `../artifacts/campaign-jobs-20261024/companies-${testInfo.project.name}.png`, fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  expect(mutations).toEqual([]);
});

test("company cards aggregate different programs and keep closed evidence collapsed", async ({ page }, testInfo) => {
  const { campaigns, mutations } = await fixture(page);
  campaigns.push(
    { ...campaigns[0], id: "upcoming", title: "百度2027届专项计划", status: "upcoming", facts: { ...campaigns[0].facts,
      starts: { value: "2026-10-25", quote: "网申开始2026年10月25日" } } },
    { ...campaigns[1], id: "pending", title: "小米2027届专项计划", status: "announced", facts: { ...campaigns[1].facts,
      published: { value: "2026-10-21", quote: "发布日期2026年10月21日" } } },
    { ...campaigns[0], id: "closed", title: "百度2027届提前批", status: "closed" },
  );
  await page.goto("/");
  await page.getByRole("tab", { name: "看秋招", exact: true }).click();
  await expect(page.locator(".campaign-card:visible")).toHaveCount(2);
  await expect(page.getByRole("article", { name: "百度校招", exact: true }).getByText("有校招岗位", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "百度2027届提前批", exact: true })).not.toBeVisible();
  await page.getByRole("article", { name: "百度校招", exact: true }).locator("summary").click();
  await expect(page.getByRole("button", { name: "百度2027届提前批", exact: true })).toBeVisible();
  await page.getByRole("article", { name: "百度校招", exact: true }).locator("summary").click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await page.screenshot({ path: `../artifacts/campaign-jobs-20261024/states-${testInfo.project.name}.png`, fullPage: true });
  await page.getByRole("checkbox", { name: "只看有岗位" }).check();
  await expect(page.locator(".campaign-card:visible")).toHaveCount(2);
  await expect(page.locator(".campaign-closed")).toHaveCount(0);
  await page.getByRole("searchbox", { name: "搜索秋招公司" }).fill("小米");
  await expect(page.locator(".campaign-card:visible")).toHaveCount(1);
  await page.getByRole("button", { name: /^我关注的/ }).click();
  await expect(page.getByText("当前范围暂无已发现校招岗位的公司", { exact: true })).toBeVisible();
  await expect(page.getByText("还没有收录这一届的秋招公告", { exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  expect(mutations).toEqual([]);
});

test("empty campus lists and unreadable companies stay distinct and out of the jobs filter", async ({ page }) => {
  const { presenceOverrides, mutations } = await fixture(page);
  presenceOverrides.set("baidu", "empty");
  presenceOverrides.set("xiaomi", "unknown");
  await page.goto("/");
  await page.getByRole("tab", { name: "看秋招", exact: true }).click();
  await expect(page.getByRole("article", { name: "百度校招", exact: true }).getByText("暂未发现校招岗位", { exact: true })).toBeVisible();
  await expect(page.getByRole("article", { name: "小米校招", exact: true }).getByText("待确认", { exact: true })).toBeVisible();
  await page.getByRole("checkbox", { name: "只看有岗位" }).check();
  await expect(page.locator(".campaign-card:visible")).toHaveCount(0);
  expect(mutations).toEqual([]);
});

test("following a company is shared with tracking and can be undone", async ({ page }) => {
  const { mutations } = await fixture(page);
  await page.goto("/");
  await page.getByRole("tab", { name: "看秋招", exact: true }).click();
  await page.locator(".campaign-card").filter({ hasText: "百度" }).getByRole("button", { name: "关注公司", exact: true }).click();
  await page.getByRole("button", { name: /^我关注的/ }).click();
  await expect(page.locator(".campaign-card")).toHaveCount(1);
  await page.getByRole("button", { name: /^追踪动态/ }).click();
  const dialog = page.getByRole("dialog", { name: "追踪动态", exact: true });
  await dialog.getByRole("tab", { name: "秋招追踪" }).click();
  await expect(dialog.getByText("百度 · 2027 届", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "查看秋招动态" }).click();
  await page.locator(".campaign-card").filter({ hasText: "百度" }).getByRole("button", { name: "已关注", exact: true }).click();
  expect(mutations.map(m => m.body.followed)).toEqual([true, false]);
});

test("verified entry links show scope and unspecified cohort without launching another search", async ({ page }, testInfo) => {
  const { campaigns, mutations } = await fixture(page);
  campaigns[0] = { ...campaigns[0], cohort_status: "unspecified", availability_scope: "job",
    application_url: "https://example.com/campus/position/123", entry_url: "https://example.com/campus/position/123",
    availability_checked_at: now, availability_stale: false,
    facts: { ...campaigns[0].facts, year_quote: "", entry: { title: "算法工程师", quote: "立即投递",
      campus_quote: "校园招聘", year_quote: "", origin_url: "https://example.com/campus", link_text: "应届投递", checked_at: now } } };
  campaigns[1] = { ...campaigns[1], status: "unknown", application_url: null,
    entry_url: "https://example.com/campus/position/456", availability_checked_at: "2026-10-19T08:00:00Z", availability_stale: true };
  await page.goto("/");
  await page.getByRole("tab", { name: "看秋招", exact: true }).click();
  const verified = page.locator(".campaign-card").filter({ hasText: "百度" });
  await expect(verified.getByText("届别待核实", { exact: true })).toBeVisible();
  await expect(verified.getByText("有校招岗位", { exact: true })).toBeVisible();
  await expect(verified.getByRole("link", { name: "官方招聘入口 ↗", exact: true })).toHaveAttribute("href", "https://example.com/campus");
  await verified.locator("summary").click();
  await expect(verified.getByRole("link", { name: "该岗位或项目的投递入口 ↗", exact: true })).toHaveAttribute("href", "https://example.com/campus/position/123");
  const stale = page.locator(".campaign-card").filter({ hasText: "小米" });
  await expect(stale.getByRole("link", { name: "前往投递 ↗", exact: true })).toHaveCount(0);
  await expect(stale.getByRole("link", { name: "官方招聘入口 ↗", exact: true })).toHaveAttribute("href", "https://example.com/campus");
  await expect(stale.getByText(/待重新检查，上次读取/)).toBeVisible();
  await verified.getByRole("button", { name: campaigns[0].title, exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "公告依据" });
  await expect(dialog.getByRole("heading", { name: "官网岗位依据" })).toBeVisible();
  await expect(dialog.getByText("立即投递", { exact: true })).toBeVisible();
  await expect(dialog.getByRole("link", { name: "应届投递 ↗", exact: true })).toHaveAttribute("href", "https://example.com/campus");
  await dialog.getByRole("button", { name: "关闭公告依据" }).click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await page.screenshot({ path: `../artifacts/campaign-jobs-20261024/entries-${testInfo.project.name}.png`, fullPage: true });
  await page.getByRole("checkbox", { name: "只看有岗位" }).check();
  await expect(page.locator(".campaign-card")).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  expect(mutations).toEqual([]);
});

test("refresh is explicit and changing cohort does not launch network discovery", async ({ page }) => {
  const { mutations } = await fixture(page);
  await page.goto("/");
  await page.getByRole("tab", { name: "看秋招", exact: true }).click();
  await page.getByLabel("秋招毕业届别").selectOption("2028");
  await expect(page.getByText("尚未检查校招岗位", { exact: true })).toHaveCount(2);
  expect(mutations).toHaveLength(0);
  await page.getByRole("button", { name: "检查已收录公司", exact: true }).click();
  expect(mutations).toEqual([{ path: "/api/campaigns/refresh", body: { year: 2028 } }]);
});

test("related jobs carries company cohort and the saved role into job search", async ({ page }) => {
  const { mutations } = await fixture(page);
  await page.goto("/");
  await expect(page.getByLabel("求职需求")).toHaveValue("2027届AI Agent校招，地点不限");
  await page.getByRole("tab", { name: "看秋招", exact: true }).click();
  await page.locator(".campaign-card").filter({ hasText: "百度" }).getByRole("button", { name: "查看相关岗位", exact: true }).click();
  await expect(page.getByRole("tab", { name: "找岗位", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect.poll(() => mutations.length).toBe(2);
  expect(mutations[0].body.company_ids).toEqual(["baidu"]);
  expect(mutations[0].body.conditions).toMatchObject({ roles: ["AI Agent"], graduation_years: [2027], job_types: ["校招"] });
  expect(mutations[1].path).toBe("/api/discovery/goals/company-goal/search");
});

test("company discovery sends only the selected cohort and prevents duplicate starts", async ({ page }) => {
  const { mutations } = await fixture(page);
  await page.goto("/");
  await page.getByRole("tab", { name: "看秋招", exact: true }).click();
  await page.getByLabel("秋招毕业届别").selectOption("2028");
  await expect(page.getByText("尚未检查校招岗位", { exact: true })).toHaveCount(2);
  expect(mutations).toEqual([]);
  await page.getByRole("button", { name: "发现更多公司", exact: true }).click();
  await expect(page.getByRole("button", { name: "正在发现公司…", exact: true })).toBeDisabled();
  await expect(page.getByText(/搜索进度 0\/4/)).toBeVisible();
  expect(mutations).toEqual([{ path: "/api/campaigns/discover", body: { year: 2028 } }]);
});

test("unverified discoveries are pending and do not appear as open companies", async ({ page }) => {
  const { discovery } = await fixture(page);
  Object.assign(discovery, { status: "queued", stage: "verify", companies_found: 1,
    pending_companies: [{ company: "新发现企业", reason: "官网归属待核验" }] });
  await page.goto("/");
  await page.getByRole("tab", { name: "看秋招", exact: true }).click();
  await expect(page.getByRole("article", { name: "新发现企业校招" })).toHaveCount(0);
  await page.locator(".campaign-discovery-progress summary").click();
  await expect(page.getByText("新发现企业：官网归属待核验", { exact: true })).toBeVisible();
});

test("waiting for company verification still allows discovering another batch", async ({ page }) => {
  const { discovery, mutations } = await fixture(page);
  Object.assign(discovery, { status: "waiting", stage: "verify", queries_completed: 4, queries_total: 4,
    pending_companies: [{ company: "待复核企业", reason: "官网暂时无法读取" }] });
  await page.goto("/");
  await page.getByRole("tab", { name: "看秋招", exact: true }).click();
  await expect(page.getByText(/可继续发现更多公司/)).toBeVisible();
  await page.getByRole("button", { name: "发现更多公司", exact: true }).click();
  expect(mutations).toEqual([{ path: "/api/campaigns/discover", body: { year: 2027 } }]);
});
