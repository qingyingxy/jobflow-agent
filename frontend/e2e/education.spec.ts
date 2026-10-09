import { expect, test } from "@playwright/test";
import type { EducationRecord } from "../app/education-editor";

test("education records keep their own major and graduation year when edited", async ({ page }, testInfo) => {
  const headers = {
    "access-control-allow-origin": "http://localhost:3000",
    "access-control-allow-headers": "content-type,x-user-id",
    "access-control-allow-methods": "GET,PUT,OPTIONS",
    "content-type": "application/json",
  };
  let profile = {
    display_name: "测试候选人", degree: "硕士", major: "金融", graduation_year: 2027,
    education_history_complete: false,
    educations: [
      { id: "edu_1", level: "bachelor", major_raw: "机械工程", school: null, enrollment_year: 2020, graduation_year: 2024, graduation_source_text: "2020-2024", status: "unknown", source_text: "本科 机械工程 2020-2024", source: "resume_asset:v3:test" },
      { id: "edu_2", level: "master", major_raw: "金融", school: null, enrollment_year: 2024, graduation_year: 2027, graduation_source_text: "2027预计毕业", graduation_year_kind: "expected", graduation_year_confirmed: false, status: "enrolled", source_text: "硕士 金融 2027预计毕业", source: "resume_asset:v3:test" },
    ] as EducationRecord[],
  };
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 200, headers, body: "" });
    if (path === "/api/profile") {
      if (route.request().method() === "PUT") profile = { ...profile, ...route.request().postDataJSON() };
      return route.fulfill({ headers, json: profile });
    }
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "简历资料", exact: true }).click();
  const bachelor = page.getByRole("group", { name: "教育经历 1", exact: true });
  const master = page.getByRole("group", { name: "教育经历 2", exact: true });
  await expect(bachelor.getByLabel("专业原名")).toHaveValue("机械工程");
  await expect(master.getByLabel("专业原名")).toHaveValue("金融");
  await expect(bachelor.getByLabel("入学年份", { exact: true })).toHaveValue("2020");
  await expect(bachelor.getByLabel("毕业 / 预计毕业年份", { exact: true })).toHaveValue("2024");
  await master.getByLabel("专业原名").fill("金融学");
  await page.getByLabel("我已核对，并已列出全部教育经历").check();
  await page.getByRole("button", { name: /保存简历资料/ }).click();
  await expect(page.getByText("简历资料已保存。下一次岗位分析会使用这份资料。")).toBeVisible();
  expect(profile.educations.map(e => [e.level, e.major_raw, e.graduation_year])).toEqual([
    ["bachelor", "机械工程", 2024], ["master", "金融学", 2027],
  ]);
  expect(profile.education_history_complete).toBe(true);
  expect(profile.educations[1].graduation_year_confirmed).toBe(false);
  await expect(master.getByLabel("我已核对这段经历的毕业年份")).not.toBeChecked();
  expect(profile.educations[1].graduation_source_text).toBe("2027预计毕业");
  await master.getByLabel("毕业 / 预计毕业年份", { exact: true }).fill("2028");
  await page.getByRole("button", { name: /保存简历资料/ }).click();
  await expect.poll(() => profile.educations[1].graduation_year).toBe(2028);
  expect(profile.educations[1].graduation_year_confirmed).toBe(true);
  await expect(master.getByLabel("我已核对这段经历的毕业年份")).toBeChecked();
  expect(profile.educations[1].graduation_source_text).toBeNull();
  expect(profile.educations[1].graduation_year_kind).toBe("expected");
  expect(profile.educations[1].source_text).toBe("硕士 金融 2027预计毕业");
  expect(profile.educations[0].enrollment_year).toBe(2020);
  expect(profile.educations[0].graduation_year).toBe(2024);
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  await expect(master.getByLabel("专业原名")).toHaveValue("金融学");
  await expect(master.getByLabel("毕业 / 预计毕业年份", { exact: true })).toHaveValue("2028");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(overflow).toBe(false);
  await page.screenshot({ path: testInfo.outputPath("education-records.png"), fullPage: true });
});

test("resume discrepancies stay optional and keep the user's current value", async ({ page }) => {
  const headers = {
    "access-control-allow-origin": "http://localhost:3000",
    "access-control-allow-headers": "content-type,x-user-id",
    "access-control-allow-methods": "GET,PUT,OPTIONS", "content-type": "application/json",
  };
  let saves = 0;
  let profile = {
    educations: [{ id: "edu_conflict", level: "master", major_raw: "金融学", school: "A大学",
      enrollment_year: 2024, graduation_year: 2028, graduation_source_text: null,
      graduation_year_confirmed: true, graduation_year_kind: "expected", status: "enrolled",
      source: "resume_asset:v4:new", source_text: "A大学 硕士 金融 2029预计毕业",
      provenance: { extracted: { graduation_year: 2029 }, overrides: ["graduation_year"],
        conflicts: { graduation_year: { incoming: 2029, source_text: "2029预计毕业" } } },
    }] as EducationRecord[], education_history_complete: true,
  };
  await page.route("http://127.0.0.1:18001/api/**", async route => {
    if (route.request().method() === "OPTIONS") return route.fulfill({ status: 200, headers, body: "" });
    if (new URL(route.request().url()).pathname === "/api/profile") {
      if (route.request().method() === "PUT") {
        saves++;
        profile = { ...profile, ...route.request().postDataJSON() };
        for (const record of profile.educations) if (record.provenance?.keep_current) {
          record.provenance = { ...record.provenance, conflicts: {}, keep_current: false };
        }
      }
      return route.fulfill({ headers, json: profile });
    }
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "简历资料", exact: true }).click();
  const summary = page.getByText("已保留你的修改；新简历有 1 处差异", { exact: true });
  await expect(summary).toBeVisible();
  // The ordinary save works without responding to the discrepancy.
  await page.getByRole("button", { name: /保存简历资料/ }).click();
  await expect.poll(() => saves).toBe(1);
  await expect(summary).toBeVisible();
  await expect(page.getByLabel("毕业 / 预计毕业年份", { exact: true })).toHaveValue("2028");
  await summary.click();
  await expect(page.getByText("新简历：2029", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "保留当前值", exact: true }).click();
  await page.getByRole("button", { name: /保存简历资料/ }).click();
  await expect.poll(() => saves).toBe(2);
  await expect(summary).toHaveCount(0);
  expect(profile.educations[0].graduation_year).toBe(2028);
  expect(profile.education_history_complete).toBe(true);
});
