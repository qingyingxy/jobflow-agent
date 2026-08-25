import { expect, test, type Page } from "@playwright/test";

const now = "2026-08-25T10:00:00+08:00";

function checklist(status: string, hasReceipt = false, hasBlocker = false) {
  return [
    { code: "approved_packet", label: "投递包已由用户批准并冻结", complete: true, blocking: true },
    { code: "official_url", label: "已绑定官方申请地址", complete: true, blocking: true },
    { code: "form_opened", label: "已打开并检查申请表单", complete: status !== "CREATED", blocking: true },
    { code: "blockers_resolved", label: "所有阻塞项均已解决", complete: !hasBlocker, blocking: true },
    { code: "ready_for_submission", label: "表单内容已完成最终检查", complete: ["READY_TO_SUBMIT", "SUBMITTED"].includes(status), blocking: true },
    { code: "valid_receipt", label: "已保存有效提交凭证", complete: hasReceipt, blocking: true },
  ];
}

async function installAttemptFixture(page: Page) {
  let attempt: Record<string, unknown> | null = null;
  let blocker: Record<string, unknown> | null = null;
  let receipt: Record<string, unknown> | null = null;
  const headers = {
    "access-control-allow-origin": "http://localhost:3000",
    "access-control-allow-headers": "content-type,x-user-id",
    "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    "content-type": "application/json",
  };
  const application = {
    id: "application_attempt_demo",
    candidate_job_id: "candidate_demo",
    job_posting_id: "job_demo",
    status: "PREPARING",
    candidate_status: "CONVERTED",
    next_action: null,
    available_transitions: ["WITHDRAWN"],
    job: {
      id: "job_demo",
      company: "Evidence Labs",
      title: "AI Product Engineer",
      source_url: "https://careers.example.com/jobs/ai-product-engineer",
      verification_status: "VERIFIED_OFFICIAL",
      availability_status: "ACTIVE",
    },
    events: [],
    created_at: now,
    updated_at: now,
  };
  const revision = {
    id: "packet_revision_attempt_demo",
    revision_number: 2,
    status: "APPROVED",
    source_changed: false,
    job_snapshot: {
      company: "Evidence Labs",
      title: "AI Product Engineer",
      source_url: "https://careers.example.com/jobs/ai-product-engineer",
    },
  };
  const packet = {
    id: "packet_attempt_demo",
    application_id: application.id,
    current_revision_id: revision.id,
    status: "APPROVED",
    current_revision: revision,
  };

  function attemptResponse(status: string) {
    return {
      id: "attempt_demo",
      user_id: "local-user",
      application_id: application.id,
      job_posting_id: "job_demo",
      packet_revision_id: revision.id,
      application_url: "https://careers.example.com/jobs/ai-product-engineer",
      status,
      available_transitions: [],
      checklist: checklist(status, Boolean(receipt), blocker?.status === "OPEN"),
      blockers: blocker ? [blocker] : [],
      receipt,
      created_at: now,
      updated_at: now,
      form_opened_at: status === "CREATED" ? null : now,
      ready_at: ["READY_TO_SUBMIT", "SUBMITTED"].includes(status) ? now : null,
      submitted_at: status === "SUBMITTED" ? now : null,
      failed_at: null,
      abandoned_at: null,
    };
  }

  await page.route("http://127.0.0.1:18001/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 200, headers, body: "" });
      return;
    }
    if (path === "/api/applications" && request.method() === "GET") {
      await route.fulfill({ headers, json: [application] });
      return;
    }
    if (path === "/api/application-packets" && request.method() === "GET") {
      await route.fulfill({ headers, json: [packet] });
      return;
    }
    if (path === "/api/application-attempts" && request.method() === "GET") {
      await route.fulfill({ headers, json: attempt ? [attempt] : [] });
      return;
    }
    if (path === `/api/packet-revisions/${revision.id}/attempts`) {
      attempt = attemptResponse("CREATED");
      await route.fulfill({ status: 201, headers, json: attempt });
      return;
    }
    if (path === "/api/application-attempts/attempt_demo/status") {
      const body = request.postDataJSON() as { status: string };
      attempt = attemptResponse(body.status);
      await route.fulfill({ headers, json: attempt });
      return;
    }
    if (path === "/api/application-attempts/attempt_demo/blockers") {
      blocker = {
        id: "blocker_demo",
        attempt_id: "attempt_demo",
        application_id: application.id,
        category: "login",
        observation: "招聘门户要求短信验证",
        stop_reason: "需要候选人本人完成登录",
        retryable: true,
        next_strategy: "验证后继续填写",
        required_user_action: "完成短信验证",
        status: "OPEN",
        created_at: now,
      };
      attempt = attemptResponse("NEEDS_USER");
      await route.fulfill({ headers, json: attempt });
      return;
    }
    if (path === "/api/application-attempts/attempt_demo/blockers/blocker_demo/resolve") {
      blocker = { ...blocker, status: "RESOLVED" };
      attempt = attemptResponse("FORM_IN_PROGRESS");
      await route.fulfill({ headers, json: attempt });
      return;
    }
    if (path === "/api/application-attempts/attempt_demo/receipt") {
      receipt = {
        id: "receipt_demo",
        confirmation_text: "Your application was submitted successfully.",
        confirmation_url: null,
        application_number: "APP-2026-001",
        screenshot_metadata: {},
        is_valid: true,
        validation_codes: ["confirmation_text", "application_number"],
        receipt_hash: "a".repeat(64),
        captured_at: now,
      };
      attempt = attemptResponse("READY_TO_SUBMIT");
      await route.fulfill({ headers, json: attempt });
      return;
    }
    if (path === "/api/application-attempts/attempt_demo/finalize") {
      application.status = "SUBMITTED";
      attempt = attemptResponse("SUBMITTED");
      await route.fulfill({ headers, json: attempt });
      return;
    }
    await route.fulfill({ status: 200, headers, json: [] });
  });
}

test("manual application execution requires a verified receipt", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await installAttemptFixture(page);
  await page.goto("/");
  await page.getByRole("button", { name: /投递执行/ }).click();

  await expect(page.getByRole("heading", { name: /Evidence Labs \/ AI Product Engineer/ })).toBeVisible();
  await page.getByRole("button", { name: /创建投递尝试/ }).click();
  await expect(page.getByText("待打开", { exact: true }).last()).toBeVisible();

  await page.getByRole("button", { name: "已打开，开始填写" }).click();
  await page.getByLabel("页面观察").fill("招聘门户要求短信验证");
  await page.getByLabel("停止原因").fill("需要候选人本人完成登录");
  await page.getByLabel("下一策略").fill("验证后继续填写");
  await page.getByLabel("需要你的动作").fill("完成短信验证");
  await page.getByRole("button", { name: "记录并暂停" }).click();

  await expect(page.getByText("招聘门户要求短信验证", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "标记已解决" }).click();
  await page.getByRole("button", { name: "表单检查完成，进入待提交" }).click();

  await page.getByLabel("确认文本").fill("Your application was submitted successfully.");
  await page.getByLabel("申请 / Reference 编号").fill("APP-2026-001");
  await page.getByText("我确认官网已经显示提交成功", { exact: false }).click();
  await page.getByRole("button", { name: "验证并冻结凭证" }).click();

  await expect(page.getByText("RECEIPT VERIFIED", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "确认真实投递并更新申请" }).click();
  await expect(page.getByText("Application 已进入 SUBMITTED", { exact: true })).toBeVisible();
  const hasHorizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(hasHorizontalOverflow).toBe(false);
  expect(consoleErrors).toEqual([]);
});
