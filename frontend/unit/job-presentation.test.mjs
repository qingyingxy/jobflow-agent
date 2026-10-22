import assert from "node:assert/strict";
import test from "node:test";
import { formatJobDescription } from "../app/job-description-format.ts";
import { jobReviewSummary } from "../app/discovery-review.ts";

test("flattened Chinese JD lists retain the complete source and technical names", () => {
  const raw = "上海-Agent Harness 工程师\r\n上海市 校招 2026-07-21\r\n工作职责：\r\n-参与 Agent Harness 建设 -搭建状态管理与 compaction 系统 -协作开发\r\n职责要求：\r\n-熟悉 Plan-and-Execute、GPT-4、AI4SE -Agent 重度用户 -本科及以上学历 -加分项：开源贡献";
  const blocks = formatJobDescription(raw);
  assert.deepEqual(blocks.filter(b => b.type === "heading").map(b => b.lines[0]), ["工作职责：", "职责要求："]);
  assert.deepEqual(blocks.filter(b => b.type === "list").map(b => b.lines.length), [3, 4]);
  assert.equal(blocks.flatMap(b => b.lines).join("").replace(/\s/g, ""), raw.replace(/\s/g, ""));
});

test("paragraphs, numbered requirements, dates, ranges and inline headings stay intact", () => {
  const raw = "工作内容：开发工具\n1. 熟悉 Node.js 24.13 与 C++\n2. 每周 3-5 天，2026-07-21 入职\n\nRequirements:\n- Knowledge of Plan-and-Execute and end-to-end systems\nVersion 3.5 is supported.\n普通段落含 AI - Agent 术语。";
  const blocks = formatJobDescription(raw);
  assert.equal(blocks.flatMap(b => b.lines).join("").replace(/\s/g, ""), raw.replace(/\s/g, ""));
  assert.ok(blocks.some(b => b.type === "list" && b.lines.length === 2));
  assert.ok(blocks.some(b => b.type === "paragraph" && b.lines[0] === "Version 3.5 is supported."));
  assert.ok(blocks.some(b => b.lines.includes("- Knowledge of Plan-and-Execute and end-to-end systems")));
  assert.deepEqual(formatJobDescription("  \n"), []);
});

test("recommendations prioritize unknown conditions without inventing eligibility", () => {
  const match = { filter_status: "pending", review_status: "recommended", checks: [
    { field: "availability", status: "pending", reason: "未知" },
    { field: "role", status: "matched", reason: "符合搜索方向" },
    { field: "graduation_year", status: "pending", reason: "未写届别" },
  ] };
  const original = JSON.stringify(match);
  const result = jobReviewSummary(match);
  assert.equal(result.label, "推荐查看");
  assert.equal(result.reason, "届别待确认 · 开放状态未知");
  assert.doesNotMatch(result.reason, /资格通过|符合当前搜索条件/);
  assert.equal(JSON.stringify(match), original);
  const incomplete = jobReviewSummary(match, { missingCompany: true, missingLocation: true });
  assert.equal(incomplete.label, "信息待补全");
  assert.match(incomplete.reason, /公司待确认.*地点待确认/);
});

test("closed jobs, personal conflicts and unread sources keep priority over missing metadata", () => {
  const source = { missingCompany: true };
  assert.equal(jobReviewSummary(undefined, { ...source, closed: true }).label, "已关闭");
  assert.equal(jobReviewSummary({ personal_gate_conflict: true }, source).label, "存在门槛冲突");
  assert.equal(jobReviewSummary({ filter_status: "excluded" }, source).label, "不符搜索条件");
  assert.equal(jobReviewSummary(undefined, { ...source, pendingLeadStatus: "NEEDS_BROWSER" }).label, "待核验");
  assert.equal(jobReviewSummary().reason, "尚未按当前需求核对");
});
