import { expect, test, type Page } from "@playwright/test";

const now = "2026-08-25T10:00:00+08:00";

async function installAtsFixture(page: Page) {
  let attemptStatus = "CREATED";
  let sessionStatus: string | null = null;
  let authorizationUsed = false;
  const headers = {
    "access-control-allow-origin": "http://localhost:3000",
    "access-control-allow-headers": "content-type,x-user-id",
    "access-control-allow-methods": "GET,POST,OPTIONS",
    "content-type": "application/json",
  };
  const application = {
    id: "application_ats_demo",
    candidate_job_id: "candidate_ats_demo",
    job_posting_id: "job_ats_demo",
    status: "PREPARING",
    candidate_status: "CONVERTED",
    next_action: null,
    available_transitions: ["WITHDRAWN"],
    job: {
      id: "job_ats_demo",
      company: "Signal Foundry",
      title: "AI Platform Engineer",
      source_url: "https://boards.greenhouse.io/signal-foundry/jobs/1001",
    },
    events: [],
    created_at: now,
    updated_at: now,
  };
  const fieldPlan = [
    {
      field_key: "resume_field",
      label: "Resume / CV",
      name: "resume",
      input_type: "file",
      required: true,
      canonical_name: "resume",
      risk: "LOW",
      action: "FILL",
      source: "resume_snapshot",
      value: "resume_asset_demo",
      reason: "值来自当前已批准的投递包",
      options: [],
    },
    {
      field_key: "privacy_field",
      label: "I agree to the privacy terms",
      name: "privacy_consent",
      input_type: "checkbox",
      required: true,
      canonical_name: "legal_consent",
      risk: "LEGAL",
      action: sessionStatus && sessionStatus !== "NEEDS_USER" ? "FILL" : "NEEDS_CONFIRMATION",
      source: "user_confirmation",
      value: "true",
      reason: "该字段影响较高，必须由用户针对本次表单再次确认",
      options: [],
    },
  ];

  function attempt() {
    return {
      id: "attempt_ats_demo",
      application_id: application.id,
      job_posting_id: application.job_posting_id,
      packet_revision_id: "packet_revision_ats_demo",
      application_url: application.job.source_url,
      status: attemptStatus,
      receipt: attemptStatus === "SUBMITTED" ? { id: "receipt_ats_demo", is_valid: true } : null,
    };
  }

  function atsSession() {
    if (!sessionStatus) return null;
    const ready = sessionStatus !== "NEEDS_USER";
    return {
      id: "ats_session_demo",
      user_id: "local-user",
      attempt_id: "attempt_ats_demo",
      application_id: application.id,
      job_posting_id: application.job_posting_id,
      packet_revision_id: "packet_revision_ats_demo",
      application_url: application.job.source_url,
      provider: "GREENHOUSE",
      status: sessionStatus,
      page_fingerprint: "a".repeat(64),
      plan_hash: "b".repeat(64),
      field_plan: fieldPlan.map((field) => field.field_key === "privacy_field" ? { ...field, action: ready ? "FILL" : "NEEDS_CONFIRMATION" } : field),
      handoff_reasons: ready ? [] : [{ code: "sensitive_field_confirmation_required", category: "field", field_key: "privacy_field", label: "I agree to the privacy terms", message: "该字段影响较高，必须由用户针对本次表单再次确认" }],
      final_summary: {
        company: "Signal Foundry",
        job_title: "AI Platform Engineer",
        resume: "AI Platform R03",
        field_count: 2,
        fill_count: ready ? 2 : 1,
        key_answers: [],
      },
      authorization_expires_at: sessionStatus === "AUTHORIZED" ? "2026-08-25T10:10:00+08:00" : null,
      authorization_used: authorizationUsed,
      created_at: now,
      updated_at: now,
      inspected_at: now,
      prepared_at: ready ? now : null,
      authorized_at: sessionStatus === "AUTHORIZED" ? now : null,
      submitted_at: sessionStatus === "SUBMITTED" ? now : null,
      failed_at: null,
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
    if (path === "/api/application-attempts" && request.method() === "GET") {
      await route.fulfill({ headers, json: [attempt()] });
      return;
    }
    if (path === "/api/ats-sessions" && request.method() === "GET") {
      await route.fulfill({ headers, json: atsSession() ? [atsSession()] : [] });
      return;
    }
    if (path === "/api/application-attempts/attempt_ats_demo/ats-session") {
      attemptStatus = "NEEDS_USER";
      sessionStatus = "NEEDS_USER";
      await route.fulfill({ headers, json: atsSession() });
      return;
    }
    if (path === "/api/ats-sessions/ats_session_demo/confirm-fields") {
      attemptStatus = "READY_TO_SUBMIT";
      sessionStatus = "READY_FOR_APPROVAL";
      await route.fulfill({ headers, json: atsSession() });
      return;
    }
    if (path === "/api/ats-sessions/ats_session_demo/authorization") {
      sessionStatus = "AUTHORIZED";
      await route.fulfill({ headers, json: { session: atsSession(), authorization_token: "token_" + "x".repeat(40), expires_at: "2026-08-25T10:10:00+08:00" } });
      return;
    }
    if (path === "/api/ats-sessions/ats_session_demo/submit") {
      authorizationUsed = true;
      attemptStatus = "SUBMITTED";
      sessionStatus = "SUBMITTED";
      application.status = "SUBMITTED";
      await route.fulfill({ headers, json: atsSession() });
      return;
    }
    await route.fulfill({ status: 200, headers, json: [] });
  });
}

test("limited ATS assistance keeps sensitive fields and submit under user control", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  await installAtsFixture(page);
  await page.goto("/");
  await page.getByRole("button", { name: /申请进度/ }).click();
  await page.getByRole("button", { name: "浏览器辅助填写" }).click();
  const dialog = page.getByRole("dialog");

  await expect(dialog.getByRole("heading", { name: /Signal Foundry \/ AI Platform Engineer/ })).toBeVisible();
  await dialog.getByRole("button", { name: "检测并检查 ATS" }).click();
  await expect(dialog.getByText("I agree to the privacy terms", { exact: true }).first()).toBeVisible();
  await expect(dialog.getByText("法律确认", { exact: true })).toBeVisible();

  await dialog.getByRole("checkbox").first().check();
  await dialog.getByRole("button", { name: "确认所选高影响字段" }).click();
  await expect(dialog.locator(".ats-session-status")).toHaveText("等待最终授权");

  await dialog.getByText("我已核对公司、岗位、简历版本、关键答案和风险", { exact: false }).click();
  await dialog.getByRole("button", { name: "签发一次性提交授权" }).click();
  await expect(dialog.getByText("ONE-TIME TOKEN IN MEMORY", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "提交并捕获凭证" }).click();

  await expect(dialog.getByText("RECEIPT VERIFIED", { exact: true })).toBeVisible();
  await expect(dialog.getByRole("status")).toContainText("Application 已进入 SUBMITTED");
  const hasHorizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(hasHorizontalOverflow).toBe(false);
  expect(consoleErrors).toEqual([]);
});
