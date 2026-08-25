import { expect, test, type Page } from "@playwright/test";

const now = "2026-08-25T10:00:00+08:00";

function applicationPacket(status: "DRAFT" | "NEEDS_REVIEW" | "APPROVED" = "DRAFT") {
  const revision = {
    id: "packet_revision_demo",
    packet_id: "packet_demo",
    application_id: "application_demo",
    job_posting_id: "job_demo",
    revision_number: 1,
    status,
    supersedes_revision_id: null,
    job_analysis_id: "analysis_demo",
    analysis_version: "job-analysis-v1",
    analysis_input_hash: "a".repeat(64),
    jd_content_hash: "b".repeat(64),
    profile_revision: 3,
    resume_version_id: "resume_version_demo",
    source_fingerprint: "c".repeat(64),
    payload_hash: "d".repeat(64),
    job_snapshot: {
      id: "job_demo",
      company: "Evidence Labs",
      title: "AI Product Engineer",
      locations: ["上海"],
      job_type: "full_time",
      source_url: "https://example.com/jobs/ai-product-engineer",
      verification_status: "VERIFIED_OFFICIAL",
      availability_status: "ACTIVE",
      raw_content: "负责 AI Agent 产品工程、评测体系与可追溯工作流，要求熟悉 Python 和可靠性设计。",
      content_hash: "b".repeat(64),
    },
    analysis_snapshot: {
      id: "analysis_demo",
      analysis_version: "job-analysis-v1",
      input_hash: "a".repeat(64),
      structured_jd: {},
      eligibility: { eligible: "pass", checks: [] },
      matches: [],
      score: { score: 91, recommendation: "recommended" },
      risks: [],
      missing_information: [],
    },
    profile_snapshot: { revision: 3 },
    resume_snapshot: {
      id: "resume_version_demo",
      version_number: 2,
      label: "AI Product Engineer 定向版",
      job_family: "AI Product",
      source_version_id: "resume_version_base",
      generation_reason: "根据岗位要求调整证据顺序",
      is_default: false,
      asset: {
        id: "resume_asset_demo",
        original_filename: "ai-product-resume.pdf",
        media_type: "application/pdf",
        size_bytes: 1024,
        sha256: "e".repeat(64),
      },
    },
    evidence_snapshots: [{
      id: "ev_demo",
      title: "Agent 评测工作台",
      claim: "建立可复现评测集与证据校验边界。",
      source: "portfolio",
      type: "project",
      skills: ["Python"],
      updated_at: now,
    }],
    form_answer_snapshots: [{
      id: "answer_demo",
      question_pattern: "Why this role?",
      answer: "I build evidence-first AI products.",
      scope_type: "role",
      scope_value: "AI Product Engineer",
      sensitivity: "personal",
      confirmed_at: now,
      updated_at: now,
    }],
    open_questions: [],
    risk_snapshots: [],
    confirmation_items: [],
    blockers: [],
    created_by_actor: "agent",
    source_changed: false,
    source_change_codes: [],
    decisions: status === "APPROVED" ? [{ id: "decision_demo", decision: "APPROVE", actor_type: "user", created_at: now }] : [],
    created_at: now,
    updated_at: now,
    submitted_for_review_at: status === "DRAFT" ? null : now,
    approved_at: status === "APPROVED" ? now : null,
    superseded_at: null,
  };
  return {
    id: "packet_demo",
    user_id: "local-user",
    application_id: "application_demo",
    job_posting_id: "job_demo",
    current_revision_id: revision.id,
    status,
    current_revision: revision,
    revisions: [revision],
    created_at: now,
    updated_at: now,
  };
}

async function installPacketFixture(page: Page) {
  let packet: ReturnType<typeof applicationPacket> | null = null;
  const headers = {
    "access-control-allow-origin": "http://localhost:3000",
    "access-control-allow-headers": "content-type,x-user-id,x-actor-type",
    "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
    "content-type": "application/json",
  };
  const application = {
    id: "application_demo",
    candidate_job_id: "candidate_demo",
    job_posting_id: "job_demo",
    status: "PREPARING",
    candidate_status: "CONVERTED",
    next_action: null,
    available_transitions: ["SUBMITTED", "WITHDRAWN"],
    job: {
      id: "job_demo",
      company: "Evidence Labs",
      title: "AI Product Engineer",
      source_url: "https://example.com/jobs/ai-product-engineer",
      verification_status: "VERIFIED_OFFICIAL",
      availability_status: "ACTIVE",
    },
    events: [],
    created_at: now,
    updated_at: now,
  };
  const resume = {
    id: "resume_version_demo",
    user_id: "local-user",
    asset_id: "resume_asset_demo",
    version_number: 2,
    label: "AI Product Engineer 定向版",
    job_family: "AI Product",
    source_version_id: "resume_version_base",
    generation_reason: "根据岗位要求调整证据顺序",
    is_default: true,
    created_at: now,
    updated_at: now,
  };
  const evidence = {
    id: "ev_demo",
    title: "Agent 评测工作台",
    claim: "建立可复现评测集与证据校验边界。",
    source: "portfolio",
  };
  const answer = {
    id: "answer_demo",
    question_pattern: "Why this role?",
    answer: "I build evidence-first AI products.",
    sensitivity: "personal",
    scope_type: "role",
    scope_value: "AI Product Engineer",
  };

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
      await route.fulfill({ headers, json: packet ? [packet] : [] });
      return;
    }
    if (path === "/api/resumes/versions") {
      await route.fulfill({ headers, json: [resume] });
      return;
    }
    if (path === "/api/evidence") {
      await route.fulfill({ headers, json: [evidence] });
      return;
    }
    if (path === "/api/answer-bank") {
      await route.fulfill({ headers, json: [answer] });
      return;
    }
    if (path === "/api/applications/application_demo/packet") {
      packet = applicationPacket("DRAFT");
      await route.fulfill({ status: 201, headers, json: packet });
      return;
    }
    if (path === "/api/packet-revisions/packet_revision_demo/items") {
      packet = applicationPacket("DRAFT");
      await route.fulfill({ headers, json: packet });
      return;
    }
    if (path === "/api/packet-revisions/packet_revision_demo/review") {
      packet = applicationPacket("NEEDS_REVIEW");
      await route.fulfill({ headers, json: packet });
      return;
    }
    if (path === "/api/packet-revisions/packet_revision_demo/approve") {
      packet = applicationPacket("APPROVED");
      await route.fulfill({ headers, json: packet });
      return;
    }
    await route.fulfill({ status: 200, headers, json: [] });
  });
}

test("frozen packet can be reviewed and explicitly approved", async ({ page }) => {
  await installPacketFixture(page);
  await page.goto("/");
  await page.getByRole("button", { name: /投递审核/ }).click();

  await expect(page.getByRole("heading", { name: /Evidence Labs \/ AI Product Engineer/ })).toBeVisible();
  await page.getByRole("button", { name: /生成冻结草稿/ }).click();
  await expect(page.getByText("岗位事实与 JD 快照", { exact: true })).toBeVisible();
  await expect(page.locator(".packet-resume-diff").getByText("V2 · AI Product Engineer 定向版", { exact: true })).toBeVisible();
  await expect(page.getByText("Agent 评测工作台", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "提交审核", exact: true }).click();
  await expect(page.getByText("待审核", { exact: true }).last()).toBeVisible();
  await page.getByRole("button", { name: "批准此冻结版本", exact: true }).click();

  await expect(page.getByText("已批准", { exact: true }).last()).toBeVisible();
  await expect(page.getByText("I build evidence-first AI products.", { exact: true })).toBeVisible();
  await expect(page.getByText("批准仅绑定这一个修订号和内容哈希，不改变申请提交状态。", { exact: true })).toBeVisible();
});
