import { expect, test } from "@playwright/test";

const api = "http://127.0.0.1:18001";
const raw = "招聘开发工程师。任职要求：硕士不限专业。熟悉 Python 开发以及自动化测试。";
const query = "2027届上海 AI Agent 校招，不考虑北京，不考虑社招";
const job = { id: "existing", company: "测试公司", title: "应用开发", source_url: "https://example.com/job/1", raw_content: raw,
  locations: ["上海市浦东新区示例园区非常长的详细街道地址一百八十八号研发中心十层"], job_type: "campus", availability_status: "OPEN", verification_status: "VERIFIED" };
const requirement = { name: "学历资格", category: "education", description: "硕士不限专业", mandatory: true, relation: "all_of", education: { relation: "all_of", branches: [{ source_text: "硕士不限专业" }] } };
const analysis = { analysis_id: "analysis-existing", job,
  structured_jd: { education_requirements: null, major_requirements: null, requirements: [requirement], deadline: null, internship_duration_months: null, weekly_days: null },
  eligibility: { eligible: "pass", checks: [{ rule_name: "education_qualification_0", field: "educations", result: "pass", reason: "硕士金融经历满足该分支", missing_information: [] }] },
  matches: [{ requirement, support_level: "supported", evidence_ids: [], explanation: "满足要求", validation_status: "passed", validation_issues: [] }],
  score: { score: null, recommendation: "insufficient_data", groups: [], missing_information: [] }, risks: [], missing_information: [] };

test("loaded results preserve query, fit mobile and retry the same job after failure", async ({ page }) => {
  let imports = 0;
  let attempts = 0;
  await page.route(`${api}/api/**`, async (route) => {
    const path = new URL(route.request().url()).pathname;
    const headers = { "access-control-allow-origin": "http://localhost:3000", "access-control-allow-headers": "content-type,x-user-id", "access-control-allow-methods": "GET,POST,OPTIONS" };
    if (route.request().method() === "OPTIONS") return route.fulfill({ headers, status: 200 });
    if (path === "/api/jobs/import-text") { imports++; return route.fulfill({ headers, json: { id: "wrong" } }); }
    if (path.endsWith("/analyze")) {
      expect(path).toBe("/api/jobs/existing/analyze"); attempts++;
      return route.fulfill({ headers, status: attempts === 1 ? 503 : 200, json: attempts === 1 ? { error: { message: "临时超时" } } : analysis });
    }
    if (path === "/api/candidates") return route.fulfill({ headers, json: [{ id: "candidate", job_posting_id: job.id, status: "SAVED", job, available_transitions: ["IGNORED"], analysis: { status: "ready", recommendation: "consider", eligibility: "pass" } }] });
    if (path === "/api/discovery/runs") return route.fulfill({ headers, json: [{ id: "run", source: "web", search_query: query, status: "SUCCEEDED", analysis_status: "SUCCEEDED", analysis_target_count: 1, analysis_completed_count: 1, analysis_failure_count: 0, discovered_count: 1, result_matches: [{ job_posting_id: job.id, match_tier: "strict", mismatch_reasons: [], mismatch_labels: [] }], agent_trace: [] }] });
    if (path === "/api/jobs/existing") return route.fulfill({ headers, json: job });
    if (path === "/api/jobs/existing/analysis") return route.fulfill({ headers, json: analysis });
    if (path === "/api/profile") return route.fulfill({ headers, status: 404, json: {} });
    return route.fulfill({ headers, json: [] });
  });
  await page.goto("/");
  await expect(page.getByRole("textbox", { name: "你想找什么" })).toHaveValue(query);
  await expect(page.getByRole("button", { name: "应用开发", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1);
  await page.getByRole("button", { name: "应用开发", exact: true }).click();
  await page.getByRole("button", { name: "打开完整匹配与申请" }).click();
  await expect(page.getByText("原文未明确", { exact: true })).toBeVisible();
  await expect(page.getByText("要求全部满足", { exact: true })).toBeVisible();
  await expect(page.getByText("education qualification 0", { exact: false })).toHaveCount(0);
  await page.getByRole("button", { name: "重新分析", exact: true }).click();
  await expect(page.getByText("临时超时", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "重新分析", exact: true }).click();
  await expect(page.getByRole("heading", { name: "资格检查", exact: true })).toBeVisible();
  expect(attempts).toBe(2);
  expect(imports).toBe(0);
  await page.getByRole("button", { name: "返回岗位列表" }).click();
  await page.reload();
  await expect(page.getByRole("textbox", { name: "你想找什么" })).toHaveValue(query);
});
