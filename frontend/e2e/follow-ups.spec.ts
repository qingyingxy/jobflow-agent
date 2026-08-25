import { expect, test, type Page } from "@playwright/test";

type BaseStatus = "PENDING" | "COMPLETED" | "CANCELLED";

type FollowUpTask = {
  id: string;
  application_id: string;
  job_posting_id: string;
  event_type: string;
  title: string;
  scheduled_at: string;
  local_scheduled_at: string;
  timezone: string;
  duration_minutes: number | null;
  all_day: boolean;
  contact_name: string | null;
  contact_detail: string | null;
  channel: string | null;
  next_action: string;
  notes: string | null;
  base_status: BaseStatus;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  cancelled_at: string | null;
};

function localDate(offset: number): string {
  const date = new Date();
  date.setHours(12, 0, 0, 0);
  date.setDate(date.getDate() + offset);
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-");
}

function localTimestamp(offset: number, time: string): string {
  return `${localDate(offset)}T${time}:00+08:00`;
}

function makeTask(
  id: string,
  title: string,
  offset: number,
  time: string,
  nextAction: string,
): FollowUpTask {
  const timestamp = localTimestamp(offset, time);
  return {
    id,
    application_id: "application_follow_up_demo",
    job_posting_id: "job_follow_up_demo",
    event_type: "INTERVIEW",
    title,
    scheduled_at: timestamp,
    local_scheduled_at: timestamp,
    timezone: "Asia/Shanghai",
    duration_minutes: 60,
    all_day: false,
    contact_name: "陈老师",
    contact_detail: "meeting-2026",
    channel: "腾讯会议",
    next_action: nextAction,
    notes: null,
    base_status: "PENDING",
    created_at: timestamp,
    updated_at: timestamp,
    completed_at: null,
    cancelled_at: null,
  };
}

async function installFollowUpFixture(page: Page) {
  const tasks: FollowUpTask[] = [
    makeTask("follow_up_overdue", "补发感谢邮件", -1, "10:00", "整理面试要点并发送邮件"),
    makeTask("follow_up_today", "技术一面", 0, "23:00", "准备系统设计案例"),
    makeTask("follow_up_cancel", "招聘经理沟通", 1, "11:00", "确认团队职责范围"),
  ];
  const headers = {
    "access-control-allow-origin": "http://localhost:3000",
    "access-control-allow-headers": "content-type,x-user-id",
    "access-control-allow-methods": "GET,POST,PATCH,OPTIONS",
    "content-type": "application/json",
  };
  const application = {
    id: "application_follow_up_demo",
    candidate_job_id: "candidate_follow_up_demo",
    job_posting_id: "job_follow_up_demo",
    status: "SUBMITTED",
    candidate_status: "CONVERTED",
    next_action: null,
    available_transitions: ["ASSESSMENT", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN"],
    job: {
      id: "job_follow_up_demo",
      company: "Calendar Labs",
      title: "Reliability Engineer",
      source_url: "https://careers.example.com/jobs/reliability-engineer",
      verification_status: "VERIFIED_OFFICIAL",
      availability_status: "ACTIVE",
    },
    events: [],
    created_at: localTimestamp(-5, "09:00"),
    updated_at: localTimestamp(-1, "10:00"),
  };

  function isOverdue(task: FollowUpTask): boolean {
    return task.base_status === "PENDING" && new Date(task.scheduled_at).getTime() < Date.now();
  }

  function response(task: FollowUpTask) {
    const overdue = isOverdue(task);
    return {
      ...task,
      status: overdue ? "OVERDUE" : task.base_status,
      is_overdue: overdue,
      available_actions: task.base_status === "PENDING" ? ["edit", "complete", "cancel"] : [],
    };
  }

  function visible(view: string): FollowUpTask[] {
    const today = localDate(0);
    const sevenDayEnd = localDate(7);
    const thirtyDayEnd = localDate(30);
    return tasks.filter((task) => {
      if (view === "all") return true;
      if (task.base_status !== "PENDING") return false;
      const day = task.local_scheduled_at.slice(0, 10);
      if (view === "today") return day === today;
      if (view === "overdue") return isOverdue(task);
      if (view === "next_7_days") return !isOverdue(task) && day >= today && day < sevenDayEnd;
      if (view === "next_30_days") return !isOverdue(task) && day >= today && day < thirtyDayEnd;
      return true;
    });
  }

  await page.route("http://127.0.0.1:18001/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 200, headers, body: "" });
      return;
    }
    if (path === "/api/applications" && request.method() === "GET") {
      await route.fulfill({ headers, json: [application] });
      return;
    }
    if (path === "/api/follow-ups" && request.method() === "GET") {
      await route.fulfill({ headers, json: visible(url.searchParams.get("view") ?? "all").map(response) });
      return;
    }
    if (path === "/api/follow-ups/summary" && request.method() === "GET") {
      await route.fulfill({
        headers,
        json: {
          timezone: "Asia/Shanghai",
          generated_at: new Date().toISOString(),
          total_pending: tasks.filter((task) => task.base_status === "PENDING").length,
          today: visible("today").length,
          overdue: visible("overdue").length,
          next_7_days: visible("next_7_days").length,
          next_30_days: visible("next_30_days").length,
        },
      });
      return;
    }
    if (path === `/api/applications/${application.id}/follow-ups` && request.method() === "POST") {
      const body = request.postDataJSON() as Record<string, unknown>;
      const local = `${body.scheduled_at as string}:00+08:00`;
      const task: FollowUpTask = {
        id: "follow_up_created",
        application_id: application.id,
        job_posting_id: application.job_posting_id,
        event_type: body.event_type as string,
        title: body.title as string,
        scheduled_at: local,
        local_scheduled_at: local,
        timezone: body.timezone as string,
        duration_minutes: body.duration_minutes as number | null,
        all_day: body.all_day as boolean,
        contact_name: body.contact_name as string | null,
        contact_detail: body.contact_detail as string | null,
        channel: body.channel as string | null,
        next_action: body.next_action as string,
        notes: body.notes as string | null,
        base_status: "PENDING",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        completed_at: null,
        cancelled_at: null,
      };
      tasks.push(task);
      await route.fulfill({ status: 201, headers, json: response(task) });
      return;
    }
    const taskMatch = path.match(/^\/api\/follow-ups\/([^/]+)$/);
    if (taskMatch && request.method() === "PATCH") {
      const task = tasks.find((item) => item.id === taskMatch[1]);
      const body = request.postDataJSON() as Record<string, unknown>;
      if (!task) {
        await route.fulfill({ status: 404, headers, json: { detail: "not found" } });
        return;
      }
      Object.assign(task, body, {
        local_scheduled_at: body.scheduled_at ? `${body.scheduled_at as string}:00+08:00` : task.local_scheduled_at,
        scheduled_at: body.scheduled_at ? `${body.scheduled_at as string}:00+08:00` : task.scheduled_at,
        updated_at: new Date().toISOString(),
      });
      await route.fulfill({ headers, json: response(task) });
      return;
    }
    const transitionMatch = path.match(/^\/api\/follow-ups\/([^/]+)\/(complete|cancel)$/);
    if (transitionMatch && request.method() === "POST") {
      const task = tasks.find((item) => item.id === transitionMatch[1]);
      if (!task) {
        await route.fulfill({ status: 404, headers, json: { detail: "not found" } });
        return;
      }
      task.base_status = transitionMatch[2] === "complete" ? "COMPLETED" : "CANCELLED";
      task.completed_at = task.base_status === "COMPLETED" ? new Date().toISOString() : null;
      task.cancelled_at = task.base_status === "CANCELLED" ? new Date().toISOString() : null;
      await route.fulfill({ headers, json: response(task) });
      return;
    }
    await route.fulfill({ status: 200, headers, json: [] });
  });
}

test("follow-up center manages the full manual task lifecycle", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await installFollowUpFixture(page);
  await page.goto("/");
  await page.getByRole("button", { name: /跟进中心/ }).click();

  await expect(page.getByRole("heading", { name: "今日任务" })).toBeVisible();
  await expect(page.getByText("技术一面", { exact: true })).toBeVisible();
  await expect(page.getByText("补发感谢邮件", { exact: true })).toBeHidden();

  await page.getByRole("tab", { name: /逾期/ }).click();
  await expect(page.getByText("补发感谢邮件", { exact: true })).toBeVisible();
  await expect(page.getByText("已逾期", { exact: true })).toBeVisible();

  await page.getByLabel("标题").fill("HR 终面");
  await page.getByLabel("日期与时间").fill(`${localDate(2)}T14:30`);
  await page.getByLabel("下一步动作").fill("准备薪资沟通问题清单");
  await page.getByLabel("渠道").fill("视频会议");
  await page.getByRole("button", { name: "创建跟进任务" }).click();
  await expect(page.getByRole("status")).toContainText("跟进任务已创建");

  await page.getByRole("tab", { name: /未来 30 天/ }).click();
  await page.getByRole("button", { name: new RegExp(localDate(2)) }).click();
  await expect(page.getByText("HR 终面", { exact: true })).toBeVisible();
  await expect(page.getByText("招聘经理沟通", { exact: true })).toBeHidden();

  await page.getByLabel("编辑 HR 终面").click();
  await page.getByLabel("标题").fill("HR 终面（已确认）");
  await page.getByLabel("下一步动作").fill("确认会议链接并准备薪资沟通问题清单");
  await page.getByRole("button", { name: "保存修改" }).click();
  await expect(page.getByText("HR 终面（已确认）", { exact: true })).toBeVisible();

  await page.getByLabel("完成 HR 终面（已确认）").click();
  await page.getByRole("tab", { name: /全部记录/ }).click();
  await expect(page.getByText("HR 终面（已确认）", { exact: true })).toBeVisible();
  await expect(page.getByText("已完成", { exact: true })).toBeVisible();

  await page.getByLabel("取消 招聘经理沟通").click();
  await expect(page.getByText("已取消", { exact: true })).toBeVisible();

  const hasHorizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(hasHorizontalOverflow).toBe(false);
  expect(consoleErrors).toEqual([]);
});
