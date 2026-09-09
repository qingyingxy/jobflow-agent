import { expect, test } from "@playwright/test";

const now = "2026-09-07T10:00:00+08:00";

test("workspace keeps job decisions primary and profile status actionable", async ({ page }, testInfo) => {
  const headers = {
    "access-control-allow-origin": "http://localhost:3000",
    "access-control-allow-headers": "content-type,x-user-id",
    "access-control-allow-methods": "GET,OPTIONS",
    "content-type": "application/json",
  };

  await page.route("http://127.0.0.1:18001/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === "OPTIONS") {
      await route.fulfill({ status: 200, headers, body: "" });
      return;
    }
    if (["/api/resumes/versions", "/api/resumes/assets", "/api/evidence", "/api/answer-bank"].includes(path)) {
      await route.fulfill({ headers, json: [] });
      return;
    }
    if (path === "/api/private-profile") {
      const fields = [
        "contact_email",
        "contact_phone",
        "current_status",
        "availability_date",
        "work_authorization",
        "sponsorship_required",
        "salary_strategy",
        "relocation_willing",
      ];
      await route.fulfill({
        headers,
        json: {
          user_id: "local-user",
          revision: 1,
          ...Object.fromEntries(fields.map((field) => [field, { state: "missing", value: null }])),
          voluntary_disclosure_policy: "ask_each_time",
          readiness: "needs_confirmation",
          needs_confirmation: fields.map((field) => ({ field, state: "missing", reason: "missing_high_impact_field" })),
          created_at: now,
          updated_at: now,
        },
      });
      return;
    }
    await route.fulfill({ status: 404, headers, json: { detail: "not mocked" } });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "发现适合你的岗位" })).toBeVisible();
  await expect(page.getByRole("button", { name: /发现岗位/ })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("button", { name: "快速判断" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /尚未上传简历/ })).toBeVisible();
  await expect(page.getByText("准备个人经历", { exact: true })).toHaveCount(0);

  const overflow = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
  }));
  expect(overflow.documentWidth).toBeLessThanOrEqual(overflow.viewportWidth + 1);

  await page.screenshot({
    path: testInfo.outputPath(`workspace-${testInfo.project.name}.png`),
    fullPage: true,
  });

  await page.getByRole("button", { name: /尚未上传简历/ }).click();
  const resumeDialog = page.getByRole("dialog");
  await expect(resumeDialog).toBeVisible();
  await expect(page.getByRole("heading", { name: "简历管理" })).toBeVisible();
  await expect(resumeDialog.getByText("上传后会自动解析经历", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: /发现岗位/ })).toHaveAttribute("aria-current", "page");
});
