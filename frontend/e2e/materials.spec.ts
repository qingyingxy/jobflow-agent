import { expect, test, type Page } from "@playwright/test";

const now = "2026-08-25T10:00:00+08:00";

const missingFields = [
  "contact_email",
  "contact_phone",
  "current_status",
  "availability_date",
  "work_authorization",
  "sponsorship_required",
  "salary_strategy",
  "relocation_willing",
];

function profileResponse(emailProvided = false) {
  const field = (name: string) => ({
    state: name === "contact_email" && emailProvided ? "provided" : "missing",
    value: name === "contact_email" && emailProvided ? "owner@example.com" : null,
  });
  return {
    user_id: "local-user",
    revision: emailProvided ? 2 : 1,
    contact_email: field("contact_email"),
    contact_phone: field("contact_phone"),
    current_status: field("current_status"),
    availability_date: field("availability_date"),
    work_authorization: field("work_authorization"),
    sponsorship_required: field("sponsorship_required"),
    salary_strategy: field("salary_strategy"),
    relocation_willing: field("relocation_willing"),
    voluntary_disclosure_policy: "ask_each_time",
    readiness: "needs_confirmation",
    needs_confirmation: missingFields
      .filter((name) => !(name === "contact_email" && emailProvided))
      .map((name) => ({ field: name, state: "missing", reason: "missing_high_impact_field" })),
    created_at: now,
    updated_at: now,
  };
}

async function installMaterialsFixture(page: Page) {
  let emailProvided = false;
  let assets: Array<Record<string, unknown>> = [];
  let versions: Array<Record<string, unknown>> = [];
  let answers: Array<Record<string, unknown>> = [];
  const headers = {
    "access-control-allow-origin": "http://localhost:3000",
    "access-control-allow-headers": "content-type,x-user-id",
    "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    "content-type": "application/json",
  };

  await page.route("http://127.0.0.1:18001/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 200, headers, body: "" });
      return;
    }
    if (path === "/api/private-profile") {
      if (request.method() === "PUT") emailProvided = true;
      await route.fulfill({ headers, json: profileResponse(emailProvided) });
      return;
    }
    if (path === "/api/resumes/assets" && request.method() === "GET") {
      await route.fulfill({ headers, json: assets });
      return;
    }
    if (path === "/api/resumes/assets" && request.method() === "POST") {
      const asset = {
        id: "resume_asset_demo",
        user_id: "local-user",
        original_filename: "agent-resume.pdf",
        media_type: "application/pdf",
        size_bytes: 42,
        sha256: "a".repeat(64),
        created_at: now,
      };
      assets = [asset];
      await route.fulfill({ status: 201, headers, json: asset });
      return;
    }
    if (path === "/api/resumes/versions" && request.method() === "GET") {
      await route.fulfill({ headers, json: versions });
      return;
    }
    if (path === "/api/resumes/versions" && request.method() === "POST") {
      const version = {
        id: "resume_version_demo",
        user_id: "local-user",
        asset_id: "resume_asset_demo",
        version_number: 1,
        label: "AI Agent 中文简历",
        job_family: "AI Agent",
        source_version_id: null,
        generation_reason: "用户上传基线",
        is_default: true,
        asset: assets[0],
        created_at: now,
        updated_at: now,
      };
      versions = [version];
      await route.fulfill({ status: 201, headers, json: version });
      return;
    }
    if (path === "/api/answer-bank" && request.method() === "GET") {
      await route.fulfill({ headers, json: answers });
      return;
    }
    if (path === "/api/answer-bank" && request.method() === "POST") {
      const body = request.postDataJSON() as Record<string, unknown>;
      const answer = {
        id: "answer_demo",
        user_id: "local-user",
        question_pattern: body.question_pattern,
        answer: body.answer,
        scope_type: body.scope_type,
        scope_value: body.scope_value,
        sensitivity: body.sensitivity,
        confirmed_at: now,
        created_at: now,
        updated_at: now,
      };
      answers = [answer];
      await route.fulfill({ status: 201, headers, json: answer });
      return;
    }
    await route.fulfill({ status: 404, headers, json: { detail: "not mocked" } });
  });
}

test("private profile keeps missing fields visible and never guesses", async ({ page }) => {
  await installMaterialsFixture(page);
  await page.goto("/");
  await page.getByRole("button", { name: /投递资料/ }).click();

  await expect(page.getByRole("heading", { name: "确认申请事实" })).toBeVisible();
  await expect(page.getByText("8 项待确认", { exact: true })).toBeVisible();
  await page.getByLabel("联系邮箱保存状态").selectOption("provided");
  await page.getByLabel("联系邮箱内容").fill("owner@example.com");
  await page.getByRole("button", { name: /保存私密档案/ }).click();

  await expect(page.getByText("仍有 7 项需要确认", { exact: false })).toBeVisible();
  await expect(page.getByText("当前状态 · 缺失", { exact: true })).toBeVisible();
});

test("resume and confirmed answer become versioned library records", async ({ page }) => {
  await installMaterialsFixture(page);
  await page.goto("/");
  await page.getByRole("button", { name: /投递资料/ }).click();

  await page.getByRole("tab", { name: /简历版本/ }).click();
  await page.getByLabel("上传新文件").setInputFiles({
    name: "agent-resume.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.7 demo"),
  });
  await page.getByLabel("版本名称").fill("AI Agent 中文简历");
  await page.getByLabel("适用岗位族").fill("AI Agent");
  await page.getByRole("button", { name: /创建简历版本/ }).click();
  await expect(page.getByText("AI Agent 中文简历", { exact: true })).toBeVisible();
  await expect(page.getByText("DEFAULT", { exact: true })).toBeVisible();

  await page.getByRole("tab", { name: /答案库/ }).click();
  await page.getByLabel("问题模式").fill("Why do you want to join us?");
  await page.getByLabel("已确认答案").fill("I value evidence-first product work.");
  await page.getByLabel("我确认答案准确，并允许保存到私密答案库").check();
  await page.getByRole("button", { name: /保存确认答案/ }).click();
  await expect(page.getByText("Why do you want to join us?", { exact: true })).toBeVisible();
  await expect(page.getByText("I value evidence-first product work.", { exact: true })).toBeVisible();
});
