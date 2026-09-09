"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import MaterialsWorkspace from "./materials-workspace";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:18001";
const userId = "local-user";

type AnalysisState = "empty" | "loading" | "success" | "error";
type SupportLevel = "supported" | "partial" | "needs_confirmation" | "unsupported";

type JobRequirement = {
  category: string;
  name: string;
  description: string;
  mandatory: boolean;
  relation?: "all_of" | "any_of" | "uncertain";
  items?: string[] | null;
  relation_reason?: string | null;
};

type RequirementMatch = {
  requirement: JobRequirement;
  support_level: SupportLevel;
  evidence_ids: string[];
  explanation: string;
  validation_status: "passed" | "failed";
  validation_issues: string[];
};

type AnalysisRisk = {
  code: string;
  severity: "high" | "medium" | "low";
  title: string;
  detail: string;
  requirement_name?: string | null;
};

type AnalysisResponse = {
  analysis_id: string;
  job: {
    id: string;
    company: string | null;
    title: string | null;
    source_url: string | null;
  };
  structured_jd: {
    company: string | null;
    title: string | null;
    job_type: string | null;
    locations: string[] | null;
    education_requirements: string[] | null;
    major_requirements: string[] | null;
    required_skills: string[] | null;
    preferred_skills: string[] | null;
    internship_duration_months: number | null;
    weekly_days: number | null;
    deadline: string | null;
    requirements: JobRequirement[] | null;
    responsibilities?: string[] | null;
  };
  eligibility: {
    eligible: "pass" | "fail" | "unknown";
    checks: Array<{
      rule_name: string;
      field: string;
      result: "pass" | "fail" | "unknown";
      reason: string;
      missing_information: string[];
    }>;
  };
  matches: RequirementMatch[];
  decision?: {
    recommendation: "recommended_application" | "consider" | "not_recommended" | "insufficient_information";
    summary: string;
    reasons: string[];
    required_supported: number;
    required_total: number;
    needs_confirmation: number;
  };
  score: {
    score: number | null;
    recommendation: "recommended" | "not_recommended" | "needs_confirmation" | "insufficient_data";
    groups: Array<{
      group: string;
      status: "applicable" | "not_applicable" | "insufficient_data";
      score: number | null;
      effective_weight: number;
    }>;
    missing_information: string[];
  };
  risks: AnalysisRisk[];
  missing_information: string[];
};

type WorkspaceMode = "profile" | "discover" | "analysis" | "board";
type ProfileSummaryState = "loading" | "ready" | "missing_resume" | "missing_evidence" | "error";

type ProfileSummary = {
  state: ProfileSummaryState;
  resumeCount: number;
  evidenceCount: number;
};
type CandidateStatus = "DISCOVERED" | "SAVED" | "IGNORED" | "CONVERTED";
type ApplicationStatus =
  | "PREPARING"
  | "SUBMITTED"
  | "ASSESSMENT"
  | "INTERVIEW"
  | "OFFER"
  | "REJECTED"
  | "WITHDRAWN";

type ApplicationEvent = {
  id: string;
  entity_type: string;
  entity_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
};

type SuggestionStatus = "PENDING" | "ACCEPTED" | "REJECTED";
type SuggestionDecision = "accept" | "edit" | "reject";

type ProfileJobType = "campus" | "internship" | "full_time" | "part_time";

type ProfileRecord = {
  user_id: string;
  display_name: string | null;
  graduation_year: number | null;
  degree: string | null;
  major: string | null;
  search_preferences: {
    preferred_locations: string[] | null;
    job_types: ProfileJobType[] | null;
    target_roles: string[] | null;
  };
};

type EvidenceRecord = {
  id: string;
  type: string;
  title: string;
  claim: string;
  skills: string[];
  source: string;
  created_at: string;
  updated_at: string;
};

type EvidenceDraft = {
  type: string;
  title: string;
  claim: string;
  skills: string;
  source: string;
};

type ProfileWorkspaceState = "idle" | "loading" | "ready" | "saving" | "error";

type ResumeSuggestion = {
  id: string;
  user_id: string;
  application_id: string;
  job_analysis_id: string;
  target_type: string;
  target_label: string | null;
  original_text: string;
  suggestion_text: string;
  evidence_ids: string[];
  status: SuggestionStatus;
  final_text: string | null;
  agent_run_id: string;
  created_at: string;
  updated_at: string;
};

type ApplicationItem = {
  id: string;
  candidate_job_id: string;
  job_posting_id: string;
  status: ApplicationStatus;
  candidate_status: "DISCOVERED" | "SAVED" | "IGNORED" | "CONVERTED";
  next_action: string | null;
  available_transitions: ApplicationStatus[];
  job: {
    id: string;
    company: string | null;
    title: string | null;
    source_url: string | null;
    source_id?: string | null;
    locations?: string[];
    job_type?: string | null;
    published_at?: string | null;
    last_seen_at?: string | null;
  };
  events: ApplicationEvent[];
  created_at: string;
  updated_at: string;
};

type BoardState = "idle" | "loading" | "ready" | "error";
type DiscoveryState = "idle" | "loading" | "ready" | "error";

type CandidateItem = {
  id: string;
  user_id: string;
  job_posting_id: string;
  status: CandidateStatus;
  available_transitions: CandidateStatus[];
  job: {
    id: string;
    company: string | null;
    title: string | null;
    source_url: string | null;
    source_id?: string | null;
    locations?: string[];
    job_type?: string | null;
    published_at?: string | null;
    verification_status?: JobVerificationStatus;
    availability_status?: JobAvailabilityStatus;
    first_seen_at?: string | null;
    last_seen_at?: string | null;
    last_verified_at?: string | null;
    availability_failure_count?: number;
    last_availability_checked_at?: string | null;
    closed_at?: string | null;
  };
  analysis?: {
    status: "ready";
    score: number | null;
    recommendation: string | null;
    eligibility: "pass" | "fail" | "unknown" | null;
  } | null;
  created_at: string;
  updated_at: string;
};

type DiscoveryRunItem = {
  id: string;
  source: string;
  source_url: string;
  search_query: string | null;
  max_results: number;
  status: "RUNNING" | "SUCCEEDED" | "PARTIAL" | "FAILED";
  discovered_count: number;
  new_count: number;
  duplicate_count: number;
  analysis_target_count: number;
  analysis_completed_count: number;
  analysis_failure_count: number;
  analysis_status: "NOT_REQUESTED" | "PENDING" | "RUNNING" | "SUCCEEDED" | "PARTIAL" | "FAILED";
  search_plan: DiscoverySearchPlan | null;
  agent_trace: DiscoveryAgentTraceStep[];
  result_matches: DiscoveryResultMatch[];
  failure_summary: string | null;
  started_at: string;
  finished_at: string | null;
  created_at: string;
};

type DiscoveryResultMatch = {
  job_posting_id: string;
  match_tier: "strict" | "expanded";
  mismatch_reasons: string[];
  mismatch_labels: string[];
};

type DiscoveryAgentTraceStep = {
  phase: string;
  tool: string;
  outcome: string;
  observation: string;
  decision: string;
  source_id: string | null;
  company: string | null;
  url: string | null;
  occurred_at?: string | null;
  duration_ms?: number | null;
  error_code?: string | null;
  details?: Record<string, unknown>;
};

type DiscoverySearchPlan = {
  version: string;
  planner: string;
  query: string | null;
  allowed_source_ids: string[];
  routes: Array<{
    source_id: string;
    company: string | null;
    source_url: string;
    tool_sequence: string[];
  }>;
  budget: {
    max_results: number;
    max_analysis: number;
    max_detail_links_per_source: number | null;
    max_concurrency: number | null;
    request_timeout_seconds: number | null;
  };
  stop_conditions: string[];
};

type DiscoverySourceOption = {
  id: string;
  company: string;
  priority: "A" | "B" | "C";
  search_mode: "dedicated_adapter" | "official_page";
};

type JobLeadStatus =
  | "NEW"
  | "VERIFYING"
  | "VERIFIED"
  | "NEEDS_BROWSER"
  | "NEEDS_USER"
  | "DUPLICATE"
  | "REJECTED_NON_JOB"
  | "FAILED";
type LeadSubmissionProvider = "manual_url" | "external_agent" | "third_party";
type JobVerificationStatus =
  | "VERIFIED_OFFICIAL"
  | "VERIFIED_SOURCE"
  | "USER_PROVIDED"
  | "LEGACY_UNVERIFIED";
type JobAvailabilityStatus = "ACTIVE" | "UNKNOWN" | "STALE" | "CLOSED";

type JobLeadItem = {
  id: string;
  discovery_run_id: string | null;
  provider: "official_adapter" | LeadSubmissionProvider;
  source_id: string | null;
  source_job_id: string | null;
  source_url: string;
  normalized_url: string;
  company_hint: string | null;
  title_hint: string | null;
  search_snippet: string | null;
  status: JobLeadStatus;
  next_action?: string;
  job_posting_id: string | null;
  failure_code: string | null;
  failure_reason: string | null;
  discovered_at: string;
  verified_at: string | null;
  created_at: string;
  updated_at: string;
};

const eligibilityLabel: Record<AnalysisResponse["eligibility"]["eligible"], string> = {
  pass: "资格通过",
  fail: "存在硬性风险",
  unknown: "需要确认",
};

const decisionLabel: Record<NonNullable<AnalysisResponse["decision"]>["recommendation"], string> = {
  recommended_application: "推荐申请",
  consider: "可以考虑",
  not_recommended: "不建议申请",
  insufficient_information: "信息不足",
};

const supportLabel: Record<SupportLevel, string> = {
  supported: "有证据",
  partial: "部分匹配",
  needs_confirmation: "待确认",
  unsupported: "无证据",
};

const relationLabel: Record<NonNullable<JobRequirement["relation"]>, string> = {
  all_of: "全部满足",
  any_of: "任选其一",
  uncertain: "关系待确认",
};

const groupLabel: Record<string, string> = {
  required_skill: "必备技能",
  preferred_skill: "加分技能",
  preferences: "偏好条件",
};

const jobTypeLabel: Record<string, string> = {
  campus: "校招",
  internship: "实习",
  full_time: "全职",
  part_time: "兼职",
  unknown: "待确认",
};

const applicationStatusLabel: Record<ApplicationStatus, string> = {
  PREPARING: "准备申请",
  SUBMITTED: "已投递",
  ASSESSMENT: "笔试 / 测评",
  INTERVIEW: "面试",
  OFFER: "Offer",
  REJECTED: "已拒绝",
  WITHDRAWN: "已放弃",
};

const applicationEventLabel: Record<string, string> = {
  ApplicationCreated: "创建申请",
  ApplicationStatusChanged: "更新申请状态",
  ApplicationAttemptCreated: "创建投递尝试",
  ApplicationAttemptStatusChanged: "更新投递执行",
  ApplicationBlockerOpened: "记录投递阻塞",
  ApplicationBlockerResolved: "解决投递阻塞",
  SubmissionReceiptRecorded: "保存提交凭证",
  ApplicationSubmissionVerified: "确认真实投递",
  FollowUpTaskCreated: "创建跟进任务",
  FollowUpTaskUpdated: "更新跟进任务",
  FollowUpTaskCompleted: "完成跟进任务",
  FollowUpTaskCancelled: "取消跟进任务",
  AtsAssistanceInspected: "检查 ATS 表单",
  AtsAssistanceNeedsUser: "ATS 请求人工接管",
  AtsSensitiveFieldsConfirmed: "确认 ATS 高影响字段",
  AtsAssistancePrepared: "验证 ATS 填写结果",
  AtsSubmissionAuthorized: "签发 ATS 一次性授权",
  AtsSubmissionStarted: "执行 ATS 提交",
  AtsSubmissionUnverified: "ATS 提交结果待核对",
  AtsSubmissionVerified: "验证 ATS 提交凭证",
  SuggestionCreated: "生成材料建议",
  SuggestionDecisionRecorded: "记录材料决策",
};

const attemptStatusLabel: Record<string, string> = {
  CREATED: "待打开",
  FORM_IN_PROGRESS: "填写中",
  NEEDS_USER: "需要用户处理",
  BLOCKED: "已阻塞",
  READY_TO_SUBMIT: "待确认提交",
  SUBMITTED: "已验证投递",
  FAILED: "本次失败",
  ABANDONED: "已结束",
};

const followUpEventTypeLabel: Record<string, string> = {
  ASSESSMENT: "在线测评",
  WRITTEN_TEST: "笔试",
  INTERVIEW: "面试",
  MATERIAL_DEADLINE: "材料截止",
  OUTREACH: "主动跟进",
  CUSTOM: "自定义事项",
};

const candidateStatusLabel: Record<CandidateStatus, string> = {
  DISCOVERED: "刚发现",
  SAVED: "已保存",
  IGNORED: "已忽略",
  CONVERTED: "已进入申请",
};

const discoveryRunStatusLabel: Record<DiscoveryRunItem["status"], string> = {
  RUNNING: "同步中",
  SUCCEEDED: "已完成",
  PARTIAL: "部分完成",
  FAILED: "失败",
};

const discoveryTraceOutcomeLabel: Record<string, string> = {
  selected: "已选择",
  succeeded: "已验证",
  partial: "部分完成",
  empty: "没有事实",
  failed: "工具失败",
  needs_adapter: "需要适配",
  route_exhausted: "路线耗尽",
  recommended: "建议人工接管",
};

const discoveryStopConditionLabel: Record<string, string> = {
  max_results_reached: "达到结果上限",
  source_route_exhausted: "来源路线耗尽",
  no_verified_jobs_requires_human_input: "无事实时人工接管",
};

const jobLeadStatusLabel: Record<JobLeadStatus, string> = {
  NEW: "待验证",
  VERIFYING: "验证中",
  VERIFIED: "已验证",
  NEEDS_BROWSER: "需要浏览器",
  NEEDS_USER: "需要处理",
  DUPLICATE: "已关联岗位",
  REJECTED_NON_JOB: "不是岗位页",
  FAILED: "验证失败",
};

const leadProviderLabel: Record<JobLeadItem["provider"], string> = {
  official_adapter: "官方 Adapter",
  manual_url: "手动 URL",
  external_agent: "外部 Agent",
  third_party: "第三方平台",
};

const verificationStatusLabel: Record<JobVerificationStatus, string> = {
  VERIFIED_OFFICIAL: "官方来源已验证",
  VERIFIED_SOURCE: "页面正文已验证",
  USER_PROVIDED: "用户提供",
  LEGACY_UNVERIFIED: "历史未验证",
};

const availabilityStatusLabel: Record<JobAvailabilityStatus, string> = {
  ACTIVE: "开放中",
  UNKNOWN: "开放状态未知",
  STALE: "可能过期",
  CLOSED: "已关闭",
};

const featuredDiscoveryCompanyIds = [
  "bytedance",
  "tencent",
  "alibaba",
  "baidu",
  "meituan",
  "jd",
  "huawei",
  "xiaohongshu",
  "xiaomi",
  "kuaishou",
];

const jobTypeShortLabel: Record<string, string> = {
  campus: "校招",
  internship: "实习",
  full_time: "全职",
  part_time: "兼职",
  unknown: "类型待确认",
};

const suggestionStatusLabel: Record<SuggestionStatus, string> = {
  PENDING: "待审批",
  ACCEPTED: "已采用",
  REJECTED: "已拒绝",
};

const boardColumns: Array<{
  status: ApplicationStatus;
  label: string;
  tone: "acid" | "coral" | "blue" | "ink";
}> = [
  { status: "PREPARING", label: "准备申请", tone: "acid" },
  { status: "SUBMITTED", label: "已投递", tone: "blue" },
  { status: "ASSESSMENT", label: "笔试 / 测评", tone: "blue" },
  { status: "INTERVIEW", label: "面试", tone: "coral" },
  { status: "OFFER", label: "Offer", tone: "acid" },
  { status: "REJECTED", label: "已拒绝", tone: "ink" },
  { status: "WITHDRAWN", label: "已放弃", tone: "ink" },
];

const profileJobTypeOptions: Array<{ value: ProfileJobType; label: string }> = [
  { value: "campus", label: "校招" },
  { value: "internship", label: "实习" },
  { value: "full_time", label: "全职" },
  { value: "part_time", label: "兼职" },
];

const evidenceTypeOptions = [
  { value: "project", label: "项目" },
  { value: "skill", label: "技能" },
  { value: "education", label: "教育" },
  { value: "experience", label: "经历" },
  { value: "certificate", label: "证书" },
];

const emptyEvidenceDraft: EvidenceDraft = {
  type: "project",
  title: "",
  claim: "",
  skills: "",
  source: "resume_manual",
};

function splitList(value: string): string[] {
  return value
    .split(/[,，、\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function joinList(value: string[] | null | undefined): string {
  return value?.join("、") ?? "";
}

function compactList(items: string[] | null | undefined): string {
  return items && items.length > 0 ? items.join(" · ") : "未识别";
}

async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as {
      error?: { message?: string; code?: string };
    };
    return payload.error?.message ?? `请求失败（${response.status}）`;
  } catch {
    return `请求失败（${response.status}）`;
  }
}

export default function Home() {
  const [isHydrated, setIsHydrated] = useState(false);
  const [mode, setMode] = useState<WorkspaceMode>("discover");
  const [resumeModalOpen, setResumeModalOpen] = useState(false);
  const [resumeAdvancedOpen, setResumeAdvancedOpen] = useState(false);
  const [manualJobModalOpen, setManualJobModalOpen] = useState(false);
  const [profileSummary, setProfileSummary] = useState<ProfileSummary>({
    state: "loading",
    resumeCount: 0,
    evidenceCount: 0,
  });
  const [rawContent, setRawContent] = useState("");
  const [company, setCompany] = useState("");
  const [title, setTitle] = useState("");
  const [state, setState] = useState<AnalysisState>("empty");
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [applications, setApplications] = useState<ApplicationItem[]>([]);
  const [boardState, setBoardState] = useState<BoardState>("idle");
  const [boardMessage, setBoardMessage] = useState("");
  const [updatingApplicationId, setUpdatingApplicationId] = useState<string | null>(null);
  const [preparingApplication, setPreparingApplication] = useState(false);
  const [candidates, setCandidates] = useState<CandidateItem[]>([]);
  const [jobLeads, setJobLeads] = useState<JobLeadItem[]>([]);
  const [discoveryRuns, setDiscoveryRuns] = useState<DiscoveryRunItem[]>([]);
  const [discoveryState, setDiscoveryState] = useState<DiscoveryState>("idle");
  const [discoveryMessage, setDiscoveryMessage] = useState("");
  const [discoveryQuery, setDiscoveryQuery] = useState("北京 / 上海的 AI Agent、LLM、算法校招岗位");
  const [discoverySources, setDiscoverySources] = useState<DiscoverySourceOption[]>([]);
  const [selectedDiscoveryCompanyIds, setSelectedDiscoveryCompanyIds] = useState<string[]>([]);
  const [discoverySourceUrl, setDiscoverySourceUrl] = useState("");
  const [discoveryCompany, setDiscoveryCompany] = useState("");
  const [updatingCandidateId, setUpdatingCandidateId] = useState<string | null>(null);
  const [updatingAvailabilityJobId, setUpdatingAvailabilityJobId] = useState<string | null>(null);
  const [leadProvider, setLeadProvider] = useState<LeadSubmissionProvider>("manual_url");
  const [leadUrl, setLeadUrl] = useState("");
  const [leadCompany, setLeadCompany] = useState("");
  const [leadTitle, setLeadTitle] = useState("");
  const [leadSnippet, setLeadSnippet] = useState("");
  const [submittingLead, setSubmittingLead] = useState(false);
  const [updatingLeadId, setUpdatingLeadId] = useState<string | null>(null);
  const [manualHandoffLeadId, setManualHandoffLeadId] = useState<string | null>(null);
  const jobLeadRevisionRef = useRef(0);

  async function loadProfileSummary() {
    setProfileSummary((current) => ({ ...current, state: "loading" }));
    try {
      const headers = { "X-User-ID": userId };
      const [resumeResponse, evidenceResponse] = await Promise.all([
        fetch(`${apiUrl}/api/resumes/versions`, { headers, cache: "no-store" }),
        fetch(`${apiUrl}/api/evidence`, { headers, cache: "no-store" }),
      ]);
      if (!resumeResponse.ok && resumeResponse.status !== 404) {
        throw new Error(await readError(resumeResponse));
      }
      if (!evidenceResponse.ok && evidenceResponse.status !== 404) {
        throw new Error(await readError(evidenceResponse));
      }
      const resumeCount = resumeResponse.ok
        ? ((await resumeResponse.json()) as Array<{ id: string }>).length
        : 0;
      const evidenceCount = evidenceResponse.ok
        ? ((await evidenceResponse.json()) as Array<{ id: string }>).length
        : 0;
      setProfileSummary({
        state: resumeCount === 0 ? "missing_resume" : evidenceCount === 0 ? "missing_evidence" : "ready",
        resumeCount,
        evidenceCount,
      });
    } catch (error) {
      console.error("profile_summary_load_failed", error);
      setProfileSummary((current) => ({ ...current, state: "error" }));
    }
  }

  async function loadApplications() {
    setBoardState("loading");
    setBoardMessage("");
    try {
      const response = await fetch(`${apiUrl}/api/applications`, {
        headers: { "X-User-ID": userId },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(await readError(response));
      setApplications((await response.json()) as ApplicationItem[]);
      setBoardState("ready");
    } catch (error) {
      setBoardState("error");
      setBoardMessage(error instanceof Error ? error.message : "申请看板加载失败。 ");
    }
  }

  useEffect(() => {
    if (mode === "board") void loadApplications();
    if (mode === "discover") void loadDiscoveryData();
  }, [mode]);

  useEffect(() => {
    setIsHydrated(true);
    void loadProfileSummary();
  }, []);

  async function loadDiscoveryData(options: { quiet?: boolean } = {}) {
    if (!options.quiet) setDiscoveryState("loading");
    const leadRevision = jobLeadRevisionRef.current;
    try {
      const [candidateResponse, leadResponse, runResponse, sourceResponse] = await Promise.all([
        fetch(`${apiUrl}/api/candidates`, {
          headers: { "X-User-ID": userId },
          cache: "no-store",
        }),
        fetch(`${apiUrl}/api/discovery/leads`, {
          headers: { "X-User-ID": userId },
          cache: "no-store",
        }),
        fetch(`${apiUrl}/api/discovery/runs`, {
          headers: { "X-User-ID": userId },
          cache: "no-store",
        }),
        fetch(`${apiUrl}/api/discovery/sources`, { cache: "no-store" }),
      ]);
      if (!candidateResponse.ok) throw new Error(await readError(candidateResponse));
      if (!leadResponse.ok) throw new Error(await readError(leadResponse));
      if (!runResponse.ok) throw new Error(await readError(runResponse));
      if (!sourceResponse.ok) throw new Error(await readError(sourceResponse));
      setCandidates((await candidateResponse.json()) as CandidateItem[]);
      const loadedLeads = (await leadResponse.json()) as JobLeadItem[];
      if (leadRevision === jobLeadRevisionRef.current) {
        setJobLeads(loadedLeads);
      }
      setDiscoveryRuns((await runResponse.json()) as DiscoveryRunItem[]);
      setDiscoverySources((await sourceResponse.json()) as DiscoverySourceOption[]);
      if (!options.quiet) setDiscoveryState("ready");
    } catch (error) {
      if (!options.quiet) {
        setDiscoveryState("error");
        setDiscoveryMessage(error instanceof Error ? error.message : "岗位发现池加载失败。");
      }
    }
  }

  async function runDiscovery() {
    if (discoveryQuery.trim().length < 2) {
      setDiscoveryState("error");
      setDiscoveryMessage("请先描述想找的岗位，例如：上海的 AI Agent 校招。");
      return;
    }
    setDiscoveryState("loading");
    setDiscoveryMessage("正在全网搜索岗位线索，并核验原始岗位页…");
    try {
      const response = await fetch(`${apiUrl}/api/discovery/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({
          query: discoveryQuery.trim(),
          source_mode: "web",
          company_ids: selectedDiscoveryCompanyIds.length > 0 ? selectedDiscoveryCompanyIds : null,
        }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const run = (await response.json()) as DiscoveryRunItem;
      setDiscoveryRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
      void pollDiscoveryRun(run.id);
    } catch (error) {
      setDiscoveryState("error");
      setDiscoveryMessage(error instanceof Error ? error.message : "全网岗位搜索启动失败。");
    }
  }

  async function pollDiscoveryRun(runId: string) {
    for (let attempt = 0; attempt < 240; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
      try {
        const response = await fetch(`${apiUrl}/api/discovery/runs/${runId}`, {
          headers: { "X-User-ID": userId },
          cache: "no-store",
        });
        if (!response.ok) throw new Error(await readError(response));
        const run = (await response.json()) as DiscoveryRunItem;
        setDiscoveryRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
        const strictCount = countDiscoveryMatches(run, "strict");
        const expandedCount = countDiscoveryMatches(run, "expanded");
        const verifiedCount = strictCount + expandedCount;
        setDiscoveryMessage(
          run.analysis_target_count > 0
            ? `严格匹配 ${strictCount} 条，自动分析 ${run.analysis_completed_count}/${run.analysis_target_count} 条；拓展候选 ${expandedCount} 条。`
            : verifiedCount > 0
              ? `已核验 ${verifiedCount} 条岗位：严格匹配 ${strictCount} 条，拓展候选 ${expandedCount} 条。`
              : run.discovered_count > 0
                ? `已找到 ${run.discovered_count} 条线索，正在核验原始岗位页…`
                : "正在搜索公开岗位…",
        );
        if (run.status !== "RUNNING") {
          await loadDiscoveryData({ quiet: true });
          setDiscoveryState(run.status === "FAILED" ? "error" : "ready");
          setDiscoveryMessage(
            verifiedCount === 0
              ? run.discovered_count > 0
                ? `找到 ${run.discovered_count} 条线索，但暂时没有可自动核验的岗位；可在线索区继续用浏览器核验。`
                : "全网暂未找到可验证岗位。你可以调整搜索目标，或直接添加一条岗位。"
              : strictCount === 0
                ? `没有严格匹配。另找到 ${expandedCount} 条真实岗位，但地点、招聘类型或方向已放宽，默认不自动分析。`
                : `搜索完成：严格匹配 ${strictCount} 条，拓展候选 ${expandedCount} 条；自动分析 ${run.analysis_completed_count}/${run.analysis_target_count} 条。`,
          );
          return;
        }
      } catch (error) {
        setDiscoveryState("error");
        setDiscoveryMessage(error instanceof Error ? error.message : "搜索进度读取失败。");
        return;
      }
    }
    setDiscoveryState("error");
    setDiscoveryMessage("搜索时间超过预期，请刷新候选池查看已经保存的岗位。");
  }

  async function runManualDiscovery() {
    if (!discoverySourceUrl.trim()) {
      setDiscoveryMessage("请先输入一个 Greenhouse board URL。");
      return;
    }
    setDiscoveryState("loading");
    setDiscoveryMessage("正在读取指定来源并进行去重…");
    try {
      const response = await fetch(`${apiUrl}/api/discovery/runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({
          source_url: discoverySourceUrl.trim(),
          company: discoveryCompany.trim() || null,
        }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const run = (await response.json()) as DiscoveryRunItem;
      await loadDiscoveryData({ quiet: true });
      setDiscoveryState("ready");
      setDiscoveryMessage(
        `指定来源同步完成：发现 ${run.discovered_count} 条，新增 ${run.new_count} 条，重复 ${run.duplicate_count} 条。`,
      );
    } catch (error) {
      setDiscoveryState("error");
      setDiscoveryMessage(error instanceof Error ? error.message : "岗位来源同步失败。");
    }
  }

  async function submitJobLead() {
    if (!leadUrl.trim()) {
      setDiscoveryMessage("请先输入一条具体岗位 URL。");
      return;
    }
    setSubmittingLead(true);
    setDiscoveryMessage("");
    try {
      const response = await fetch(`${apiUrl}/api/discovery/leads`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({
          provider: leadProvider,
          source_url: leadUrl.trim(),
          company_hint: leadCompany.trim() || null,
          title_hint: leadTitle.trim() || null,
          search_snippet: leadSnippet.trim() || null,
        }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const created = (await response.json()) as JobLeadItem;
      jobLeadRevisionRef.current += 1;
      setJobLeads((current) => [created, ...current.filter((item) => item.id !== created.id)]);
      setLeadUrl("");
      setLeadCompany("");
      setLeadTitle("");
      setLeadSnippet("");
      setDiscoveryMessage("岗位线索已保存。它仍是待验证信息，不会提前进入候选池。");
    } catch (error) {
      setDiscoveryMessage(error instanceof Error ? error.message : "岗位线索提交失败。");
    } finally {
      setSubmittingLead(false);
    }
  }

  async function verifyJobLead(leadId: string) {
    setUpdatingLeadId(leadId);
    setDiscoveryMessage("正在读取岗位正文并核对来源…");
    try {
      const response = await fetch(`${apiUrl}/api/discovery/leads/${leadId}/verify`, {
        method: "POST",
        headers: { "X-User-ID": userId },
      });
      if (!response.ok) {
        const errorMessage = await readError(response);
        await loadDiscoveryData({ quiet: true });
        throw new Error(errorMessage);
      }
      const verified = (await response.json()) as JobLeadItem;
      await loadDiscoveryData({ quiet: true });
      setDiscoveryMessage(
        verified.status === "DUPLICATE"
          ? "验证完成：该线索已关联到现有岗位，没有创建重复记录。"
          : "验证完成：岗位已进入可信候选池。",
      );
    } catch (error) {
      setDiscoveryMessage(error instanceof Error ? error.message : "岗位线索验证失败。");
    } finally {
      setUpdatingLeadId(null);
    }
  }

  async function verifyJobLeadWithBrowser(leadId: string) {
    setUpdatingLeadId(leadId);
    setDiscoveryMessage("正在启动只读浏览器并核对动态页面…");
    try {
      const response = await fetch(`${apiUrl}/api/discovery/leads/${leadId}/handoff/browser`, {
        method: "POST",
        headers: { "X-User-ID": userId },
      });
      if (!response.ok) {
        const message = await readError(response);
        await loadDiscoveryData({ quiet: true });
        throw new Error(message);
      }
      const verified = (await response.json()) as JobLeadItem;
      await loadDiscoveryData({ quiet: true });
      setDiscoveryMessage(
        verified.status === "DUPLICATE"
          ? "浏览器验证完成：已关联到现有岗位。"
          : "浏览器验证完成：动态岗位已进入可信候选池。",
      );
    } catch (error) {
      setDiscoveryMessage(error instanceof Error ? error.message : "浏览器接管失败。");
    } finally {
      setUpdatingLeadId(null);
    }
  }

  async function checkJobAvailability(jobId: string) {
    setUpdatingAvailabilityJobId(jobId);
    setDiscoveryMessage("正在重新读取官方岗位页…");
    try {
      const response = await fetch(`${apiUrl}/api/jobs/${jobId}/availability/check`, {
        method: "POST",
        headers: { "X-User-ID": userId },
      });
      if (!response.ok) throw new Error(await readError(response));
      const check = (await response.json()) as { result_status: JobAvailabilityStatus };
      await loadDiscoveryData({ quiet: true });
      setDiscoveryMessage(`开放状态检查完成：${availabilityStatusLabel[check.result_status]}。`);
    } catch (error) {
      setDiscoveryMessage(error instanceof Error ? error.message : "岗位开放状态检查失败。");
    } finally {
      setUpdatingAvailabilityJobId(null);
    }
  }

  async function updateCandidate(candidateId: string, status: CandidateStatus) {
    setUpdatingCandidateId(candidateId);
    setDiscoveryMessage("");
    try {
      const response = await fetch(`${apiUrl}/api/candidates/${candidateId}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({ status }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const updated = (await response.json()) as CandidateItem;
      setCandidates((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (error) {
      setDiscoveryMessage(error instanceof Error ? error.message : "候选岗位状态更新失败。");
    } finally {
      setUpdatingCandidateId(null);
    }
  }

  async function openCandidate(jobId: string) {
    setMode("analysis");
    setState("loading");
    setErrorMessage("");
    try {
      const [response, analysisResponse] = await Promise.all([
        fetch(`${apiUrl}/api/jobs/${jobId}`, { cache: "no-store" }),
        fetch(`${apiUrl}/api/jobs/${jobId}/analysis`, {
          headers: { "X-User-ID": userId },
          cache: "no-store",
        }),
      ]);
      if (!response.ok) throw new Error(await readError(response));
      const posting = (await response.json()) as {
        raw_content: string;
        company: string | null;
        title: string | null;
      };
      setRawContent(posting.raw_content);
      setCompany(posting.company ?? "");
      setTitle(posting.title ?? "");
      setManualHandoffLeadId(null);
      if (analysisResponse.ok) {
        setAnalysis((await analysisResponse.json()) as AnalysisResponse);
        setState("success");
      } else if (analysisResponse.status === 404 || analysisResponse.status === 409) {
        setAnalysis(null);
        setState("empty");
      } else {
        throw new Error(await readError(analysisResponse));
      }
    } catch (error) {
      setAnalysis(null);
      setState("error");
      setErrorMessage(error instanceof Error ? error.message : "岗位详情加载失败。");
    }
  }

  function openManualJD(leadId?: string) {
    const lead = leadId ? jobLeads.find((item) => item.id === leadId) : null;
    setRawContent("");
    setCompany(lead?.company_hint ?? "");
    setTitle(lead?.title_hint ?? "");
    setManualHandoffLeadId(lead?.id ?? null);
    setAnalysis(null);
    setState("empty");
    setErrorMessage("");
    setManualJobModalOpen(true);
  }

  async function runAnalysis() {
    if (rawContent.trim().length < 20) {
      setState("error");
      setErrorMessage("岗位文本至少需要 20 个字符，才能开始分析。");
      return;
    }

    setState("loading");
    setErrorMessage("");
    try {
      let posting: { id: string };
      if (manualHandoffLeadId) {
        const handoffResponse = await fetch(
          `${apiUrl}/api/discovery/leads/${manualHandoffLeadId}/handoff/manual-jd`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-User-ID": userId },
            body: JSON.stringify({
              company: company.trim() || null,
              title: title.trim() || null,
              raw_content: rawContent,
            }),
          },
        );
        if (!handoffResponse.ok) throw new Error(await readError(handoffResponse));
        const completed = (await handoffResponse.json()) as JobLeadItem;
        if (!completed.job_posting_id) throw new Error("接管完成后没有生成可分析的岗位。");
        posting = { id: completed.job_posting_id };
      } else {
        const importResponse = await fetch(`${apiUrl}/api/jobs/import-text`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            company: company.trim() || null,
            title: title.trim() || null,
            raw_content: rawContent,
          }),
        });
        if (!importResponse.ok) throw new Error(await readError(importResponse));
        posting = (await importResponse.json()) as { id: string };
      }

      const analysisResponse = await fetch(
        `${apiUrl}/api/jobs/${posting.id}/analyze`,
        {
          method: "POST",
          headers: { "X-User-ID": userId },
          cache: "no-store",
        },
      );
      if (!analysisResponse.ok) {
        throw new Error(await readError(analysisResponse));
      }
      setAnalysis((await analysisResponse.json()) as AnalysisResponse);
      setManualHandoffLeadId(null);
      setState("success");
      setManualJobModalOpen(false);
      setMode("analysis");
      void loadDiscoveryData({ quiet: true });
    } catch (error) {
      setState("error");
      setErrorMessage(error instanceof Error ? error.message : "分析失败，请稍后重试。");
    }
  }

  async function prepareApplication() {
    if (!analysis) return;
    setPreparingApplication(true);
    setBoardMessage("正在创建申请记录…");
    try {
      const candidateResponse = await fetch(`${apiUrl}/api/candidates`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({ job_posting_id: analysis.job.id }),
      });
      if (!candidateResponse.ok) throw new Error(await readError(candidateResponse));
      const candidate = (await candidateResponse.json()) as { id: string };
      const applicationResponse = await fetch(
        `${apiUrl}/api/candidates/${candidate.id}/prepare-application`,
        {
          method: "POST",
          headers: { "X-User-ID": userId },
        },
      );
      if (!applicationResponse.ok) throw new Error(await readError(applicationResponse));
      await loadApplications();
      setBoardMessage("申请记录已创建，接下来由你手动推进状态。 ");
      setMode("board");
    } catch (error) {
      setBoardMessage(error instanceof Error ? error.message : "申请创建失败。 ");
    } finally {
      setPreparingApplication(false);
    }
  }

  async function transitionApplication(applicationId: string, status: ApplicationStatus) {
    setUpdatingApplicationId(applicationId);
    setBoardMessage("");
    try {
      const response = await fetch(`${apiUrl}/api/applications/${applicationId}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({ status }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const updated = (await response.json()) as ApplicationItem;
      setApplications((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (error) {
      setBoardMessage(error instanceof Error ? error.message : "状态更新失败。 ");
    } finally {
      setUpdatingApplicationId(null);
    }
  }

  const profileStatusTitle = profileSummary.state === "ready"
    ? "个人资料已就绪"
    : profileSummary.state === "missing_resume"
      ? "尚未上传简历"
      : profileSummary.state === "missing_evidence"
        ? "简历已上传"
        : profileSummary.state === "loading"
          ? "正在检查个人资料"
          : "个人资料状态暂不可用";
  const profileStatusDetail = profileSummary.state === "ready"
    ? `${profileSummary.evidenceCount} 条经历证据`
    : profileSummary.state === "missing_resume"
      ? "点击上传"
      : profileSummary.state === "missing_evidence"
        ? "待补充经历证据"
        : profileSummary.state === "loading"
          ? "请稍候"
          : "点击检查";
  const discoveredCount = candidates.filter((item) => item.status === "DISCOVERED").length;

  return (
    <main className={`workspace-shell${isHydrated ? " workspace-hydrated" : ""}`}>
      <header className="workspace-topbar">
        <div className="brand-lockup">
          <span className="brand-mark">JF</span>
          <span className="brand-name">JobFlow</span>
        </div>
        <div className="topbar-trail">
          <button
            className={`profile-status-trigger profile-status-${profileSummary.state}`}
            disabled={!isHydrated}
            onClick={() => {
              void loadProfileSummary();
              setResumeModalOpen(true);
            }}
            type="button"
            aria-label={`${profileStatusTitle}，${profileStatusDetail}。打开简历管理`}
          >
            <span className="profile-status-mark" aria-hidden="true">
              {profileSummary.state === "ready" ? "✓" : profileSummary.state === "loading" ? "…" : "!"}
            </span>
            <span>
              <strong>{profileStatusTitle}</strong>
              <small>{profileStatusDetail}</small>
            </span>
          </button>
        </div>
      </header>

      <div className="workspace-frame">
        <aside className="workspace-sidebar">
          <span className="workspace-nav-label">工作区</span>
          <nav className="workspace-nav" aria-label="工作区导航">
            <button
              aria-current={mode === "discover" || mode === "analysis" ? "page" : undefined}
              aria-label={`发现岗位，${discoveredCount} 条候选`}
              className={mode === "discover" || mode === "analysis" ? "workspace-nav-active" : ""}
              disabled={!isHydrated}
              onClick={() => setMode("discover")}
              type="button"
            >
              <span className="workspace-nav-index" aria-hidden="true">01</span>
              <strong>发现岗位</strong>
              <span className="workspace-nav-count">{discoveredCount}</span>
            </button>
            <button
              aria-current={mode === "board" ? "page" : undefined}
              className={mode === "board" ? "workspace-nav-active" : ""}
              disabled={!isHydrated}
              onClick={() => setMode("board")}
              type="button"
            >
              <span className="workspace-nav-index" aria-hidden="true">02</span>
              <strong>申请进度</strong>
              <span className="workspace-nav-count">{applications.length}</span>
            </button>
            <button
              aria-current={mode === "profile" ? "page" : undefined}
              className={mode === "profile" ? "workspace-nav-active" : ""}
              disabled={!isHydrated}
              onClick={() => setMode("profile")}
              type="button"
            >
              <span className="workspace-nav-index" aria-hidden="true">03</span>
              <strong>我的经历</strong>
            </button>
          </nav>
        </aside>

        <div className="workspace-content">
          <section className={`workspace-intro workspace-intro-${mode}`}>
            <div>
              <p className="eyebrow">
                {mode === "analysis" ? "岗位匹配" : mode === "discover" ? "岗位发现" : mode === "profile" ? "个人资料" : "申请管理"}
              </p>
              <h1>
                {mode === "analysis"
                  ? "岗位匹配详情"
                  : mode === "discover"
                    ? "发现适合你的岗位"
                    : mode === "profile"
                      ? "核对你的经历"
                      : "跟进每份申请"}
              </h1>
            </div>
            <p className="intro-note">
              {mode === "profile"
                ? "这里优先展示从简历自动解析的经历。确认或修改后，它们会成为岗位匹配的依据。"
                : mode === "discover"
                  ? "搜索全网公开岗位，或添加你已经看到的岗位。"
                  : mode === "analysis"
                    ? "根据岗位原文和你确认过的经历，查看匹配依据与申请建议。"
                    : "查看当前状态、下一步和关键时间。"}
            </p>
          </section>

          {mode === "profile" ? (
            <ProfileWorkspace apiUrl={apiUrl} userId={userId} onProfileChange={loadProfileSummary} />
          ) : mode === "analysis" ? (
            <section className="analysis-detail">
              <header className="analysis-detail-header">
                <button className="analysis-back" onClick={() => setMode("discover")} type="button">
                  <span aria-hidden="true">←</span> 返回岗位列表
                </button>
                <div className="analysis-job-title">
                  <span>{company || analysis?.job.company || "公司待确认"}</span>
                  <h2>{title || analysis?.job.title || "岗位详情"}</h2>
                </div>
                <div className="analysis-detail-actions">
                  <button onClick={() => setMode("profile")} type="button">编辑经历</button>
                  <button className="analysis-run" disabled={state === "loading" || rawContent.trim().length < 20} onClick={() => void runAnalysis()} type="button">
                    {state === "loading" ? "分析中…" : state === "success" ? "重新分析" : "开始匹配"}
                  </button>
                </div>
              </header>

              <details className="analysis-source">
                <summary>查看岗位原文</summary>
                <pre>{rawContent || "暂无岗位原文"}</pre>
              </details>

              <section className={`result-panel result-${state}`} aria-live="polite">
                <div className="result-heading">
                  <div>
                    <div className="section-kicker">匹配结果</div>
                    <p className="result-subtitle">
                      {profileSummary.evidenceCount > 0 ? `使用 ${profileSummary.evidenceCount} 条已确认经历` : "尚无可引用的经历"}
                    </p>
                  </div>
                  {state === "success" && analysis ? (
                    <span className={`eligibility-badge badge-${analysis.eligibility.eligible}`}>
                      <span className="badge-dot" />{eligibilityLabel[analysis.eligibility.eligible]}
                    </span>
                  ) : null}
                </div>

                {state === "empty" ? (
                  <div className="analysis-empty">
                    <h3>这个岗位还没有匹配结果</h3>
                    <p>{profileSummary.evidenceCount > 0 ? "开始后，系统会解析岗位要求，并只引用你确认过的经历。" : "建议先上传简历并核对经历，再开始匹配。"}</p>
                    <button disabled={rawContent.trim().length < 20} onClick={() => void runAnalysis()} type="button">开始匹配</button>
                  </div>
                ) : null}
                {state === "loading" ? <LoadingState /> : null}
                {state === "error" ? <ErrorState message={errorMessage} onRetry={runAnalysis} /> : null}
                {state === "success" && analysis ? (
                  <AnalysisResult
                    analysis={analysis}
                    onPrepareApplication={prepareApplication}
                    preparing={preparingApplication}
                  />
                ) : null}
              </section>
            </section>
          ) : mode === "discover" ? (
            <DiscoveryWorkspace
              candidates={candidates}
              leads={jobLeads}
              runs={discoveryRuns}
              state={discoveryState}
              message={discoveryMessage}
              query={discoveryQuery}
              sources={discoverySources}
              selectedCompanyIds={selectedDiscoveryCompanyIds}
              sourceUrl={discoverySourceUrl}
              company={discoveryCompany}
              updatingCandidateId={updatingCandidateId}
              updatingAvailabilityJobId={updatingAvailabilityJobId}
              leadProvider={leadProvider}
              leadUrl={leadUrl}
              leadCompany={leadCompany}
              leadTitle={leadTitle}
              leadSnippet={leadSnippet}
              submittingLead={submittingLead}
              updatingLeadId={updatingLeadId}
              onQueryChange={setDiscoveryQuery}
              onToggleCompany={(sourceId) => {
                setSelectedDiscoveryCompanyIds((current) => (
                  current.includes(sourceId)
                    ? current.filter((item) => item !== sourceId)
                    : [...current, sourceId]
                ));
              }}
              onSourceUrlChange={setDiscoverySourceUrl}
              onCompanyChange={setDiscoveryCompany}
              onLeadProviderChange={setLeadProvider}
              onLeadUrlChange={setLeadUrl}
              onLeadCompanyChange={setLeadCompany}
              onLeadTitleChange={setLeadTitle}
              onLeadSnippetChange={setLeadSnippet}
              onRun={runDiscovery}
              onManualRun={runManualDiscovery}
              onSubmitLead={submitJobLead}
              onVerifyLead={verifyJobLead}
              onBrowserLead={verifyJobLeadWithBrowser}
              onRefresh={loadDiscoveryData}
              onOpen={openCandidate}
              onPasteJD={(leadId) => openManualJD(leadId)}
              onUpdate={updateCandidate}
              onCheckAvailability={checkJobAvailability}
            />
          ) : (
            <ApplicationBoard
              applications={applications}
              state={boardState}
              message={boardMessage}
              updatingApplicationId={updatingApplicationId}
              onRefresh={loadApplications}
              onTransition={transitionApplication}
            />
          )}

          <footer className="workspace-footer">
            <span>JobFlow</span>
            <span>本地运行 · 数据由你确认</span>
          </footer>
        </div>
      </div>

      {resumeModalOpen ? (
        <ModalShell
          title={resumeAdvancedOpen ? "申请资料设置" : "简历管理"}
          description={resumeAdvancedOpen ? "这些资料只在准备申请时使用。" : "上传简历后，系统会自动解析经历，供你在“我的经历”中核对。"}
          onClose={() => {
            setResumeModalOpen(false);
            setResumeAdvancedOpen(false);
          }}
          wide={resumeAdvancedOpen}
        >
          <MaterialsWorkspace
            apiUrl={apiUrl}
            userId={userId}
            onResumeChange={loadProfileSummary}
            variant={resumeAdvancedOpen ? "full" : "resume-only"}
          />
          <div className="modal-secondary-action">
            <button onClick={() => setResumeAdvancedOpen((current) => !current)} type="button">
              {resumeAdvancedOpen ? "返回简历管理" : "高级申请资料"}
            </button>
          </div>
        </ModalShell>
      ) : null}

      {manualJobModalOpen ? (
        <ModalShell
          title={manualHandoffLeadId ? "补充岗位原文" : "添加岗位"}
          description="粘贴完整的岗位描述，系统会解析要求并与你已确认的经历进行匹配。"
          onClose={() => {
            setManualJobModalOpen(false);
            setManualHandoffLeadId(null);
          }}
        >
          <div className="manual-job-form">
            {manualHandoffLeadId ? (
              <div className="manual-job-context">
                <strong>正在补充一条无法自动读取的岗位</strong>
                <span>补充后会继续原来的岗位线索，不会创建重复记录。</span>
              </div>
            ) : null}
            <div className="field-pair">
              <label>
                <span>公司（可选）</span>
                <input value={company} onChange={(event) => setCompany(event.target.value)} placeholder="例如：字节跳动" />
              </label>
              <label>
                <span>岗位名称（可选）</span>
                <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：AI 应用开发" />
              </label>
            </div>
            <label className="textarea-label">
              <span>岗位描述</span>
              <textarea
                value={rawContent}
                onChange={(event) => setRawContent(event.target.value)}
                placeholder="粘贴岗位职责和任职要求，至少 20 个字符"
                rows={12}
              />
            </label>
            {state === "error" && errorMessage ? <div className="manual-job-error">{errorMessage}</div> : null}
            <div className="manual-job-footer">
              <span>{profileSummary.evidenceCount > 0 ? `将使用 ${profileSummary.evidenceCount} 条已确认经历` : "尚无已确认经历，匹配结果可能信息不足"}</span>
              <button disabled={state === "loading" || rawContent.trim().length < 20} onClick={() => void runAnalysis()} type="button">
                {state === "loading" ? "正在分析…" : manualHandoffLeadId ? "补充并分析" : "添加并分析"}
              </button>
            </div>
          </div>
        </ModalShell>
      ) : null}
    </main>
  );
}

function ModalShell({
  title,
  description,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  description: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

  return (
    <div className="workspace-modal-backdrop" onMouseDown={(event) => {
      if (event.currentTarget === event.target) onClose();
    }}>
      <section className={`workspace-modal ${wide ? "workspace-modal-wide" : ""}`} role="dialog" aria-modal="true" aria-labelledby="workspace-modal-title">
        <header className="workspace-modal-header">
          <div>
            <h2 id="workspace-modal-title">{title}</h2>
            <p>{description}</p>
          </div>
          <button onClick={onClose} type="button" aria-label="关闭弹窗">×</button>
        </header>
        <div className="workspace-modal-body">{children}</div>
      </section>
    </div>
  );
}

function ProfileWorkspace({
  apiUrl,
  userId,
  onProfileChange,
}: {
  apiUrl: string;
  userId: string;
  onProfileChange?: () => void;
}) {
  const [state, setState] = useState<ProfileWorkspaceState>("idle");
  const [message, setMessage] = useState("");
  const [profileForm, setProfileForm] = useState({
    displayName: "",
    graduationYear: "",
    degree: "",
    major: "",
    preferredLocations: "",
    jobTypes: [] as ProfileJobType[],
    targetRoles: "",
  });
  const [evidence, setEvidence] = useState<EvidenceRecord[]>([]);
  const [draft, setDraft] = useState<EvidenceDraft>(emptyEvidenceDraft);
  const [editingEvidenceId, setEditingEvidenceId] = useState<string | null>(null);
  const [evidenceComposerOpen, setEvidenceComposerOpen] = useState(false);
  const [savingEvidence, setSavingEvidence] = useState(false);
  const [deletingEvidenceId, setDeletingEvidenceId] = useState<string | null>(null);

  async function loadProfileData() {
    setState("loading");
    setMessage("");
    try {
      const [profileResponse, evidenceResponse] = await Promise.all([
        fetch(`${apiUrl}/api/profile`, {
          headers: { "X-User-ID": userId },
          cache: "no-store",
        }),
        fetch(`${apiUrl}/api/evidence`, {
          headers: { "X-User-ID": userId },
          cache: "no-store",
        }),
      ]);

      if (!profileResponse.ok && profileResponse.status !== 404) {
        throw new Error(await readError(profileResponse));
      }
      if (!evidenceResponse.ok) throw new Error(await readError(evidenceResponse));

      if (profileResponse.ok) {
        const profile = (await profileResponse.json()) as ProfileRecord;
        setProfileForm({
          displayName: profile.display_name ?? "",
          graduationYear: profile.graduation_year?.toString() ?? "",
          degree: profile.degree ?? "",
          major: profile.major ?? "",
          preferredLocations: joinList(profile.search_preferences.preferred_locations),
          jobTypes: profile.search_preferences.job_types ?? [],
          targetRoles: joinList(profile.search_preferences.target_roles),
        });
      }
      setEvidence((await evidenceResponse.json()) as EvidenceRecord[]);
      setState("ready");
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "个人资料暂时取不到。");
    }
  }

  useEffect(() => {
    void loadProfileData();
  }, []);

  async function saveProfile() {
    setState("saving");
    setMessage("");
    try {
      const graduationYear = profileForm.graduationYear.trim();
      const response = await fetch(`${apiUrl}/api/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({
          display_name: profileForm.displayName.trim() || null,
          graduation_year: graduationYear ? Number(graduationYear) : null,
          degree: profileForm.degree.trim() || null,
          major: profileForm.major.trim() || null,
          search_preferences: {
            preferred_locations: splitList(profileForm.preferredLocations).length > 0
              ? splitList(profileForm.preferredLocations)
              : null,
            job_types: profileForm.jobTypes.length > 0 ? profileForm.jobTypes : null,
            target_roles: splitList(profileForm.targetRoles).length > 0
              ? splitList(profileForm.targetRoles)
              : null,
          },
        }),
      });
      if (!response.ok) throw new Error(await readError(response));
      setState("ready");
      setMessage("个人画像已保存。下一次岗位分析会使用这份资料。");
      onProfileChange?.();
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "个人画像保存失败。");
    }
  }

  async function saveEvidence() {
    if (!draft.title.trim() || !draft.claim.trim()) {
      setMessage("请至少填写证据标题和事实描述。");
      return;
    }
    setSavingEvidence(true);
    setMessage("");
    try {
      const isEditing = Boolean(editingEvidenceId);
      const response = await fetch(
        isEditing ? `${apiUrl}/api/evidence/${editingEvidenceId}` : `${apiUrl}/api/evidence`,
        {
          method: isEditing ? "PATCH" : "POST",
          headers: { "Content-Type": "application/json", "X-User-ID": userId },
          body: JSON.stringify({
            type: draft.type,
            title: draft.title.trim(),
            claim: draft.claim.trim(),
            skills: splitList(draft.skills),
            source: draft.source.trim() || "resume_manual",
          }),
        },
      );
      if (!response.ok) throw new Error(await readError(response));
      const saved = (await response.json()) as EvidenceRecord;
      setEvidence((current) => isEditing
        ? current.map((item) => item.id === saved.id ? saved : item)
        : [saved, ...current]);
      setDraft(emptyEvidenceDraft);
      setEditingEvidenceId(null);
      setEvidenceComposerOpen(false);
      setMessage(isEditing ? "经历证据已更新。" : "经历证据已添加。" );
      onProfileChange?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "经历证据保存失败。");
    } finally {
      setSavingEvidence(false);
    }
  }

  function editEvidence(item: EvidenceRecord) {
    setEditingEvidenceId(item.id);
    setEvidenceComposerOpen(true);
    setDraft({
      type: item.type,
      title: item.title,
      claim: item.claim,
      skills: joinList(item.skills),
      source: item.source,
    });
    setMessage("正在编辑这条证据。保存后会立即用于后续匹配。");
  }

  function cancelEdit() {
    setEditingEvidenceId(null);
    setEvidenceComposerOpen(false);
    setDraft(emptyEvidenceDraft);
    setMessage("");
  }

  async function deleteEvidence(id: string) {
    if (!window.confirm("确认删除这条经历证据吗？已有分析不会被自动重算。")) return;
    setDeletingEvidenceId(id);
    setMessage("");
    try {
      const response = await fetch(`${apiUrl}/api/evidence/${id}`, {
        method: "DELETE",
        headers: { "X-User-ID": userId },
      });
      if (!response.ok) throw new Error(await readError(response));
      setEvidence((current) => current.filter((item) => item.id !== id));
      if (editingEvidenceId === id) cancelEdit();
      setMessage("经历证据已删除。新的岗位分析会使用更新后的证据集合。");
      onProfileChange?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "经历证据删除失败。");
    } finally {
      setDeletingEvidenceId(null);
    }
  }

  function toggleJobType(value: ProfileJobType) {
    setProfileForm((current) => ({
      ...current,
      jobTypes: current.jobTypes.includes(value)
        ? current.jobTypes.filter((item) => item !== value)
        : [...current.jobTypes, value],
    }));
  }

  return (
    <section className="profile-layout">
      <aside className="profile-identity-panel">
        <div className="section-kicker">基本信息</div>
        <h2>你的求职偏好</h2>
        <p className="profile-panel-note">这里保存资格判断需要的事实和求职偏好。没有填写的内容会在分析中保留为“需要确认”。</p>

        <div className="profile-form-grid">
          <label>
            <span>姓名 / 显示名</span>
            <input
              value={profileForm.displayName}
              onChange={(event) => setProfileForm((current) => ({ ...current, displayName: event.target.value }))}
              placeholder="例如：王永峥"
            />
          </label>
          <label>
            <span>毕业年份</span>
            <input
              type="number"
              min="2000"
              max="2100"
              value={profileForm.graduationYear}
              onChange={(event) => setProfileForm((current) => ({ ...current, graduationYear: event.target.value }))}
              placeholder="例如：2027"
            />
          </label>
          <label>
            <span>学历</span>
            <input
              value={profileForm.degree}
              onChange={(event) => setProfileForm((current) => ({ ...current, degree: event.target.value }))}
              placeholder="例如：硕士"
            />
          </label>
          <label>
            <span>专业</span>
            <input
              value={profileForm.major}
              onChange={(event) => setProfileForm((current) => ({ ...current, major: event.target.value }))}
              placeholder="例如：计算机技术"
            />
          </label>
        </div>

        <div className="profile-preferences">
          <div className="profile-subheading"><span>岗位偏好</span><small>可选</small></div>
          <label>
            <span>目标城市</span>
            <input
              value={profileForm.preferredLocations}
              onChange={(event) => setProfileForm((current) => ({ ...current, preferredLocations: event.target.value }))}
              placeholder="多个城市用顿号或逗号分隔"
            />
          </label>
          <label>
            <span>目标岗位</span>
            <input
              value={profileForm.targetRoles}
              onChange={(event) => setProfileForm((current) => ({ ...current, targetRoles: event.target.value }))}
              placeholder="例如：AI Agent工程师、大模型应用工程师"
            />
          </label>
          <div className="profile-job-types">
            <span>岗位类型</span>
            <div>
              {profileJobTypeOptions.map((option) => (
                <label className="profile-check" key={option.value}>
                  <input
                    type="checkbox"
                    checked={profileForm.jobTypes.includes(option.value)}
                    onChange={() => toggleJobType(option.value)}
                  />
                  <span>{option.label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>

        <button className="profile-save-button" disabled={state === "loading" || state === "saving"} onClick={saveProfile} type="button">
          {state === "saving" ? "正在保存…" : "保存个人画像 ↗"}
        </button>
      </aside>

      <section className="profile-evidence-panel">
        <div className="profile-section-heading">
          <div>
            <div className="section-kicker">匹配依据</div>
            <h2>核对自动解析的经历</h2>
          </div>
          <span className="profile-count">{evidence.length.toString().padStart(2, "0")} 条证据</span>
        </div>
        <p className="profile-section-note">上传简历后，系统会把项目和工作经历解析到这里。请核对事实；岗位匹配只会引用你保留的内容。</p>

        {message ? <div className={`profile-message ${state === "error" ? "profile-message-error" : ""}`}>{message}</div> : null}

        <details
          className="evidence-composer-collapsible"
          open={evidenceComposerOpen}
          onToggle={(event) => setEvidenceComposerOpen(event.currentTarget.open)}
        >
          <summary>{editingEvidenceId ? "正在编辑经历" : "手动补充一条经历"}<span aria-hidden="true">＋</span></summary>
          <div className="evidence-composer">
          <div className="evidence-composer-topline">
            <span>{editingEvidenceId ? "修改已保存的内容" : "简历中没有这条经历时，可在这里补充"}</span>
            <small>请只填写真实事实</small>
          </div>
          <div className="evidence-form-grid">
            <label>
              <span>类型</span>
              <select value={draft.type} onChange={(event) => setDraft((current) => ({ ...current, type: event.target.value }))}>
                {evidenceTypeOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label>
              <span>标题</span>
              <input value={draft.title} onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))} placeholder="例如：Code Agent Lab" />
            </label>
            <label>
              <span>技能标签</span>
              <input value={draft.skills} onChange={(event) => setDraft((current) => ({ ...current, skills: event.target.value }))} placeholder="例如：RAG、BM25、LangGraph" />
            </label>
            <label>
              <span>来源标记</span>
              <input value={draft.source} onChange={(event) => setDraft((current) => ({ ...current, source: event.target.value }))} placeholder="例如：resume_code_agent_lab" />
            </label>
          </div>
          <label className="evidence-claim-field">
            <span>事实描述</span>
            <textarea value={draft.claim} onChange={(event) => setDraft((current) => ({ ...current, claim: event.target.value }))} placeholder="写清楚你做了什么、使用了什么技术、得到什么结果。" rows={4} />
          </label>
          <div className="evidence-composer-footer">
            <small>示例：基于 AST 构建代码块索引，融合 BM25 与向量检索。</small>
            <div>
              {editingEvidenceId ? <button className="evidence-cancel" onClick={cancelEdit} type="button">取消编辑</button> : null}
              <button className="evidence-save" disabled={savingEvidence} onClick={saveEvidence} type="button">
                {savingEvidence ? "保存中…" : editingEvidenceId ? "更新证据 ↗" : "添加证据 ↗"}
              </button>
            </div>
          </div>
          </div>
        </details>

        <div className="evidence-list-heading">
          <span>已解析经历</span>
          <button className="profile-refresh" disabled={state === "loading"} onClick={() => void loadProfileData()} type="button">刷新</button>
        </div>
        {state === "loading" ? <div className="profile-empty">正在取回你的画像与经历…</div> : null}
        {state !== "loading" && evidence.length === 0 ? (
          <div className="profile-empty">
            <strong>还没有经历证据。</strong>
            <p>请先点击右上角上传简历，系统会自动解析其中的项目和工作经历。</p>
          </div>
        ) : null}
        {evidence.length > 0 ? (
          <div className="evidence-list">
            {evidence.map((item) => (
              <article className="evidence-card" key={item.id}>
                <div className="evidence-card-topline">
                  <span>{item.type}</span>
                  <div>
                    <button onClick={() => editEvidence(item)} type="button">编辑</button>
                    <button disabled={deletingEvidenceId === item.id} onClick={() => void deleteEvidence(item.id)} type="button">{deletingEvidenceId === item.id ? "删除中" : "删除"}</button>
                  </div>
                </div>
                <h3>{item.title}</h3>
                <p>{item.claim}</p>
                <div className="evidence-card-footer">
                  <div className="evidence-tags">
                    {item.skills.map((skill) => <span key={skill}>{skill}</span>)}
                  </div>
                  <small>{item.source}</small>
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </section>
    </section>
  );
}

function LoadingState() {
  return (
    <div className="loading-state">
      <div className="loading-orbit"><span /></div>
      <p className="loading-label">正在分析岗位</p>
      <h2>正在把岗位变成可判断的信号。</h2>
      <div className="loading-steps">
        <span className="loading-step-active">解析 JD</span><i>→</i><span>检查资格</span><i>→</i><span>匹配证据</span><i>→</i><span>生成建议</span>
      </div>
    </div>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="error-state">
      <div className="error-symbol">!</div>
      <p className="loading-label">ANALYSIS INTERRUPTED</p>
      <h2>这条岗位还没有变成可靠结论。</h2>
      <p>{message}</p>
      <button className="retry-button" onClick={onRetry} type="button">重新分析 <span aria-hidden="true">↗</span></button>
    </div>
  );
}

function DiscoveryCompanyOption({
  source,
  selected,
  onToggle,
}: {
  source: DiscoverySourceOption;
  selected: boolean;
  onToggle: (sourceId: string) => void;
}) {
  return (
    <label className={`discovery-company-option${selected ? " is-selected" : ""}`}>
      <input
        type="checkbox"
        checked={selected}
        onChange={() => onToggle(source.id)}
      />
      <span>
        <strong>{source.company}</strong>
        <small>优先搜索</small>
      </span>
    </label>
  );
}

function DiscoveryCompanyScope({
  sources,
  selectedCompanyIds,
  onToggle,
}: {
  sources: DiscoverySourceOption[];
  selectedCompanyIds: string[];
  onToggle: (sourceId: string) => void;
}) {
  const sourceById = new Map(sources.map((source) => [source.id, source]));
  const featuredSources = featuredDiscoveryCompanyIds
    .map((sourceId) => sourceById.get(sourceId))
    .filter((source): source is DiscoverySourceOption => Boolean(source));
  const featuredIds = new Set(featuredDiscoveryCompanyIds);
  const remainingSources = sources.filter((source) => !featuredIds.has(source.id));

  return (
    <div className="discovery-company-scope" role="group" aria-labelledby="discovery-company-label">
      <div className="discovery-company-heading">
        <span id="discovery-company-label">优先公司</span>
        <strong>{selectedCompanyIds.length > 0 ? `${selectedCompanyIds.length} 家已选` : "不限公司"}</strong>
      </div>
      <div className="discovery-company-grid">
        {featuredSources.map((source) => (
          <DiscoveryCompanyOption
            key={source.id}
            source={source}
            selected={selectedCompanyIds.includes(source.id)}
            onToggle={onToggle}
          />
        ))}
      </div>
      {remainingSources.length > 0 ? (
        <details className="discovery-company-more">
          <summary>更多公司 · {remainingSources.length}</summary>
          <div className="discovery-company-grid discovery-company-grid-more">
            {remainingSources.map((source) => (
              <DiscoveryCompanyOption
                key={source.id}
                source={source}
                selected={selectedCompanyIds.includes(source.id)}
                onToggle={onToggle}
              />
            ))}
          </div>
        </details>
      ) : null}
      <div className="discovery-company-legend" aria-label="公司筛选说明">
        <span>不选择时搜索全网；选择后优先查找这些公司的岗位。</span>
      </div>
    </div>
  );
}

type LeadQueueFilter = "actionable" | "handoff" | "verified" | "all";

function JobLeadQueue({
  leads,
  provider,
  sourceUrl,
  company,
  title,
  snippet,
  submitting,
  updatingLeadId,
  onProviderChange,
  onSourceUrlChange,
  onCompanyChange,
  onTitleChange,
  onSnippetChange,
  onSubmit,
  onVerify,
  onBrowser,
  onOpenJob,
  onPasteJD,
}: {
  leads: JobLeadItem[];
  provider: LeadSubmissionProvider;
  sourceUrl: string;
  company: string;
  title: string;
  snippet: string;
  submitting: boolean;
  updatingLeadId: string | null;
  onProviderChange: (value: LeadSubmissionProvider) => void;
  onSourceUrlChange: (value: string) => void;
  onCompanyChange: (value: string) => void;
  onTitleChange: (value: string) => void;
  onSnippetChange: (value: string) => void;
  onSubmit: () => void;
  onVerify: (leadId: string) => void;
  onBrowser: (leadId: string) => void;
  onOpenJob: (jobId: string) => void;
  onPasteJD: (leadId: string) => void;
}) {
  const [filter, setFilter] = useState<LeadQueueFilter>("actionable");
  const actionableStatuses = new Set<JobLeadStatus>(["NEW", "VERIFYING", "NEEDS_BROWSER", "NEEDS_USER", "FAILED"]);
  const handoffStatuses = new Set<JobLeadStatus>(["NEEDS_BROWSER", "NEEDS_USER", "REJECTED_NON_JOB"]);
  const verifiedStatuses = new Set<JobLeadStatus>(["VERIFIED", "DUPLICATE"]);
  const filteredLeads = leads.filter((lead) => {
    if (filter === "actionable") return actionableStatuses.has(lead.status);
    if (filter === "handoff") return handoffStatuses.has(lead.status);
    if (filter === "verified") return verifiedStatuses.has(lead.status);
    return true;
  });
  const filterOptions: Array<{ value: LeadQueueFilter; label: string; count: number }> = [
    { value: "actionable", label: "待处理", count: leads.filter((lead) => actionableStatuses.has(lead.status)).length },
    { value: "handoff", label: "需接管", count: leads.filter((lead) => handoffStatuses.has(lead.status)).length },
    { value: "verified", label: "已验证", count: leads.filter((lead) => verifiedStatuses.has(lead.status)).length },
    { value: "all", label: "全部", count: leads.length },
  ];

  return (
    <details className="job-lead-section">
      <summary className="job-lead-heading">
        <div>
          <div className="section-kicker">岗位链接</div>
          <h2>有具体岗位链接？</h2>
          <p>添加后先核对岗位正文，验证通过才会进入候选岗位。</p>
        </div>
        <span className="job-lead-counter">{leads.length} 条线索</span>
      </summary>

      <div className="job-lead-composer">
        <div className="job-lead-composer-topline">
          <strong>添加岗位链接</strong>
          <span>保存后等待正文验证</span>
        </div>
        <div className="job-lead-form">
          <label className="job-lead-provider-field">
            <span>线索来源</span>
            <select value={provider} onChange={(event) => onProviderChange(event.target.value as LeadSubmissionProvider)}>
              <option value="manual_url">我找到的 URL</option>
              <option value="external_agent">外部 Agent 搜索</option>
              <option value="third_party">第三方招聘平台</option>
            </select>
          </label>
          <label className="job-lead-url-field">
            <span>具体岗位 URL</span>
            <input
              type="url"
              value={sourceUrl}
              onChange={(event) => onSourceUrlChange(event.target.value)}
              placeholder="https://careers.example.com/jobs/123"
            />
          </label>
          <label>
            <span>公司提示（可选）</span>
            <input value={company} onChange={(event) => onCompanyChange(event.target.value)} placeholder="例如：示例科技" />
          </label>
          <label>
            <span>岗位提示（可选）</span>
            <input value={title} onChange={(event) => onTitleChange(event.target.value)} placeholder="例如：AI Agent 工程师" />
          </label>
          <label className="job-lead-snippet-field">
            <span>搜索摘要（可选，仅作线索）</span>
            <input value={snippet} onChange={(event) => onSnippetChange(event.target.value)} placeholder="保留发现上下文，不作为岗位事实" />
          </label>
          <button className="job-lead-submit" onClick={onSubmit} disabled={submitting} type="button">
            {submitting ? "正在保存…" : "保存线索"}<span aria-hidden="true">＋</span>
          </button>
        </div>
      </div>

      <div className="job-lead-toolbar">
        <div className="job-lead-filters" aria-label="岗位线索筛选">
          {filterOptions.map((option) => (
            <button
              className={filter === option.value ? "is-active" : ""}
              key={option.value}
              onClick={() => setFilter(option.value)}
              type="button"
            >
              {option.label}<span>{option.count.toString().padStart(2, "0")}</span>
            </button>
          ))}
        </div>
        <span className="job-lead-boundary">验证后进入候选岗位</span>
      </div>

      {filteredLeads.length > 0 ? (
        <div className="job-lead-list">
          {filteredLeads.map((lead) => {
            const canVerify = lead.status === "NEW" || lead.status === "FAILED";
            const needsHandoff = handoffStatuses.has(lead.status);
            const isVerified = verifiedStatuses.has(lead.status);
            return (
              <article className={`job-lead-row job-lead-${lead.status.toLowerCase().replaceAll("_", "-")}`} key={lead.id}>
                <div className="job-lead-status-cell">
                  <span className="job-lead-provider">{leadProviderLabel[lead.provider]}</span>
                  <strong>{jobLeadStatusLabel[lead.status]}</strong>
                  <time>{formatDate(lead.verified_at ?? lead.discovered_at)}</time>
                </div>
                <div className="job-lead-main">
                  <div className="job-lead-title-line">
                    <div>
                      <span>{lead.company_hint ?? "公司待验证"}</span>
                      <h3>{lead.title_hint ?? "岗位名称待验证"}</h3>
                    </div>
                    <code>{lead.id.slice(-8).toUpperCase()}</code>
                  </div>
                  <a href={lead.source_url} target="_blank" rel="noreferrer">{lead.normalized_url}</a>
                  {lead.search_snippet ? <p className="job-lead-snippet">搜索摘要：{lead.search_snippet}</p> : null}
                  {lead.failure_reason ? <p className="job-lead-failure">{lead.failure_code ? `${lead.failure_code} / ` : ""}{lead.failure_reason}</p> : null}
                  {needsHandoff ? <p className="job-lead-next">下一步：动态页可先尝试只读浏览器验证；遇到登录或安全验证时停下，再由你粘贴完整 JD。</p> : null}
                </div>
                <div className="job-lead-actions">
                  {canVerify ? (
                    <button className="job-lead-primary" onClick={() => onVerify(lead.id)} disabled={updatingLeadId === lead.id} type="button">
                      {updatingLeadId === lead.id ? "验证中…" : lead.status === "FAILED" ? "重新验证" : "验证正文"}
                    </button>
                  ) : null}
                  {lead.status === "VERIFYING" ? <button className="job-lead-primary" disabled type="button">验证中…</button> : null}
                  {lead.status === "NEEDS_BROWSER" ? (
                    <button className="job-lead-primary" onClick={() => onBrowser(lead.id)} disabled={updatingLeadId === lead.id} type="button">
                      {updatingLeadId === lead.id ? "浏览器读取中…" : "浏览器验证"}
                    </button>
                  ) : null}
                  {isVerified && lead.job_posting_id ? (
                    <button className="job-lead-primary" onClick={() => onOpenJob(lead.job_posting_id!)} type="button">查看岗位</button>
                  ) : null}
                  <a href={lead.source_url} target="_blank" rel="noreferrer">打开原页 ↗</a>
                  {needsHandoff ? <button className="job-lead-secondary" onClick={() => onPasteJD(lead.id)} type="button">粘贴 JD 接管</button> : null}
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="job-lead-empty">
          <strong>{leads.length === 0 ? "还没有岗位线索" : "这个视图没有记录"}</strong>
          <span>{leads.length === 0 ? "提交具体岗位 URL，或运行一次全网搜索。" : "切换筛选项查看其他验证状态。"}</span>
        </div>
      )}
    </details>
  );
}

function DiscoveryWorkspace({
  candidates,
  leads,
  runs,
  state,
  message,
  query,
  sources,
  selectedCompanyIds,
  sourceUrl,
  company,
  updatingCandidateId,
  updatingAvailabilityJobId,
  leadProvider,
  leadUrl,
  leadCompany,
  leadTitle,
  leadSnippet,
  submittingLead,
  updatingLeadId,
  onQueryChange,
  onToggleCompany,
  onSourceUrlChange,
  onCompanyChange,
  onLeadProviderChange,
  onLeadUrlChange,
  onLeadCompanyChange,
  onLeadTitleChange,
  onLeadSnippetChange,
  onRun,
  onManualRun,
  onSubmitLead,
  onVerifyLead,
  onBrowserLead,
  onRefresh,
  onOpen,
  onPasteJD,
  onUpdate,
  onCheckAvailability,
}: {
  candidates: CandidateItem[];
  leads: JobLeadItem[];
  runs: DiscoveryRunItem[];
  state: DiscoveryState;
  message: string;
  query: string;
  sources: DiscoverySourceOption[];
  selectedCompanyIds: string[];
  sourceUrl: string;
  company: string;
  updatingCandidateId: string | null;
  updatingAvailabilityJobId: string | null;
  leadProvider: LeadSubmissionProvider;
  leadUrl: string;
  leadCompany: string;
  leadTitle: string;
  leadSnippet: string;
  submittingLead: boolean;
  updatingLeadId: string | null;
  onQueryChange: (value: string) => void;
  onToggleCompany: (sourceId: string) => void;
  onSourceUrlChange: (value: string) => void;
  onCompanyChange: (value: string) => void;
  onLeadProviderChange: (value: LeadSubmissionProvider) => void;
  onLeadUrlChange: (value: string) => void;
  onLeadCompanyChange: (value: string) => void;
  onLeadTitleChange: (value: string) => void;
  onLeadSnippetChange: (value: string) => void;
  onRun: () => void;
  onManualRun: () => void;
  onSubmitLead: () => void;
  onVerifyLead: (leadId: string) => void;
  onBrowserLead: (leadId: string) => void;
  onRefresh: () => void;
  onOpen: (jobId: string) => void;
  onPasteJD: (leadId?: string) => void;
  onUpdate: (candidateId: string, status: CandidateStatus) => void;
  onCheckAvailability: (jobId: string) => void;
}) {
  const [showAllExpanded, setShowAllExpanded] = useState(false);
  const [expandedResultsOpen, setExpandedResultsOpen] = useState(false);
  const pool = candidates.filter((item) => item.status === "DISCOVERED" || item.status === "SAVED");
  const ignoredPool = candidates.filter((item) => item.status === "IGNORED");
  const latestRun = runs[0];
  const latestMatches = latestRun?.result_matches ?? [];
  const candidateByJobId = new Map(pool.map((candidate) => [candidate.job_posting_id, candidate]));
  const latestJobIds = new Set(latestMatches.map((match) => match.job_posting_id));
  const strictMatches = latestMatches.filter((match) => match.match_tier === "strict");
  const expandedMatches = latestMatches.filter((match) => match.match_tier === "expanded");
  const strictPool = latestRun
    ? strictMatches.flatMap((match) => {
        const candidate = candidateByJobId.get(match.job_posting_id);
        return candidate ? [{ candidate, match }] : [];
      })
    : pool.map((candidate) => ({ candidate, match: undefined }));
  const expandedPool = expandedMatches.flatMap((match) => {
    const candidate = candidateByJobId.get(match.job_posting_id);
    return candidate ? [{ candidate, match }] : [];
  });
  const historicalPool = latestRun
    ? pool.filter((candidate) => !latestJobIds.has(candidate.job_posting_id))
    : [];
  const currentPoolSize = strictPool.length + expandedPool.length;
  const shouldAutoExpand = Boolean(
    latestRun
      && latestRun.status !== "RUNNING"
      && strictMatches.length === 0
      && expandedMatches.length > 0,
  );
  useEffect(() => {
    setExpandedResultsOpen(shouldAutoExpand);
    setShowAllExpanded(false);
  }, [latestRun?.id, latestRun?.status, shouldAutoExpand]);
  const verifiedResultCount = latestRun?.result_matches.length ?? 0;
  const needsHumanJD = Boolean(
    latestRun
      && latestRun.status !== "RUNNING"
      && verifiedResultCount === 0
      && state !== "loading",
  );
  return (
    <section className="discovery-shell">
      <div className="discovery-control-panel">
        <div className="discovery-control-heading">
          <div>
            <h2>搜索岗位</h2>
            <p>描述你想找的方向，系统会搜索公开网页并核验原始岗位内容。</p>
          </div>
          <button className="discovery-add-button" onClick={() => onPasteJD()} type="button">
            <span aria-hidden="true">＋</span> 添加岗位
          </button>
        </div>
        <div className="discovery-form">
          <label>
            <span className="sr-only">你想找什么</span>
            <textarea
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="例如：北京 / 上海的 AI Agent、LLM、算法校招岗位"
            />
          </label>
          <button
            className="discovery-sync-button"
            onClick={onRun}
            disabled={state === "loading"}
            type="button"
          >
            <span>{state === "loading" ? "搜索中…" : "搜索并分析"}</span>
            <span aria-hidden="true">↗</span>
          </button>
        </div>
        <details className="discovery-filters">
          <summary>
            <span>优先公司（可选）</span>
            <strong>{selectedCompanyIds.length > 0 ? `${selectedCompanyIds.length} 家公司` : "不限公司"}</strong>
          </summary>
          <div className="discovery-filter-content">
            <DiscoveryCompanyScope
              sources={sources}
              selectedCompanyIds={selectedCompanyIds}
              onToggle={onToggleCompany}
            />
            <details className="discovery-advanced">
              <summary>指定其他招聘页面</summary>
              <div className="discovery-advanced-form">
                <label>
                  <span>招聘页面 URL</span>
                  <input
                    value={sourceUrl}
                    onChange={(event) => onSourceUrlChange(event.target.value)}
                    placeholder="https://boards.greenhouse.io/{board_token}"
                  />
                </label>
                <label>
                  <span>公司名称（可选）</span>
                  <input
                    value={company}
                    onChange={(event) => onCompanyChange(event.target.value)}
                    placeholder="例如：目标公司"
                  />
                </label>
                <button className="discovery-advanced-button" onClick={onManualRun} disabled={state === "loading"} type="button">
                  同步这个来源
                </button>
              </div>
            </details>
          </div>
        </details>
      </div>

      {message ? <div className="discovery-message">{message}</div> : null}

      {needsHumanJD ? (
        <div className="discovery-human-gate">
          <div>
            <span>需要人工补充</span>
            <h3>暂时没有自动核验成功的岗位。</h3>
            <p>你可以在线索区继续核验，也可以直接添加岗位内容进入匹配。</p>
          </div>
          <button onClick={() => onPasteJD()} type="button">粘贴 JD 继续分析 <span aria-hidden="true">↗</span></button>
        </div>
      ) : null}

      <div className="discovery-pool-heading">
        <div>
          <h2>候选岗位</h2>
          <p>优先展示符合筛选条件的岗位，放宽条件的结果会单独收起。</p>
        </div>
        <button className="board-refresh" onClick={onRefresh} disabled={state === "loading"} type="button">
          {state === "loading" ? "读取中…" : "刷新"}
        </button>
      </div>

      {state === "error" ? (
        <div className="discovery-empty discovery-error">
          <h3>这次来源同步没有完成。</h3>
          <p>{message || "请确认来源入口可公开访问，或检查后端服务是否正在运行。"}</p>
          <button className="retry-button" onClick={onRefresh} type="button">重试 ↗</button>
        </div>
      ) : null}
      {state === "loading" && currentPoolSize === 0 ? (
        <div className="discovery-empty">
          <div className="board-loader" />
          <h3>正在整理公开岗位。</h3>
          <p>读取来源、标准化字段、计算去重指纹，然后才会进入候选池。</p>
        </div>
      ) : null}
      {state !== "error" && state !== "loading" && currentPoolSize === 0 && (!latestRun || verifiedResultCount === 0) ? (
        <div className="discovery-empty">
          <div className="empty-glyph">＋</div>
          <h3>{needsHumanJD ? "这次没有可验证的候选岗位。" : "候选池还是空的。"}</h3>
          <p>{needsHumanJD ? "系统已经停止自动生成结果。你可以粘贴具体 JD 继续，也可以调整目标后重新搜索。" : "描述目标后开始即时搜索。岗位进入这里后，你可以先保存、忽略，或者查看自动分析结果。"}</p>
          <button className="discovery-paste-button" onClick={() => onPasteJD()} type="button">粘贴 JD 继续 <span aria-hidden="true">↗</span></button>
        </div>
      ) : null}
      {latestRun && latestRun.status !== "RUNNING" && verifiedResultCount > 0 ? (
        <div className="discovery-result-group-heading">
          <div>
            <span>优先结果</span>
            <h3>严格匹配</h3>
            <p>满足查询中的地点、招聘类型和岗位方向；选择优先公司后也会纳入范围判断。</p>
          </div>
          <strong>{strictMatches.length.toString().padStart(2, "0")}</strong>
        </div>
      ) : null}

      {latestRun && latestRun.status !== "RUNNING" && verifiedResultCount > 0 && strictMatches.length === 0 ? (
        <div className="discovery-no-strict-match">
          <strong>本次严格匹配为 0</strong>
          <span>下方岗位已经过原始页面核验，但不代表它们满足你的原始条件。</span>
        </div>
      ) : null}

      {strictPool.length > 0 ? (
        <div className="discovery-pool discovery-pool-strict">
          {strictPool.map(({ candidate, match }) => (
            <DiscoveryCard
              key={candidate.id}
              candidate={candidate}
              match={match}
              updating={updatingCandidateId === candidate.id}
              checkingAvailability={updatingAvailabilityJobId === candidate.job.id}
              onOpen={() => onOpen(candidate.job.id)}
              onUpdate={(status) => onUpdate(candidate.id, status)}
              onCheckAvailability={() => onCheckAvailability(candidate.job.id)}
            />
          ))}
        </div>
      ) : null}

      {latestRun && latestRun.status !== "RUNNING" && verifiedResultCount > 0 ? (
        <details
          className="discovery-expanded-results"
          open={expandedResultsOpen}
          onToggle={(event) => setExpandedResultsOpen(event.currentTarget.open)}
        >
          <summary>
            <span><strong>拓展候选 / {expandedMatches.length.toString().padStart(2, "0")}</strong>真实岗位，但至少一项条件已放宽，默认不自动分析</span>
            <span aria-hidden="true">＋</span>
          </summary>
          {expandedPool.length > 0 ? (
            <div className="discovery-pool">
              {(showAllExpanded ? expandedPool : expandedPool.slice(0, 6)).map(({ candidate, match }) => (
                <DiscoveryCard
                  key={candidate.id}
                  candidate={candidate}
                  match={match}
                  updating={updatingCandidateId === candidate.id}
                  checkingAvailability={updatingAvailabilityJobId === candidate.job.id}
                  onOpen={() => onOpen(candidate.job.id)}
                  onUpdate={(status) => onUpdate(candidate.id, status)}
                  onCheckAvailability={() => onCheckAvailability(candidate.job.id)}
                />
              ))}
            </div>
          ) : (
            <p className="discovery-expanded-empty">本次没有需要放宽条件的候选。</p>
          )}
          {expandedPool.length > 6 ? (
            <button className="discovery-show-more" onClick={() => setShowAllExpanded((current) => !current)} type="button">
              {showAllExpanded ? "收起部分结果" : `查看其余 ${expandedPool.length - 6} 条岗位`}
            </button>
          ) : null}
        </details>
      ) : null}

      {historicalPool.length > 0 ? (
        <details className="discovery-ignored-archive">
          <summary>历史候选 / {historicalPool.length.toString().padStart(2, "0")} · 不属于本次搜索结果</summary>
          <div className="discovery-pool">
            {historicalPool.map((candidate) => (
              <DiscoveryCard
                key={candidate.id}
                candidate={candidate}
                updating={updatingCandidateId === candidate.id}
                checkingAvailability={updatingAvailabilityJobId === candidate.job.id}
                onOpen={() => onOpen(candidate.job.id)}
                onUpdate={(status) => onUpdate(candidate.id, status)}
                onCheckAvailability={() => onCheckAvailability(candidate.job.id)}
              />
            ))}
          </div>
        </details>
      ) : null}

      {ignoredPool.length > 0 ? (
        <details className="discovery-ignored-archive">
          <summary>已忽略记录 / {ignoredPool.length.toString().padStart(2, "0")} · 默认不进入候选分析</summary>
          <div className="discovery-pool">
            {ignoredPool.map((candidate) => (
              <DiscoveryCard
                key={candidate.id}
                candidate={candidate}
                updating={updatingCandidateId === candidate.id}
                checkingAvailability={updatingAvailabilityJobId === candidate.job.id}
                onOpen={() => onOpen(candidate.job.id)}
                onUpdate={(status) => onUpdate(candidate.id, status)}
                onCheckAvailability={() => onCheckAvailability(candidate.job.id)}
              />
            ))}
          </div>
        </details>
      ) : null}

      <JobLeadQueue
        leads={leads}
        provider={leadProvider}
        sourceUrl={leadUrl}
        company={leadCompany}
        title={leadTitle}
        snippet={leadSnippet}
        submitting={submittingLead}
        updatingLeadId={updatingLeadId}
        onProviderChange={onLeadProviderChange}
        onSourceUrlChange={onLeadUrlChange}
        onCompanyChange={onLeadCompanyChange}
        onTitleChange={onLeadTitleChange}
        onSnippetChange={onLeadSnippetChange}
        onSubmit={onSubmitLead}
        onVerify={onVerifyLead}
        onBrowser={onBrowserLead}
        onOpenJob={onOpen}
        onPasteJD={onPasteJD}
      />

      <DiscoveryRunHistory runs={runs} />
    </section>
  );
}

function DiscoveryCard({
  candidate,
  match,
  updating,
  checkingAvailability,
  onOpen,
  onUpdate,
  onCheckAvailability,
}: {
  candidate: CandidateItem;
  match?: DiscoveryResultMatch;
  updating: boolean;
  checkingAvailability: boolean;
  onOpen: () => void;
  onUpdate: (status: CandidateStatus) => void;
  onCheckAvailability: () => void;
}) {
  const locations = candidate.job.locations ?? [];
  const canSave = candidate.available_transitions.includes("SAVED");
  const canIgnore = candidate.available_transitions.includes("IGNORED");
  const sourceLabel = candidate.job.source_id?.startsWith("bytedance:")
    ? "字节跳动官方招聘"
    : candidate.job.source_id?.startsWith("tencent:")
      ? "腾讯官方招聘"
      : candidate.job.source_id?.startsWith("greenhouse:")
        ? "Greenhouse 官方招聘"
        : "人工录入岗位";
  const candidateDecision = candidate.analysis?.recommendation === "recommended_application"
    ? "推荐申请"
    : candidate.analysis?.recommendation === "consider"
      ? "可以考虑"
      : candidate.analysis?.recommendation === "not_recommended"
        ? "不建议申请"
        : "信息不足";
  const analysisLabel = match?.match_tier === "expanded"
    ? candidate.analysis
      ? `已有分析 / ${candidateDecision}`
      : "待手动分析"
    : candidate.analysis
      ? `分析完成 / ${candidateDecision}`
      : "待进入分析";
  const openLabel = match?.match_tier === "expanded"
    ? candidate.analysis ? "查看已有分析 ↗" : "手动分析 ↗"
    : candidate.analysis ? "查看分析 ↗" : "进入分析 ↗";
  return (
    <article className={`discovery-card discovery-card-${candidate.status.toLowerCase()} ${match ? `discovery-card-${match.match_tier}` : ""}`}>
      <div className="discovery-card-topline">
        <span>{sourceLabel}</span>
        <div className="discovery-card-signals">
          {candidate.job.verification_status ? (
            <span className={`discovery-verification discovery-verification-${candidate.job.verification_status.toLowerCase()}`}>
              {verificationStatusLabel[candidate.job.verification_status]}
            </span>
          ) : null}
          {match ? <span className={`discovery-match-tier discovery-match-tier-${match.match_tier}`}>{match.match_tier === "strict" ? "严格匹配" : "拓展候选"}</span> : null}
          <span className="discovery-status">{candidateStatusLabel[candidate.status]}</span>
        </div>
      </div>
      <div className="discovery-card-body">
        <div>
          <p className="discovery-company">{candidate.job.company ?? "未识别公司"}</p>
          <h3>{candidate.job.title ?? "未识别岗位"}</h3>
          <p className="discovery-meta">
            {locations.length > 0 ? locations.join(" · ") : "地点待确认"}
            <span> / </span>
            {candidate.job.job_type ? jobTypeShortLabel[candidate.job.job_type] ?? candidate.job.job_type : "类型待确认"}
            <span> / </span>
            {analysisLabel}
          </p>
          {candidate.job.availability_status ? (
            <p className={`discovery-availability discovery-availability-${candidate.job.availability_status.toLowerCase()}`}>
              {availabilityStatusLabel[candidate.job.availability_status]}
              {candidate.job.availability_failure_count
                ? ` · 连续读取失败 ${candidate.job.availability_failure_count} 次`
                : candidate.job.last_availability_checked_at
                  ? ` · ${formatDate(candidate.job.last_availability_checked_at)}`
                  : ""}
            </p>
          ) : null}
          {match?.mismatch_labels.length ? (
            <div className="discovery-mismatch-list" aria-label="条件放宽原因">
              {match.mismatch_labels.map((label) => <span key={label}>{label}</span>)}
            </div>
          ) : null}
        </div>
        <div className="discovery-date">
          <span>{candidate.job.last_verified_at ? "最近验证" : "最近发现"}</span>
          <strong>{formatDate(candidate.job.last_verified_at ?? candidate.job.last_seen_at ?? candidate.updated_at)}</strong>
        </div>
      </div>
      <div className="discovery-card-footer">
        <button className="discovery-open" onClick={onOpen} type="button">{openLabel}</button>
        <div className="discovery-secondary-actions">
          <button onClick={onCheckAvailability} disabled={checkingAvailability} type="button">
            {checkingAvailability ? "检查中…" : "检查开放状态"}
          </button>
          {canSave ? (
            <button onClick={() => onUpdate("SAVED")} disabled={updating} type="button">保存</button>
          ) : null}
          {canIgnore ? (
            <button onClick={() => onUpdate("IGNORED")} disabled={updating} type="button">忽略</button>
          ) : null}
        </div>
      </div>
    </article>
  );
}

function DiscoveryRunHistory({ runs }: { runs: DiscoveryRunItem[] }) {
  return (
    <details className="discovery-history">
      <summary className="discovery-history-heading">
        <div>
          <div className="section-kicker">搜索记录</div>
          <h2>最近的搜索记录</h2>
        </div>
        <span>{runs.length} 次搜索</span>
      </summary>
      {runs.length === 0 ? (
        <p className="discovery-history-empty">还没有搜索记录。第一次即时搜索后，这里会记录搜索目标、来源数量和自动分析进度。</p>
      ) : (
        <div className="discovery-history-list">
          {runs.slice(0, 5).map((run) => (
            <div className="discovery-history-row" key={run.id}>
              <span className="discovery-history-source">{run.search_query || run.source}</span>
              <strong>{discoveryRunStatusLabel[run.status]}</strong>
              <span>严格 {countDiscoveryMatches(run, "strict")} / 拓展 {countDiscoveryMatches(run, "expanded")} / 分析 {run.analysis_completed_count}/{run.analysis_target_count}</span>
              <time>{formatDate(run.created_at)}</time>
              {run.failure_summary ? (
                <p className="discovery-history-warning" title={run.failure_summary}>
                  {run.failure_summary.split("\n").slice(0, 2).join("；")}
                </p>
              ) : null}
              {run.agent_trace?.length ? (
                <details className="discovery-agent-trace">
                  <summary>查看搜索过程 / {run.agent_trace.length.toString().padStart(2, "0")} 步</summary>
                  {run.search_plan ? (
                    <div className="discovery-plan-contract">
                      <div className="discovery-plan-heading">
                        <span>{run.search_plan.version.toUpperCase()}</span>
                        <strong>
                          来源 {run.search_plan.allowed_source_ids.length} · 岗位上限 {run.search_plan.budget.max_results} · 自动分析 {run.search_plan.budget.max_analysis}
                        </strong>
                      </div>
                      <div className="discovery-plan-routes">
                        {run.search_plan.routes.slice(0, 6).map((route) => (
                          <p key={`${run.id}-${route.source_id}-plan`}>
                            <b>{route.company ?? route.source_id}</b>
                            <span>{route.tool_sequence.join(" → ")}</span>
                          </p>
                        ))}
                        {run.search_plan.routes.length > 6 ? (
                          <p><b>其余来源</b><span>还有 {run.search_plan.routes.length - 6} 条受控路线</span></p>
                        ) : null}
                      </div>
                      <div className="discovery-plan-stops">
                        {run.search_plan.stop_conditions.map((condition) => (
                          <span key={`${run.id}-${condition}`}>{discoveryStopConditionLabel[condition] ?? condition}</span>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  <div className="discovery-agent-trace-list">
                    {run.agent_trace.map((step, index) => (
                      <article className={`discovery-agent-step trace-${step.outcome}`} key={`${run.id}-${index}-${step.tool}`}>
                        <div>
                          <span>{(index + 1).toString().padStart(2, "0")} · {step.phase.toUpperCase()}</span>
                          <strong>{discoveryTraceOutcomeLabel[step.outcome] ?? step.outcome}</strong>
                          {step.duration_ms !== null && step.duration_ms !== undefined ? <small>{step.duration_ms} MS</small> : null}
                          {typeof step.details?.output_count === "number" ? <small>OUTPUT {step.details.output_count}</small> : null}
                          {step.error_code ? <code>{step.error_code}</code> : null}
                        </div>
                        <h3>{step.company ? `${step.company} / ` : ""}{step.tool}</h3>
                        <p>{step.observation}</p>
                        <p className="discovery-agent-decision">决策：{step.decision}</p>
                      </article>
                    ))}
                  </div>
                </details>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </details>
  );
}

function AnalysisResult({
  analysis,
  onPrepareApplication,
  preparing,
}: {
  analysis: AnalysisResponse;
  onPrepareApplication: () => void;
  preparing: boolean;
}) {
  const jd = analysis.structured_jd;
  const requiredMatches = analysis.matches.filter((match) => match.requirement.mandatory);
  const decision = analysis.decision ?? {
    recommendation: analysis.score.recommendation === "recommended"
      ? "recommended_application" as const
      : analysis.score.recommendation === "not_recommended"
        ? "not_recommended" as const
        : analysis.score.recommendation === "needs_confirmation"
          ? "consider" as const
          : "insufficient_information" as const,
    summary: "这条历史分析还没有生成完整申请建议，请结合资格检查和经历证据确认。",
    reasons: [],
    required_supported: requiredMatches.filter((match) => match.support_level === "supported").length,
    required_total: requiredMatches.length,
    needs_confirmation: analysis.matches.filter((match) => match.support_level === "needs_confirmation").length,
  };

  return (
    <div className="analysis-result">
      <div className="signal-summary">
        <div className="score-block">
          <span className="summary-label">APPLICATION DECISION</span>
          <strong>{decisionLabel[decision.recommendation]}</strong>
          <span className="score-denominator">{decision.required_supported}/{decision.required_total} 条必须条件有证据</span>
        </div>
        <div className="recommendation-block">
          <span className="summary-label">WHY</span>
          <strong>{decision.summary}</strong>
          <span>{analysis.job.company ?? jd.company ?? "未识别公司"} · {analysis.job.title ?? jd.title ?? "未识别岗位"}</span>
          {decision.reasons.map((reason) => <small key={reason}>{reason}</small>)}
        </div>
        <div className="decision-action">
          <span className="summary-label">HUMAN GATE</span>
          <button onClick={onPrepareApplication} disabled={preparing} type="button">
            {preparing ? "正在创建…" : "准备申请 ↗"}
          </button>
          <small>确认后才会进入申请看板</small>
        </div>
        <div className="signal-stamp">{decision.recommendation === "recommended_application" ? "APPLY\nREADY" : decision.recommendation === "not_recommended" ? "HARD\nSTOP" : "REVIEW\nFIRST"}</div>
      </div>

      <section className="result-section jd-section">
        <div className="result-section-heading"><span>01</span><h2>结构化岗位</h2><span className="section-rule" /></div>
        <div className="jd-facts">
          <Fact label="岗位类型" value={jd.job_type ? jobTypeLabel[jd.job_type] ?? jd.job_type : "未识别"} />
          <Fact label="工作地点" value={compactList(jd.locations)} />
          <Fact label="学历要求" value={compactList(jd.education_requirements)} />
          <Fact label="专业要求" value={compactList(jd.major_requirements)} />
          <Fact label="必备技能" value={compactList(jd.required_skills)} accent />
          <Fact label="加分技能" value={compactList(jd.preferred_skills)} />
          <Fact label="截止时间" value={jd.deadline ?? "未识别"} />
          <Fact label="实习条件" value={internshipCopy(jd)} />
          <Fact label="岗位职责" value={compactList(jd.responsibilities)} />
        </div>
      </section>

      <section className="result-section eligibility-section">
        <div className="result-section-heading"><span>02</span><h2>资格检查</h2><span className="section-rule" /></div>
        <div className="eligibility-list">
          {analysis.eligibility.checks.map((check) => (
            <div className="eligibility-row" key={`${check.rule_name}-${check.field}`}>
              <span className={`check-icon check-${check.result}`}>{check.result === "pass" ? "✓" : check.result === "fail" ? "×" : "?"}</span>
              <div><strong>{check.rule_name.replaceAll("_", " ")}</strong><p>{check.reason}</p></div>
              <span className={`check-word check-word-${check.result}`}>{check.result.toUpperCase()}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="result-section evidence-section">
        <div className="result-section-heading"><span>03</span><h2>要求 × 经历证据</h2><span className="section-rule" /></div>
        {analysis.matches.length === 0 ? (
          <div className="subtle-empty">这条 JD 暂未识别出可匹配的结构化要求。可以补充更完整的岗位原文后重试。</div>
        ) : (
          <div className="match-list">
            {analysis.matches.map((match) => <MatchRow key={`${match.requirement.category}-${match.requirement.name}-${match.requirement.description}`} match={match} />)}
          </div>
        )}
      </section>

      <section className="result-section risk-section">
        <div className="result-section-heading"><span>04</span><h2>风险与待确认</h2><span className="section-rule" /></div>
        {analysis.risks.length === 0 && analysis.missing_information.length === 0 ? (
          <div className="clear-signal"><span>✓</span> 暂未发现需要拦截的风险。</div>
        ) : (
          <div className="risk-list">
            {analysis.risks.map((risk) => (
              <div className={`risk-row risk-${risk.severity}`} key={risk.code}>
                <span className="risk-severity">{risk.severity === "high" ? "HIGH" : risk.severity === "medium" ? "CHECK" : "NOTE"}</span>
                <div><strong>{risk.title}</strong><p>{risk.detail}</p></div>
              </div>
            ))}
            {analysis.missing_information.map((item) => <div className="missing-row" key={item}><span>＋</span><p>待补充：{item}</p></div>)}
          </div>
        )}
      </section>
    </div>
  );
}

function ApplicationBoard({
  applications,
  state,
  message,
  updatingApplicationId,
  onRefresh,
  onTransition,
}: {
  applications: ApplicationItem[];
  state: BoardState;
  message: string;
  updatingApplicationId: string | null;
  onRefresh: () => void;
  onTransition: (applicationId: string, status: ApplicationStatus) => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = applications.find((item) => item.id === selectedId) ?? applications[0] ?? null;

  return (
    <section className="board-shell">
      <header className="board-header">
        <div>
          <div className="section-kicker"><span>01</span> 申请状态</div>
          <h2>把每一次跟进，<em>变成下一步。</em></h2>
          <p>只有用户确认过的岗位才会出现在这里。状态由用户手动推进，事件时间线负责留下事实。</p>
        </div>
        <button className="board-refresh" onClick={onRefresh} disabled={state === "loading"} type="button">
          {state === "loading" ? "同步中…" : "同步申请 ↻"}
        </button>
      </header>

      {message ? <div className="board-message">{message}</div> : null}
      {state === "error" ? (
        <div className="board-empty board-error">
          <span className="empty-index">BOARD / ERROR</span>
          <h3>申请记录暂时取不到。</h3>
          <p>{message || "请确认后端服务正在运行。"}</p>
          <button className="retry-button" onClick={onRefresh} type="button">重试 ↗</button>
        </div>
      ) : null}
      {state === "loading" && applications.length === 0 ? (
        <div className="board-empty">
          <span className="empty-index">BOARD / SYNC</span>
          <div className="board-loader" />
          <h3>正在取回你的申请。</h3>
        </div>
      ) : null}
      {state !== "error" && state !== "loading" && applications.length === 0 ? (
        <div className="board-empty">
          <span className="empty-index">BOARD / 00</span>
          <div className="empty-glyph">＋</div>
          <h3>这里还没有申请。</h3>
          <p>回到岗位分析，点击“准备申请”，第一条申请会在用户确认后出现在这里。</p>
        </div>
      ) : null}
      {applications.length > 0 ? (
        <>
          <div className="application-board" aria-label="申请状态看板">
            {boardColumns.map((column) => {
              const items = applications.filter((item) => item.status === column.status);
              return (
                <section className="application-column" key={column.status}>
                  <header className="column-header">
                    <span className={`column-marker marker-${column.tone}`} />
                    <strong>{column.label}</strong>
                    <span>{items.length.toString().padStart(2, "0")}</span>
                  </header>
                  <div className="column-cards">
                    {items.map((item) => (
                      <ApplicationCard
                        key={item.id}
                        application={item}
                        selected={selected?.id === item.id}
                        updating={updatingApplicationId === item.id}
                        onSelect={() => setSelectedId(item.id)}
                        onTransition={(status) => onTransition(item.id, status)}
                      />
                    ))}
                    {items.length === 0 ? <div className="column-empty">暂无申请</div> : null}
                  </div>
                </section>
              );
            })}
          </div>
          <TimelinePanel application={selected} />
          <SuggestionPanel application={selected} />
        </>
      ) : null}
    </section>
  );
}

function ApplicationCard({
  application,
  selected,
  updating,
  onSelect,
  onTransition,
}: {
  application: ApplicationItem;
  selected: boolean;
  updating: boolean;
  onSelect: () => void;
  onTransition: (status: ApplicationStatus) => void;
}) {
  return (
    <article className={`application-card ${selected ? "application-card-selected" : ""}`} onClick={onSelect}>
      <div className="application-card-topline">
        <span>{application.job.company ?? "未命名公司"}</span>
        <span>{formatDate(application.updated_at)}</span>
      </div>
      <h3>{application.job.title ?? "未命名岗位"}</h3>
      <p className="application-location">{application.job.source_url ? "官方来源已保存" : "手动导入岗位"}</p>
      {application.next_action ? (
        <div className="next-action"><span>下一步</span><strong>{application.next_action}</strong></div>
      ) : null}
      <div className="application-card-footer">
        <button className="timeline-trigger" onClick={(event) => { event.stopPropagation(); onSelect(); }} type="button">
          时间线 · {application.events.length}
        </button>
        {application.available_transitions.length > 0 ? (
          <select
            aria-label={`${application.job.title ?? "申请"}推进状态`}
            disabled={updating}
            value=""
            onChange={(event) => {
              const nextStatus = event.target.value as ApplicationStatus;
              if (nextStatus) onTransition(nextStatus);
            }}
          >
            <option value="">{updating ? "更新中…" : "推进 ↗"}</option>
            {application.available_transitions.map((status) => (
              <option key={status} value={status}>{applicationStatusLabel[status]}</option>
            ))}
          </select>
        ) : <span className="application-closed">已结束</span>}
      </div>
    </article>
  );
}

function TimelinePanel({ application }: { application: ApplicationItem | null }) {
  return (
    <section className="timeline-panel">
      <div className="timeline-heading">
        <div>
          <div className="section-kicker"><span>02</span> 事件时间线</div>
          <h2>{application ? `${application.job.company ?? "未命名公司"} / ${application.job.title ?? "未命名岗位"}` : "选择一条申请"}</h2>
        </div>
        {application ? <span className="timeline-status">{applicationStatusLabel[application.status]}</span> : null}
      </div>
      {application ? (
        <div className="timeline-list">
          {application.events.map((event, index) => (
            <div className="timeline-event" key={event.id}>
              <span className={`timeline-node ${index === application.events.length - 1 ? "timeline-node-current" : ""}`} />
              <div>
                <div className="timeline-event-topline">
                  <strong>{applicationEventLabel[event.event_type] ?? event.event_type}</strong>
                  <time>{formatDate(event.created_at)}</time>
                </div>
                <p>{eventDescription(event)}</p>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="timeline-empty">点击申请卡片查看它是如何从用户确认走到当前状态的。</p>
      )}
    </section>
  );
}

function SuggestionPanel({ application }: { application: ApplicationItem | null }) {
  const applicationId = application?.id;
  const [suggestions, setSuggestions] = useState<ResumeSuggestion[]>([]);
  const [suggestionState, setSuggestionState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [message, setMessage] = useState("");
  const [targetType, setTargetType] = useState("project_bullet");
  const [targetLabel, setTargetLabel] = useState("项目经历");
  const [originalText, setOriginalText] = useState("");
  const [editedText, setEditedText] = useState<Record<string, string>>({});
  const [creating, setCreating] = useState(false);
  const [workingId, setWorkingId] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function loadSuggestions() {
      if (!applicationId) {
        setSuggestions([]);
        setSuggestionState("idle");
        setMessage("");
        return;
      }
      setSuggestionState("loading");
      setMessage("");
      try {
        const response = await fetch(`${apiUrl}/api/applications/${applicationId}/suggestions`, {
          headers: { "X-User-ID": userId },
          cache: "no-store",
        });
        if (!response.ok) throw new Error(await readError(response));
        const next = (await response.json()) as ResumeSuggestion[];
        if (!active) return;
        setSuggestions(next);
        setEditedText(Object.fromEntries(next.map((item) => [item.id, item.suggestion_text])));
        setSuggestionState("ready");
      } catch (error) {
        if (!active) return;
        setSuggestionState("error");
        setMessage(error instanceof Error ? error.message : "材料建议加载失败。");
      }
    }
    void loadSuggestions();
    return () => {
      active = false;
    };
  }, [applicationId]);

  async function createSuggestion() {
    if (!applicationId || !originalText.trim()) {
      setMessage("请先提供需要修改的原文。");
      return;
    }
    setCreating(true);
    setMessage("");
    try {
      const response = await fetch(`${apiUrl}/api/applications/${applicationId}/suggestions`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({
          original_text: originalText,
          target_type: targetType,
          target_label: targetLabel || null,
        }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const created = (await response.json()) as ResumeSuggestion;
      setSuggestions((current) => [created, ...current]);
      setEditedText((current) => ({ ...current, [created.id]: created.suggestion_text }));
      setOriginalText("");
      setSuggestionState("ready");
      setMessage("建议已生成，仍需你确认后才能进入最终材料。");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "材料建议生成失败。");
    } finally {
      setCreating(false);
    }
  }

  async function decideSuggestion(suggestionId: string, decision: SuggestionDecision) {
    setWorkingId(suggestionId);
    setMessage("");
    const body: Record<string, string> = { decision };
    if (decision === "edit") {
      body.final_text = editedText[suggestionId]?.trim() ?? "";
    }
    try {
      const response = await fetch(`${apiUrl}/api/suggestions/${suggestionId}/decide`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(await readError(response));
      const updated = (await response.json()) as ResumeSuggestion;
      setSuggestions((current) => current.map((item) => item.id === updated.id ? updated : item));
      setMessage(decision === "reject" ? "建议已拒绝，不会进入最终材料。" : "最终文本已保存到申请记录。 ");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "材料审批失败。");
    } finally {
      setWorkingId(null);
    }
  }

  return (
    <section className="suggestion-panel">
      <div className="suggestion-heading">
        <div>
          <div className="section-kicker"><span>03</span> 材料建议</div>
          <h2>把证据写进 <em>可用文本。</em></h2>
          <p>Agent 只能基于当前经历提出建议。原文、建议和最终文本分开保存，接受前不会影响你的材料。</p>
        </div>
        {application ? <span className="suggestion-context">{application.job.title ?? "未命名岗位"}</span> : null}
      </div>

      {message ? <div className="suggestion-message">{message}</div> : null}
      {!application ? (
        <p className="suggestion-empty">先选择一条申请，才能创建或审批材料建议。</p>
      ) : (
        <div className="suggestion-content">
          <div className="suggestion-composer">
            <div className="suggestion-composer-topline">
              <span className="suggestion-index">REQUEST / 01</span>
              <span>明确原文后再让 Agent 改写</span>
            </div>
            <div className="suggestion-form-pair">
              <label>
                <span>目标类型</span>
                <select value={targetType} onChange={(event) => setTargetType(event.target.value)}>
                  <option value="project_bullet">项目经历</option>
                  <option value="summary">个人简介</option>
                  <option value="skills">技能描述</option>
                  <option value="cover_note">求职备注</option>
                </select>
              </label>
              <label>
                <span>目标标签（可选）</span>
                <input value={targetLabel} onChange={(event) => setTargetLabel(event.target.value)} placeholder="例如：Memory-RAG" />
              </label>
            </div>
            <label className="suggestion-original-input">
              <span>需要修改的原文</span>
              <textarea
                value={originalText}
                onChange={(event) => setOriginalText(event.target.value)}
                placeholder="粘贴一条项目经历、个人简介或技能描述"
                rows={4}
              />
            </label>
            <div className="suggestion-composer-footer">
              <small>JobAnalysis 会自动绑定到当前岗位的最新有效分析。</small>
              <button className="suggestion-generate" onClick={createSuggestion} disabled={creating} type="button">
                {creating ? "生成中…" : "生成材料建议 ↗"}
              </button>
            </div>
          </div>

          {suggestionState === "loading" && suggestions.length === 0 ? <div className="suggestion-empty">正在取回这条申请的材料记录…</div> : null}
          {suggestionState === "error" ? <div className="suggestion-empty suggestion-error">{message || "材料建议暂时取不到。"}</div> : null}
          {suggestionState !== "error" && suggestionState !== "loading" && suggestions.length === 0 ? (
            <div className="suggestion-empty">还没有建议。提供一段原文，看看证据如何被写进岗位相关表达。</div>
          ) : null}
          {suggestions.length > 0 ? (
            <div className="suggestion-list">
              {suggestions.map((suggestion) => (
                <article className={`suggestion-card suggestion-card-${suggestion.status.toLowerCase()}`} key={suggestion.id}>
                  <div className="suggestion-card-topline">
                    <div><span className="suggestion-index">{suggestion.target_label ?? suggestion.target_type}</span><span className="suggestion-run">RUN {suggestion.agent_run_id.slice(-8).toUpperCase()}</span></div>
                    <span className={`suggestion-status suggestion-status-${suggestion.status.toLowerCase()}`}>{suggestionStatusLabel[suggestion.status]}</span>
                  </div>
                  <div className="suggestion-copy-grid">
                    <div className="suggestion-copy">
                      <span>原文</span>
                      <p>{suggestion.original_text}</p>
                    </div>
                    <div className="suggestion-copy suggestion-copy-accent">
                      <span>Agent 建议</span>
                      <p>{suggestion.suggestion_text}</p>
                    </div>
                  </div>
                  <div className="suggestion-evidence-line">
                    <span>证据引用</span>
                    <strong>{suggestion.evidence_ids.length} 条当前用户经历</strong>
                  </div>
                  {suggestion.status === "PENDING" ? (
                    <div className="suggestion-review">
                      <label>
                        <span>编辑后文本 / 可选</span>
                        <textarea
                          value={editedText[suggestion.id] ?? suggestion.suggestion_text}
                          onChange={(event) => setEditedText((current) => ({ ...current, [suggestion.id]: event.target.value }))}
                          rows={3}
                        />
                      </label>
                      <div className="suggestion-actions">
                        <button className="suggestion-primary" disabled={workingId === suggestion.id} onClick={() => decideSuggestion(suggestion.id, "accept")} type="button">采用建议 ↗</button>
                        <button className="suggestion-secondary" disabled={workingId === suggestion.id} onClick={() => decideSuggestion(suggestion.id, "edit")} type="button">保存编辑</button>
                        <button className="suggestion-reject" disabled={workingId === suggestion.id} onClick={() => decideSuggestion(suggestion.id, "reject")} type="button">拒绝</button>
                      </div>
                    </div>
                  ) : suggestion.status === "ACCEPTED" ? (
                    <div className="suggestion-final"><span>FINAL TEXT</span><p>{suggestion.final_text}</p></div>
                  ) : (
                    <div className="suggestion-final suggestion-final-rejected"><span>NOT SAVED</span><p>用户拒绝了这条建议，未产生最终文本。</p></div>
                  )}
                </article>
              ))}
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}

function eventDescription(event: ApplicationEvent): string {
  const fromStatus = event.payload.from_status;
  const toStatus = event.payload.to_status;
  if (typeof fromStatus === "string" && typeof toStatus === "string") {
    const from = applicationStatusLabel[fromStatus as ApplicationStatus] ?? fromStatus;
    const to = applicationStatusLabel[toStatus as ApplicationStatus] ?? toStatus;
    return `${from} → ${to}`;
  }
  if (event.event_type === "SuggestionCreated") {
    const count = event.payload.evidence_count;
    return `引用 ${typeof count === "number" ? count : 0} 条经历证据，等待用户审批`;
  }
  if (event.event_type === "SuggestionDecisionRecorded") {
    const decision = event.payload.decision;
    const finalTextPresent = event.payload.final_text_present === true;
    const decisionLabel = decision === "reject" ? "拒绝建议" : decision === "edit" ? "编辑后接受" : "接受建议";
    return `${decisionLabel} · ${finalTextPresent ? "已保存最终文本" : "未保存最终文本"}`;
  }
  if (event.event_type === "ApplicationAttemptCreated") {
    return `已绑定投递包版本 ${String(event.payload.packet_revision_id ?? "").slice(-8).toUpperCase()}，尚未打开表单`;
  }
  if (event.event_type === "ApplicationAttemptStatusChanged") {
    const from = String(event.payload.from_status ?? "");
    const to = String(event.payload.to_status ?? "");
    return `${attemptStatusLabel[from] ?? from} → ${attemptStatusLabel[to] ?? to}`;
  }
  if (event.event_type === "ApplicationBlockerOpened") {
    const category = String(event.payload.category ?? "other");
    return `暂停填写并记录 ${category} 阻塞，等待解决后继续`;
  }
  if (event.event_type === "ApplicationBlockerResolved") {
    const remaining = Number(event.payload.remaining_open_blockers ?? 0);
    return `阻塞已解决 · 仍有 ${remaining} 项待处理`;
  }
  if (event.event_type === "SubmissionReceiptRecorded") {
    const codes = Array.isArray(event.payload.validation_codes) ? event.payload.validation_codes : [];
    return `凭证已冻结 · ${codes.length} 类成功证据通过校验，申请状态尚未改变`;
  }
  if (event.event_type === "ApplicationSubmissionVerified") {
    return "投递包、执行记录与真实凭证已关联，申请进入已投递";
  }
  if (event.event_type === "FollowUpTaskCreated") {
    const type = followUpEventTypeLabel[String(event.payload.event_type ?? "")] ?? "跟进事项";
    return `${type}已加入日程 · ${String(event.payload.scheduled_at ?? "时间待确认")}`;
  }
  if (event.event_type === "FollowUpTaskUpdated") {
    const fields = Array.isArray(event.payload.changed_fields) ? event.payload.changed_fields.length : 0;
    return `跟进日程已更新 · ${fields} 个字段发生变化，申请状态未改变`;
  }
  if (event.event_type === "FollowUpTaskCompleted") {
    return "跟进任务已完成 · 申请阶段仍需用户根据事实单独确认";
  }
  if (event.event_type === "FollowUpTaskCancelled") {
    return "跟进任务已取消 · 历史记录继续保留";
  }
  if (event.event_type === "AtsAssistanceInspected") {
    return `${String(event.payload.provider ?? "ATS")} 表单已检查 · ${String(event.payload.field_count ?? 0)} 个字段`;
  }
  if (event.event_type === "AtsAssistanceNeedsUser") {
    return "浏览器辅助已暂停 · 需要用户确认字段或完成人工验证";
  }
  if (event.event_type === "AtsSensitiveFieldsConfirmed") {
    const fields = Array.isArray(event.payload.field_keys) ? event.payload.field_keys.length : 0;
    return `已针对本次表单确认 ${fields} 个高影响字段`;
  }
  if (event.event_type === "AtsAssistancePrepared") {
    return `字段填写已验证 · ${String(event.payload.fill_count ?? 0)} 个字段等待最终授权`;
  }
  if (event.event_type === "AtsSubmissionAuthorized") {
    return "一次性提交授权已签发 · 仅绑定当前岗位、URL、投递包和页面指纹";
  }
  if (event.event_type === "AtsSubmissionStarted") {
    return "一次性授权已消费 · 正在执行受控 ATS 提交";
  }
  if (event.event_type === "AtsSubmissionUnverified") {
    return "ATS 未返回足够成功证据 · 禁止自动重试，等待人工核对";
  }
  if (event.event_type === "AtsSubmissionVerified") {
    return "ATS 成功信息已生成有效凭证 · 申请进入已投递";
  }
  return "用户确认创建申请记录";
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function countDiscoveryMatches(run: DiscoveryRunItem, tier: DiscoveryResultMatch["match_tier"]): number {
  return (run.result_matches ?? []).filter((match) => match.match_tier === tier).length;
}

function Fact({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return <div className={`fact-card ${accent ? "fact-accent" : ""}`}><span>{label}</span><strong>{value}</strong></div>;
}

function MatchRow({ match }: { match: RequirementMatch }) {
  return (
    <article className={`match-row match-${match.support_level}`}>
      <div className="match-main">
        <div className="match-title-line">
          <strong>{match.requirement.name}</strong>
          <span className="match-category">{groupLabel[match.requirement.category] ?? match.requirement.category}</span>
          {match.requirement.relation ? (
            <span className="match-category" title={match.requirement.relation_reason ?? undefined}>
              {relationLabel[match.requirement.relation]}
            </span>
          ) : null}
        </div>
        <p>{match.requirement.description}</p>
        <div className="match-explanation"><span className="quote-mark">“</span>{match.explanation}</div>
      </div>
      <div className="match-status"><span className="match-status-dot" /><strong>{supportLabel[match.support_level]}</strong><small>{match.evidence_ids.length > 0 ? `${match.evidence_ids.length} 条引用` : "需要补充"}</small></div>
    </article>
  );
}

function internshipCopy(jd: AnalysisResponse["structured_jd"]): string {
  const parts: string[] = [];
  if (jd.internship_duration_months !== null) parts.push(`${jd.internship_duration_months} 个月`);
  if (jd.weekly_days !== null) parts.push(`每周 ${jd.weekly_days} 天`);
  return parts.length > 0 ? parts.join(" · ") : "未识别";
}
