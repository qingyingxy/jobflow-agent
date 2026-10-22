import { expect, test, type Page } from "@playwright/test";

async function fixture(page: Page) {
  const now = new Date().toISOString();
  const goal = { id: "tracking-goal", name: "Agent 校招", input_text: "2027 届 AI Agent / RAG 校招，地点不限", query: "Agent 校招", version: 1,
    conditions: { locations: [], preferred_locations: [], excluded_locations: [], roles: ["ai agent", "rag"], excluded_roles: [], job_types: ["校招"], excluded_job_types: [], graduation_years: [2027], keywords: [], pending_conditions: [] },
    condition_sources: {}, company_ids: null, update_interval_minutes: 0, next_update_at: null as string | null };
  const job = { id: "tracking-job", company: "测试公司", title: "Agent 应用开发工程师", locations: ["北京"], job_type: "campus", source_url: "https://example.com/jobs/agent", verification_status: "VERIFIED_OFFICIAL", availability_status: "ACTIVE", raw_content: "负责 Agent 工具调用、任务执行与可靠性改进。面向 2027 届毕业生。" };
  const candidate = { id: "tracking-candidate", user_id: "local-user", job_posting_id: job.id, status: "DISCOVERED", available_transitions: ["SAVED", "IGNORED"], job, analysis: null, created_at: now, updated_at: now };
  const application = { id: "tracking-application", candidate_job_id: candidate.id, job_posting_id: job.id, status: "SUBMITTED", candidate_status: "CONVERTED", next_action: null, available_transitions: ["INTERVIEW", "WITHDRAWN"], job, events: [], created_at: now, updated_at: now };
  const scheduled = new Date(Date.now() + 20 * 60_000).toISOString();
  const task = { id: "tracking-task", application_id: application.id, job_posting_id: job.id, title: "技术面试", company: job.company, job_title: job.title, event_type: "INTERVIEW", scheduled_at: scheduled, local_scheduled_at: scheduled,
    reminder_at: new Date(Date.now() - 10 * 60_000).toISOString(), timezone: "Asia/Shanghai", duration_minutes: 60, all_day: false, is_overdue: false, next_action: "准备项目复盘", status: "PENDING", base_status: "PENDING", available_actions: ["edit", "complete", "cancel"], created_at: now, updated_at: now };
  const mutations: string[] = [];
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id", "access-control-allow-methods": "GET,POST,PUT,PATCH,OPTIONS" };
    const json = (data: unknown) => route.fulfill({ headers, json: data });
    if (method === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (method !== "GET") mutations.push(`${method} ${path}`);
    if (path === "/api/tracking/summary") return json({ checked_at: now, scheduler_running: true, searches: [{ goal, latest_run: { id: "tracking-run", status: "SUCCEEDED", started_at: now, finished_at: now, new_count: 1 } }], tasks: [task], counts: { scheduled_goals: goal.update_interval_minutes ? 1 : 0, today: 1, overdue: 0, attention: 1 } });
    if (path.endsWith("/schedule")) {
      goal.update_interval_minutes = route.request().postDataJSON().interval_minutes;
      goal.next_update_at = new Date(Date.now() + goal.update_interval_minutes * 60_000).toISOString();
      return json(goal);
    }
    if (path === "/api/discovery/goals") return json([goal]);
    if (path.endsWith("/library")) return json({ goal_id: goal.id, goal_version: 1, query: goal.query, latest_run_id: null, lead_ids: [], counts: { matched: 1 },
      result_matches: [{ job_posting_id: job.id, filter_status: "matched", match_tier: "strict", mismatch_reasons: [], mismatch_labels: [], checks: [] }], updates: [{ kind: "new", job_posting_id: job.id, company: job.company, title: job.title }] });
    if (path === "/api/candidates") return json(method === "GET" ? [candidate] : candidate);
    if (path.endsWith("/prepare-application")) { application.status = "PREPARING"; return json(application); }
    if (path === "/api/applications") return json([application]);
    if (path === `/api/jobs/${job.id}`) return json(job);
    if (path.endsWith("/analysis")) return json(null);
    if (path.endsWith("/calendar")) return route.fulfill({ headers: { ...headers, "content-type": "text/calendar", "content-disposition": "attachment; filename=jobflow-follow-up.ics" }, body: "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n" });
    if (path === "/api/follow-ups") return json([task]);
    if (path === "/api/follow-ups/summary") return json({ timezone: "Asia/Shanghai", generated_at: now, total_pending: 1, today: 1, overdue: 0, next_7_days: 1, next_30_days: 1 });
    return json([]);
  });
  return { mutations };
}

test("tracking schedules persist, show changes, and reopen the saved target", async ({ page }, testInfo) => {
  const { mutations } = await fixture(page);
  await page.goto("/");
  await page.getByRole("button", { name: /^追踪动态/ }).click();
  const dialog = page.getByRole("dialog", { name: "追踪动态", exact: true });
  await dialog.getByLabel("Agent 校招的更新频率").selectOption("60");
  await expect(dialog.getByLabel("Agent 校招的更新频率")).toHaveValue("60");
  await expect(dialog.getByText(/^下一次：/)).toBeVisible();
  await dialog.getByRole("button", { name: "查看本轮新增与变化" }).click();
  await expect(dialog.locator(".tracking-changes")).toContainText("Agent 应用开发工程师");
  await page.screenshot({ path: `../artifacts/tracking-20261021/jobs-${testInfo.project.name}.png` });
  await expect(dialog).toHaveJSProperty("scrollWidth", await dialog.evaluate(el => el.clientWidth));
  await dialog.getByRole("button", { name: "查看岗位", exact: true }).click();
  await expect(page.getByLabel("求职需求")).toHaveValue("2027 届 AI Agent / RAG 校招，地点不限");
  await page.reload();
  await page.getByRole("button", { name: /^追踪动态/ }).click();
  await expect(dialog.getByLabel("Agent 校招的更新频率")).toHaveValue("60");
  expect(mutations).toEqual(["PUT /api/discovery/goals/tracking-goal/schedule"]);
});

test("reminders require opt-in, deduplicate after reload and export a scoped calendar", async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    const calls: string[] = [];
    Object.assign(window, { testNotifications: calls });
    Object.defineProperty(window, "Notification", { value: class {
      static permission = "default";
      static async requestPermission() { this.permission = "granted"; return "granted"; }
      constructor(title: string) { calls.push(title); }
      close() {}
    }, configurable: true });
    localStorage.setItem("jobflow:tracking-notified:local-user", localStorage.getItem("jobflow:tracking-notified:local-user") || "null");
  });
  await fixture(page);
  await page.goto("/");
  await page.getByRole("button", { name: /^追踪动态/ }).click();
  const dialog = page.getByRole("dialog", { name: "追踪动态", exact: true });
  await dialog.getByRole("tab", { name: "投递跟进" }).click();
  expect(await page.evaluate(() => (window as unknown as { testNotifications: string[] }).testNotifications)).toEqual([]);
  await dialog.getByRole("button", { name: "开启桌面提醒" }).click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { testNotifications: string[] }).testNotifications)).toEqual(["技术面试"]);
  await page.evaluate(() => window.dispatchEvent(new Event("jobflow:tracking-changed")));
  await page.screenshot({ path: `../artifacts/tracking-20261021/tasks-${testInfo.project.name}.png` });
  await dialog.getByRole("button", { name: "查看跟进" }).click();
  await expect(dialog.getByLabel("关联申请")).toHaveValue("tracking-application");
  await expect(dialog.getByText("技术面试", { exact: true })).toBeVisible();
  const download = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "导出日历 技术面试" }).click();
  expect((await download).suggestedFilename()).toMatch(/\.ics$/);
  await expect(dialog).toHaveJSProperty("scrollWidth", await dialog.evaluate(el => el.clientWidth));
  await page.screenshot({ path: `../artifacts/tracking-20261021/followup-${testInfo.project.name}.png` });
  await page.reload();
  await page.getByRole("button", { name: /^追踪动态/ }).click();
  await dialog.getByRole("tab", { name: "投递跟进" }).click();
  await dialog.getByRole("button", { name: "开启桌面提醒" }).click();
  await expect(dialog.getByRole("button", { name: "关闭桌面提醒" })).toBeVisible();
  expect(await page.evaluate(() => (window as unknown as { testNotifications: string[] }).testNotifications)).toEqual([]);
});

test("job detail can enter application tracking without running a model or recording submission", async ({ page }) => {
  const { mutations } = await fixture(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Agent 应用开发工程师", exact: true }).click();
  await page.getByRole("button", { name: "加入申请进度", exact: true }).click();
  await expect(page.getByLabel("申请状态看板")).toBeVisible();
  await expect(page.getByText("已经在官网投递？记录一下", { exact: true })).toBeVisible();
  expect(mutations).toEqual(["POST /api/candidates", "POST /api/candidates/tracking-candidate/prepare-application"]);
});
