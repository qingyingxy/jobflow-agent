"use client";
import { parseApiTimestamp } from "./api-time";
import { reviewStatus, reviewCounts, reviewCaveats, reviewRelevance, jobReviewSummary } from "./discovery-review";
import { EducationEditor, EducationRecord, educationLabels } from "./education-editor";
import { FactDifferences, type FactProvenance } from "./fact-differences";

import { useEffect, useRef, useState, type ReactNode } from "react";

import JobCorrectionEditor from "./job-correction-editor";
import AccountPrivacy from "./account-privacy";
import CompanyDiscoveryPanel, { type DiscoveredCompanySource } from "./company-discovery-panel";
import ManualSubmission from "./manual-submission";
import AttemptWorkspace from "./attempt-workspace";
import AtsWorkspace from "./ats-workspace";
import FollowUpWorkspace from "./follow-up-workspace";
import MaterialsWorkspace from "./materials-workspace";
import PacketWorkspace from "./packet-workspace";
import SearchGoalControls, { type SearchGoal } from "./search-goal-controls";
import SearchProgress from "./search-progress";
import SearchActivity from "./search-activity";
import TrackingCenter from "./tracking-center";
import CampaignWorkspace, { type CampaignTarget } from "./campaign-workspace";
import JobDescription from "./job-description";

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
  education?: { relation: "all_of" | "any_of" | "uncertain"; branches: Array<{ source_text: string }> } | null;
};

type RequirementMatch = {
  requirement: JobRequirement;
  support_level: SupportLevel;
  evidence_ids: string[];
  education_evidence?: EducationRecord[];
  item_checks?: { source_text: string; condition_text: string; support_level: SupportLevel; evidence_quotes: string[]; unresolved: string[] }[];
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
    graduation_condition_kind?: "simple" | "qualified" | "ambiguous" | null;
    graduation_source_text?: string | null;
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
      jd_evidence?: Array<{ source_text: string }>;
      education_evidence?: EducationRecord[];
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
type ApplicationTool = "packet" | "attempt" | "assisted" | "followup";
type ProfileSummaryState = "loading" | "ready" | "missing_resume" | "missing_evidence" | "missing_education" | "error";

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
  educations?: EducationRecord[];
  education_history_complete?: boolean;
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
  provenance?: FactProvenance;
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
  pendingLead?: JobLeadItem;
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
  search_goal_id?: string | null;
  search_goal_version?: number | null;
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
  usage_metrics?: {
    first_result_ms: number | null; first_useful_ms: number | null;
    first_fresh_useful_ms?: number | null;
    first_recommended_ms?: number | null; first_fresh_recommended_ms?: number | null;
    first_new_recommended_ms?: number | null;
    new_recommended_jobs?: number; resolved_recommended_jobs?: number;
    source_read_attempts?: number; source_read_successes?: number; source_read_success_rate?: number | null;
    source_retry_attempts?: number; source_retry_recovered?: number;
    read_attempts: number; read_successes: number; read_success_rate: number | null;
    cache_hits: number; retry_attempts: number; retry_recovered: number;
    new_effective_jobs: number; resolved_effective_jobs: number; effective_job_gain: number;
  } | null;
  result_matches: DiscoveryResultMatch[];
  filter_conditions?: Record<string, (string | number)[]>;
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
  filter_status?: "matched" | "pending" | "excluded";
  review_status?: "recommended" | "pending" | "excluded" | null;
  preference_score?: number;
  personal_requirements?: { category: string; status: string; label: string; reason: string; evidence: string; source_url: string | null }[];
  personal_gate_conflict?: boolean;
  result_status?: {
    reading: { status: string; reason?: string | null };
    analysis: { state: string; label: string; reason: string };
    search: { state: string; label: string; missing_fields: string[] };
    personal: { state: string; label: string; reason: string };
  };
  checks?: { field: string; status: "matched" | "pending" | "excluded"; reason: string; evidence: string[]; source_url: string }[];
};

type GoalLibrary = {
  goal_id: string; goal_version: number; query: string; lead_ids: string[];
  result_matches: DiscoveryResultMatch[]; latest_run_id: string | null;
  updates: { kind: "new" | "changed" | "closed"; job_posting_id: string; title: string; company: string | null }[];
  counts: Record<string, number>;
  company_progress?: CompanySearchProgress[];
  company_discovery?: DiscoveredCompanySource[];
  company_discovery_queue?: { status: string; stage: string; enabled: boolean; queries_completed: number; queries_total: number; links_saved: number; companies_pending: number; companies_verified: number; error?: string | null; next_run_at?: string | null };
  review_queue?: { status: string; enabled: boolean; remaining: number; waiting: number; cooldown: number; blocked: number; processed: number; completed: number; error?: string | null;
    lanes?: Record<"source" | "qualifications", { remaining: number; waiting: number; cooldown: number; blocked: number }> };
};

type CompanySearchProgress = {
  source_id: string; company: string; official_url: string;
  status: "not_checked" | "running" | "paused" | "completed" | "failed" | "stale";
  matched_count: number; checked_count: number; pages_checked: number;
  pending_count?: number; remaining_count?: number;
  strategy?: "official_listing" | "web_search" | null;
  search_attempts?: number;
  can_continue: boolean;
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
  | "DEFERRED"
  | "VERIFIED"
  | "CLOSED"
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
  discovery_kind?: "job" | "entry";
  source_label?: string;
  selection_status?: "DISCOVERED" | "SAVED" | "IGNORED";
  id: string;
  discovery_run_id: string | null;
  provider: "official_adapter" | LeadSubmissionProvider;
  source_id: string | null;
  source_job_id: string | null;
  source_url: string;
  normalized_url: string;
  company_hint: string | null;
  extracted_fields?: { title?: string; company?: string; locations?: string[]; job_type?: string | null; basis?: string; raw_content?: string };
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
  needs_confirmation: "信息不足",
  unsupported: "无证据",
};

const relationLabel: Record<NonNullable<JobRequirement["relation"]>, string> = {
  all_of: "要求全部满足",
  any_of: "任选其一",
  uncertain: "关系待确认",
};

const groupLabel: Record<string, string> = {
  required_skill: "必备技能",
  preferred_skill: "加分技能",
  preferences: "偏好条件",
  education: "学历条件",
  major: "专业条件",
  experience: "经历要求",
  general: "综合要求",
};

function qualificationName(field: string, rule: string): string {
  const names: Record<string, string> = {
    educations: "学历及专业条件", education: "学历要求", major: "专业要求",
    graduation_year: "毕业届别", locations: "工作地点", job_type: "招聘类型",
  };
  return names[field] ?? names[rule] ?? "资格条件";
}

function educationConditionSummary(jd: AnalysisResponse["structured_jd"]): string {
  const conditions = (jd.requirements ?? []).filter((r) => r.education).map((r) => r.description);
  return compactList(conditions.length ? conditions : [...(jd.education_requirements ?? []), ...(jd.major_requirements ?? [])]);
}

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
  PortalApplicationObserved: "官网进度同步",
  PortalApplicationUnlinked: "解除官网关联",
  ApplicationCreated: "创建申请",
  ApplicationStatusChanged: "更新申请状态",
  ApplicationAttemptCreated: "创建投递尝试",
  ApplicationAttemptStatusChanged: "更新投递执行",
  ApplicationBlockerOpened: "记录投递阻塞",
  ApplicationBlockerResolved: "解决投递阻塞",
  SubmissionReceiptRecorded: "保存提交凭证",
  ApplicationSubmissionVerified: "确认真实投递",
  ManualSubmissionRecorded: "用户登记已投递",
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
  DEFERRED: "暂缓核验，可重试",
  VERIFIED: "已验证",
  CLOSED: "原页面确认已下线",
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
  const [discoveryMode, setDiscoveryMode] = useState<"jobs" | "campaigns">("jobs");
  const [campaignYear, setCampaignYear] = useState<number | undefined>();
  const [trackingGoal, setTrackingGoal] = useState<SearchGoal | null>(null);
  const [focusedApplicationId, setFocusedApplicationId] = useState<string | null>(null);
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
  const [activePosting, setActivePosting] = useState<{ id: string; raw_content: string; company: string; title: string } | null>(null);
  const [state, setState] = useState<AnalysisState>("empty");
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [applications, setApplications] = useState<ApplicationItem[]>([]);
  const [boardState, setBoardState] = useState<BoardState>("idle");
  const [boardMessage, setBoardMessage] = useState("");
  const [updatingApplicationId, setUpdatingApplicationId] = useState<string | null>(null);
  const [preparingApplication, setPreparingApplication] = useState(false);
  const [candidates, setCandidates] = useState<CandidateItem[]>([]);
  const [candidatesLoaded, setCandidatesLoaded] = useState(false);
  const candidateRevisionRef = useRef(0);
  const [jobLeads, setJobLeads] = useState<JobLeadItem[]>([]);
  const [leadsLoaded, setLeadsLoaded] = useState(false);
  const [discoveryRuns, setDiscoveryRuns] = useState<DiscoveryRunItem[]>([]);
  const [discoveryState, setDiscoveryState] = useState<DiscoveryState>("idle");
  const [searchStarting, setSearchStarting] = useState(false);
  const [discoveryMessage, setDiscoveryMessage] = useState("");
  const [discoveryQuery, setDiscoveryQuery] = useState("");
  const [activeGoal, setActiveGoal] = useState<SearchGoal | null>(null);
  const [goalLibrary, setGoalLibrary] = useState<GoalLibrary | null>(null);
  const [goalLibraryError, setGoalLibraryError] = useState("");
  const [goalLibraryLoading, setGoalLibraryLoading] = useState(false);
  const [goalProgress, setGoalProgress] = useState<Pick<GoalLibrary, "goal_id" | "goal_version" | "review_queue" | "company_discovery_queue"> | null>(null);
  const progressInFlightRef = useRef<string | null>(null);
  const mergedGoalLibrary = goalLibrary && goalProgress?.goal_id === goalLibrary.goal_id && goalProgress.goal_version === goalLibrary.goal_version
    ? { ...goalLibrary, ...goalProgress } : goalLibrary;
  const [discoveryRefreshToken, setDiscoveryRefreshToken] = useState(0);
  const activeGoalRef = useRef<SearchGoal | null>(null);
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
  const queryRestoredRef = useRef(false);
  const queryEditedRef = useRef(false);
  const pollingRunsRef = useRef(new Set<string>());
  const startingSearchRef = useRef(false);
  const discoveryLoadRef = useRef(0);
  const discoveryRefreshPendingRef = useRef(false);
  const profileLoadRef = useRef(0);
  const libraryLoadRef = useRef(0);
  const libraryInFlightRef = useRef<{ key: string; promise: Promise<void> } | null>(null);

  function chooseGoal(goal: SearchGoal | null) {
    setTrackingGoal(null);
    const unchanged = activeGoalRef.current?.id === goal?.id && activeGoalRef.current?.version === goal?.version;
    activeGoalRef.current = goal;
    setActiveGoal(goal);
    if (!unchanged) { setGoalLibrary(null); setGoalProgress(null); setGoalLibraryLoading(false); }
    setGoalLibraryError("");
    queryEditedRef.current = true;
    setSelectedDiscoveryCompanyIds(goal?.company_ids || []);
    if (goal) void loadGoalLibrary();
  }

  async function loadGoalLibrary() {
    const goal = activeGoalRef.current;
    if (!goal) return;
    const key = `${goal.id}:${goal.version}`;
    // A slow response is still useful. Polling must not supersede it forever.
    if (libraryInFlightRef.current?.key === key) return libraryInFlightRef.current.promise;
    const request = ++libraryLoadRef.current;
    const current = () => request === libraryLoadRef.current && activeGoalRef.current?.id === goal.id && activeGoalRef.current?.version === goal.version;
    setGoalLibraryLoading(true);
    void loadGoalProgress(goal);
    const promise = (async () => { try {
      const response = await fetch(`${apiUrl}/api/discovery/goals/${goal.id}/library?include_progress=false`, {
        headers: { "X-User-ID": userId }, cache: "no-store",
      });
      if (!response.ok) throw new Error(await readError(response));
      const library = await response.json() as GoalLibrary;
      if (current() && library.goal_id === goal.id && library.goal_version === goal.version) {
        setGoalLibrary(library); setGoalLibraryError("");
      }
    } catch (error) {
      if (current()) setGoalLibraryError(error instanceof Error ? error.message : "岗位库读取失败");
    } })();
    libraryInFlightRef.current = { key, promise };
    try { await promise; } finally {
      if (libraryInFlightRef.current?.promise === promise) libraryInFlightRef.current = null;
      if (current()) setGoalLibraryLoading(false);
    }
  }

  async function loadGoalProgress(goal: SearchGoal) {
    const key = `${goal.id}:${goal.version}`;
    if (progressInFlightRef.current === key) return;
    progressInFlightRef.current = key;
    try {
      const response = await fetch(`${apiUrl}/api/discovery/goals/${goal.id}/progress`, { headers: { "X-User-ID": userId }, cache: "no-store" });
      if (!response.ok) return;
      const progress = await response.json();
      if (activeGoalRef.current?.id === goal.id && activeGoalRef.current?.version === goal.version
          && progress.goal_id === goal.id && progress.goal_version === goal.version) setGoalProgress(progress);
    } catch { /* A progress refresh cannot erase the saved job list. */ }
    finally { if (progressInFlightRef.current === key) progressInFlightRef.current = null; }
  }

  useEffect(() => {
    if (!activeGoal || ![mergedGoalLibrary?.review_queue?.status, mergedGoalLibrary?.company_discovery_queue?.status].some(status => ["queued", "running"].includes(status || ""))) return;
    const discovery = mergedGoalLibrary?.company_discovery_queue;
    const reviewing = ["queued", "running"].includes(mergedGoalLibrary?.review_queue?.status || "");
    const cooling = discovery?.status === "queued" && discovery.next_run_at && parseApiTimestamp(discovery.next_run_at).getTime() - Date.now() > 60000;
    const timer = window.setInterval(() => { void loadGoalLibrary(); }, !reviewing && cooling ? 60000 : 4000);
    return () => window.clearInterval(timer);
  }, [activeGoal?.id, activeGoal?.version, mergedGoalLibrary?.review_queue?.status, mergedGoalLibrary?.company_discovery_queue?.status, mergedGoalLibrary?.company_discovery_queue?.next_run_at]);

  async function loadProfileSummary() {
    const request = ++profileLoadRef.current;
    setProfileSummary((current) => ({ ...current, state: "loading" }));
    try {
      const headers = { "X-User-ID": userId };
      const [resumeResponse, evidenceResponse, profileResponse] = await Promise.all([
        fetch(`${apiUrl}/api/resumes/versions`, { headers, cache: "no-store" }),
        fetch(`${apiUrl}/api/evidence`, { headers, cache: "no-store" }),
        fetch(`${apiUrl}/api/profile`, { headers, cache: "no-store" }),
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
      const evidence = evidenceResponse.ok ? await evidenceResponse.json() as EvidenceRecord[] : [];
      if (!profileResponse.ok && profileResponse.status !== 404) throw new Error(await readError(profileResponse));
      const profile = profileResponse.ok ? await profileResponse.json() as ProfileRecord : null;
      const genericEvidenceCount = evidence.filter((item) => item.type !== "education" || !profile?.educations?.length).length;
      const evidenceCount = genericEvidenceCount + (profile?.educations?.length ?? 0);
      const educationReady = profile?.educations?.length
        ? profile.educations.every((item) => item.level !== "unknown" && item.major_raw && item.graduation_year)
        : Boolean(profile?.degree && profile?.major && profile?.graduation_year);
      if (request !== profileLoadRef.current) return;
      setProfileSummary({
        state: resumeCount === 0 ? "missing_resume" : evidenceCount === 0 ? "missing_evidence" : !educationReady ? "missing_education" : "ready",
        resumeCount,
        evidenceCount,
      });
    } catch (error) {
      if (request !== profileLoadRef.current) return;
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
    const request = ++discoveryLoadRef.current;
    if (!options.quiet) { discoveryRefreshPendingRef.current = true; setDiscoveryState("loading"); }
    const leadRevision = jobLeadRevisionRef.current;
    const candidateRevision = candidateRevisionRef.current;
    async function read<T>(path: string, apply: (value: T) => void) {
      const response = await fetch(`${apiUrl}${path}`, { headers: { "X-User-ID": userId }, cache: "no-store" });
      if (!response.ok) throw new Error(await readError(response));
      const body = await response.json() as T;
      if (request === discoveryLoadRef.current) apply(body);
    }
    const results = await Promise.allSettled([
      read<CandidateItem[]>("/api/candidates", rows => {
        if (candidateRevision === candidateRevisionRef.current) { setCandidates(rows); setCandidatesLoaded(true); }
      }),
      read<JobLeadItem[]>("/api/discovery/leads", leads => {
        if (leadRevision === jobLeadRevisionRef.current) { setJobLeads(leads); setLeadsLoaded(true); }
      }),
      read<DiscoveryRunItem[]>("/api/discovery/runs?compact=true&limit=20", runs => {
        setDiscoveryRuns(runs);
        if (!queryRestoredRef.current) {
          queryRestoredRef.current = true;
          const latestSearch = runs.find(run => run.search_query);
          if (latestSearch?.search_query && !queryEditedRef.current) setDiscoveryQuery(latestSearch.search_query);
        }
      }),
      read<DiscoverySourceOption[]>("/api/discovery/sources", setDiscoverySources),
      loadGoalLibrary(),
    ]);
    if (request !== discoveryLoadRef.current) return;
    // A newer quiet refresh must finish an overlapping visible refresh too.
    const foreground = discoveryRefreshPendingRef.current;
    discoveryRefreshPendingRef.current = false;
    const names = ["岗位列表", "岗位线索", "搜索历史", "官网来源", "目标岗位库"];
    const failed = results.flatMap((result, i) => result.status === "rejected" ? [names[i]] : []);
    if (failed.length) {
      if (foreground) {
        setDiscoveryState("error");
        setDiscoveryMessage(`${failed.join("、")}读取失败，已保留可用内容。请重试连接。`);
      }
    } else {
      setDiscoveryState(current => current === "error" || foreground
        ? (startingSearchRef.current || pollingRunsRef.current.size ? "loading" : "ready") : current);
      setDiscoveryMessage(current => current === "Failed to fetch" || current.includes("请重试连接") ? "连接已恢复" : current);
    }
  }

  function retryDiscovery() {
    setDiscoveryRefreshToken(value => value + 1);
    void loadProfileSummary();
    void loadDiscoveryData();
  }

  async function findCampaignJobs(campaign: CampaignTarget) {
    const conditions = { ...(activeGoalRef.current?.conditions || {}), graduation_years: [campaign.year],
      job_types: ["校招"], excluded_job_types: [] };
    const response = await fetch(`${apiUrl}/api/discovery/goals`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-User-ID": userId },
      body: JSON.stringify({ input_text: `${campaign.company} ${campaign.year}届校招`,
        name: `${campaign.company} ${campaign.year}届校招`, conditions, company_ids: [campaign.company_id] }),
    });
    if (!response.ok) throw new Error(await readError(response));
    const goal = await response.json() as SearchGoal;
    chooseGoal(goal);
    setTrackingGoal(goal);
    setDiscoveryQuery(goal.input_text);
    setDiscoveryMode("jobs");
    await runDiscovery(goal);
  }

  async function runDiscovery(goal: SearchGoal, continueCompanyId?: string) {
    if (startingSearchRef.current || discoveryRuns.some(run => run.status === "RUNNING" && run.search_goal_id === goal.id)) return;
    if (goal.query.trim().length < 2) {
      setDiscoveryState("error");
      setDiscoveryMessage("请先描述想找的岗位，例如：上海的 AI Agent 校招。");
      return;
    }
    startingSearchRef.current = true;
    setSearchStarting(true);
    setDiscoveryState("loading");
    setDiscoveryMessage(continueCompanyId ? "正在接着查询这家公司，已有岗位和保存状态会保留…" : "正在读取招聘官网，岗位会陆续显示，可以边看边等…");
    try {
      const response = await fetch(`${apiUrl}/api/discovery/goals/${goal.id}/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({
          expected_version: goal.version,
          continue_company_id: continueCompanyId,
        }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const run = (await response.json()) as DiscoveryRunItem;
      setDiscoveryRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
      void pollDiscoveryRun(run.id);
    } catch (error) {
      setDiscoveryState("error");
      setDiscoveryMessage(error instanceof Error ? error.message : "全网岗位搜索启动失败。");
    } finally { startingSearchRef.current = false; setSearchStarting(false); }
  }

  async function pollDiscoveryRun(runId: string) {
    if (pollingRunsRef.current.has(runId)) return;
    pollingRunsRef.current.add(runId);
    let lastResults = "";
    let connectionFailures = 0;
    try {
    for (let attempt = 0; attempt < 1240; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, Math.min(15000, 1500 * 2 ** connectionFailures)));
      try {
        const response = await fetch(`${apiUrl}/api/discovery/runs/${runId}?compact=true`, {
          headers: { "X-User-ID": userId },
          cache: "no-store",
          signal: AbortSignal.timeout(15000),
        });
        if ([401, 403, 404].includes(response.status)) {
          setDiscoveryState("error");
          setDiscoveryMessage(await readError(response));
          return;
        }
        if (!response.ok) throw new Error(await readError(response));
        const run = (await response.json()) as DiscoveryRunItem;
        const results = JSON.stringify([run.discovered_count, run.result_matches]);
        if (results !== lastResults || run.status !== "RUNNING") {
          await loadRunResults(runId);
          lastResults = results;
        } else if (attempt % 4 === 0) await loadGoalLibrary();
        connectionFailures = 0;
        if (run.status === "RUNNING") setDiscoveryState("loading");
        setDiscoveryRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
        const counts = reviewCounts(run.result_matches);
        const verifiedCount = run.result_matches.length;
        const summary = `正文已核验 ${verifiedCount} 条：优先查看 ${counts.recommended} 条（搜索条件已确认 ${counts.confirmed} 条），待核实 ${counts.pending} 条，明确不符 ${counts.excluded} 条。`;
        setDiscoveryMessage(verifiedCount ? summary : `已找到 ${run.discovered_count} 条线索，正在核验原始岗位页…`);
        if (run.status !== "RUNNING") {
          setDiscoveryState(run.status === "FAILED" ? "error" : "ready");
          setDiscoveryMessage((verifiedCount ? summary : "本次暂未核验出具体岗位，已发现线索会保留，可继续核验或调整条件搜索。")
            + (run.status === "FAILED" || run.status === "PARTIAL" ? " 部分查询未完成，已有结果已保存，可继续查找。" : ""));
          return;
        }
      } catch {
        connectionFailures = Math.min(4, connectionFailures + 1);
        setDiscoveryMessage("进度连接暂时中断，正在自动重连。已显示的岗位仍可查看，请勿重复启动搜索。");
      }
    }
    setDiscoveryState("error");
    setDiscoveryMessage("搜索时间超过预期，请刷新候选池查看已经保存的岗位。");
    } finally { pollingRunsRef.current.delete(runId); }
  }

  async function loadRunResults(runId: string) {
    const headers = { "X-User-ID": userId };
    const leadRevision = jobLeadRevisionRef.current;
    const candidateRevision = candidateRevisionRef.current;
    const [candidateResponse, leadResponse] = await Promise.all([
      fetch(`${apiUrl}/api/candidates?discovery_run_id=${encodeURIComponent(runId)}`, { headers, cache: "no-store" }),
      fetch(`${apiUrl}/api/discovery/leads?discovery_run_id=${encodeURIComponent(runId)}`, { headers, cache: "no-store" }),
    ]);
    if (!candidateResponse.ok) throw new Error(await readError(candidateResponse));
    if (!leadResponse.ok) throw new Error(await readError(leadResponse));
    const changed = await candidateResponse.json() as CandidateItem[];
    const leads = await leadResponse.json() as JobLeadItem[];
    setCandidates(old => {
      const current = new Map(old.map(item => [item.id, item]));
      for (const item of changed) {
        const previous = current.get(item.id);
        current.set(item.id, previous && candidateRevision !== candidateRevisionRef.current
          ? { ...item, status: previous.status } : item);
      }
      return [...current.values()];
    });
    if (leadRevision === jobLeadRevisionRef.current) {
      setJobLeads(old => [...old.filter(item => item.discovery_run_id !== runId), ...leads]);
    }
    await loadGoalLibrary();
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
      let response = await fetch(`${apiUrl}/api/discovery/leads/${leadId}/verify`, {
        method: "POST",
        headers: { "X-User-ID": userId },
      });
      if (!response.ok) {
        const failure = await response.clone().json().catch(() => null);
        if (["lead_requires_browser", "job_detail_unconfirmed"].includes(failure?.detail?.code)) {
          setDiscoveryMessage("正在加载动态页面；文字提取失败时将自动尝试截图识别…");
          response = await fetch(`${apiUrl}/api/discovery/leads/${leadId}/handoff/browser`, {
            method: "POST", headers: { "X-User-ID": userId },
          });
        }
      }
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
    const previous = candidates.find(item => item.id === candidateId);
    candidateRevisionRef.current += 1;
    setCandidates(current => current.map(item => item.id === candidateId ? { ...item, status } : item));
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
      candidateRevisionRef.current += 1;
      setCandidates((current) => current.map((item) => item.id === updated.id ? updated : item));
      return true;
    } catch (error) {
      candidateRevisionRef.current += 1;
      if (previous) setCandidates(current => current.map(item => item.id === candidateId ? previous : item));
      setDiscoveryMessage(error instanceof Error ? error.message : "候选岗位状态更新失败。");
      return false;
    } finally {
      setUpdatingCandidateId(current => current === candidateId ? null : current);
    }
  }

  async function openCandidate(jobId: string) {
    setMode("analysis");
    setState("loading");
    setErrorMessage("");
    setActivePosting(null);
    setRawContent("");
    setAnalysis(null);
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
      setActivePosting({ id: jobId, raw_content: posting.raw_content, company: posting.company ?? "", title: posting.title ?? "" });
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

  useEffect(() => {
    if (mode === "discover") discoveryRuns.filter(run => run.status === "RUNNING").forEach(run => { void pollDiscoveryRun(run.id); });
  }, [mode, discoveryRuns.map(run => `${run.id}:${run.status}`).join(",")]);

  function openManualJD(leadId?: string) {
    const lead = leadId ? jobLeads.find((item) => item.id === leadId) : null;
    setRawContent("");
    setActivePosting(null);
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
      if (activePosting && activePosting.raw_content === rawContent && activePosting.company === company && activePosting.title === title) {
        posting = activePosting;
      } else if (manualHandoffLeadId) {
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

      // Preserve identity even if analysis fails; retry the same saved document.
      setActivePosting({ id: posting.id, raw_content: rawContent, company, title });
      setManualHandoffLeadId(null);

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

  function prepareApplication() {
    const jobId = analysis?.job.id || activePosting?.id;
    if (jobId) void trackApplication(jobId);
  }

  async function trackApplication(jobId: string): Promise<boolean> {
    if (preparingApplication) return false;
    setPreparingApplication(true);
    setBoardMessage("正在创建申请记录…");
    try {
      const candidateResponse = await fetch(`${apiUrl}/api/candidates`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({ job_posting_id: jobId }),
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
      const application = await applicationResponse.json() as ApplicationItem;
      await loadApplications();
      setFocusedApplicationId(application.id);
      void loadDiscoveryData({ quiet: true });
      setBoardMessage("已加入申请进度。完成官网投递后，可登记已投递并安排跟进。");
      setMode("board");
      window.dispatchEvent(new Event("jobflow:tracking-changed"));
      return true;
    } catch (error) {
      setBoardMessage(error instanceof Error ? error.message : "申请创建失败。 ");
      return false;
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
      window.dispatchEvent(new Event("jobflow:tracking-changed"));
    } catch (error) {
      setBoardMessage(error instanceof Error ? error.message : "状态更新失败。 ");
    } finally {
      setUpdatingApplicationId(null);
    }
  }

  const profileStatusTitle = profileSummary.state === "ready"
    ? "简历与经历已载入"
    : profileSummary.state === "missing_education"
      ? "教育信息待补充"
    : profileSummary.state === "missing_resume"
      ? "尚未上传简历"
      : profileSummary.state === "missing_evidence"
        ? "简历已上传"
        : profileSummary.state === "loading"
          ? "正在检查个人资料"
          : "个人资料状态暂不可用";
  const profileStatusDetail = profileSummary.state === "ready"
    ? `${profileSummary.evidenceCount} 条经历证据`
    : profileSummary.state === "missing_education"
      ? "已有经历可用于匹配"
    : profileSummary.state === "missing_resume"
      ? "点击上传"
      : profileSummary.state === "missing_evidence"
        ? "待补充经历证据"
        : profileSummary.state === "loading"
          ? "请稍候"
          : "点击检查";
  const discoveredCount = candidates.filter((item) => item.status === "DISCOVERED").length;

  return (
    <main className={`workspace-shell jobflow-clean${isHydrated ? " workspace-hydrated" : ""}`}>
      <header className="workspace-topbar">
        <div className="brand-lockup">
          <span className="brand-name">JobFlow</span>
        </div>
          <nav className="workspace-nav" aria-label="工作区导航">
            <button
              aria-current={mode === "discover" || mode === "analysis" ? "page" : undefined}
              aria-label={`发现岗位，${discoveredCount} 条候选`}
              className={mode === "discover" || mode === "analysis" ? "workspace-nav-active" : ""}
              disabled={!isHydrated}
              onClick={() => setMode("discover")}
              type="button"
            >
              <strong>发现岗位</strong>
            </button>
            <button
              aria-current={mode === "board" ? "page" : undefined}
              className={mode === "board" ? "workspace-nav-active" : ""}
              disabled={!isHydrated}
              onClick={() => setMode("board")}
              type="button"
            >
              <strong>申请进度</strong>
            </button>
            <button
              aria-current={mode === "profile" ? "page" : undefined}
              aria-label="简历资料"
              className={mode === "profile" ? "workspace-nav-active" : ""}
              disabled={!isHydrated}
              onClick={() => setMode("profile")}
              type="button"
            >
              <strong>简历资料</strong>
            </button>
          </nav>
        <div className="topbar-trail">
          <TrackingCenter apiUrl={apiUrl} userId={userId}
            onSelectGoal={goal => { setTrackingGoal(goal); setDiscoveryMode("jobs"); setMode("discover"); }}
            onOpenCampaigns={year => { setCampaignYear(year); setDiscoveryMode("campaigns"); setMode("discover"); }}
            onOpenBoard={() => { setMode("board"); void loadApplications(); }}
            onScheduleChange={() => setDiscoveryRefreshToken(value => value + 1)} />
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
          {profileSummary.state === "error" && <button type="button" onClick={retryDiscovery}>重新连接资料</button>}
        </div>
      </header>

      <div className="workspace-frame">


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
                    ? discoveryMode === "campaigns" ? "关注公司的秋招动态" : "发现适合你的岗位"
                    : mode === "profile"
                      ? "核对你的经历"
                      : "跟进每份申请"}
              </h1>
            </div>
            <p className="intro-note">
              {mode === "profile"
                ? "这里优先展示从简历自动解析的经历。确认或修改后，它们会成为岗位匹配的依据。"
                : mode === "discover"
                  ? discoveryMode === "campaigns" ? "先看哪些公司开招，再查看与你相关的岗位。" : "按本次输入的城市、方向和招聘类型搜索，无需先填写简历。添加简历后可进一步分析匹配情况。"
                  : mode === "analysis"
                    ? "根据岗位原文和已保存的经历，查看匹配依据与申请建议。"
                    : "查看当前状态、下一步和关键时间。"}
            </p>
          </section>

          {mode === "discover" && <div className="discovery-mode-tabs" role="tablist" aria-label="发现方式">
            {(["jobs", "campaigns"] as const).map(item => <button key={item} type="button" role="tab"
              id={`discovery-mode-${item}`} aria-controls={`discovery-panel-${item}`} aria-selected={discoveryMode === item}
              tabIndex={discoveryMode === item ? 0 : -1} onClick={() => setDiscoveryMode(item)}
              onKeyDown={event => { if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
                event.preventDefault(); const next = event.key === "Home" ? "jobs" : event.key === "End" ? "campaigns" : item === "jobs" ? "campaigns" : "jobs";
                setDiscoveryMode(next); document.getElementById(`discovery-mode-${next}`)?.focus();
              } }}>{item === "jobs" ? "找岗位" : "看秋招"}</button>)}
          </div>}

          {mode === "profile" ? (
            <><ProfileWorkspace apiUrl={apiUrl} userId={userId} onProfileChange={loadProfileSummary} /><AccountPrivacy apiUrl={apiUrl} userId={userId} /></>
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
                      {profileSummary.evidenceCount > 0 ? `使用 ${profileSummary.evidenceCount} 条已保存经历` : "尚无可引用的经历"}
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
                    <p>{profileSummary.evidenceCount > 0 ? "开始后，系统会解析岗位要求，并引用已保存的经历。" : "建议先上传简历并核对经历，再开始匹配。"}</p>
                    <button disabled={rawContent.trim().length < 20} onClick={() => void runAnalysis()} type="button">开始匹配</button>
                  </div>
                ) : null}
                {state === "loading" ? <LoadingState /> : null}
                {state === "error" ? <ErrorState message={errorMessage} onRetry={runAnalysis} /> : null}
                {state === "success" && analysis ? (
                  <><JobCorrectionEditor<AnalysisResponse> key={analysis.job.id} apiUrl={apiUrl} userId={userId} jobId={analysis.job.id} onSaved={setAnalysis} />
                  <AnalysisResult
                    analysis={analysis}
                    onPrepareApplication={prepareApplication}
                    preparing={preparingApplication}
                  /></>
                ) : null}
              </section>
            </section>
          ) : mode === "discover" ? (
            discoveryMode === "campaigns" ? <div id="discovery-panel-campaigns" role="tabpanel" aria-labelledby="discovery-mode-campaigns">
              <CampaignWorkspace key={campaignYear} apiUrl={apiUrl} userId={userId}
                initialYear={campaignYear ?? activeGoal?.conditions.graduation_years[0]} onFindJobs={findCampaignJobs} />
            </div> : <div id="discovery-panel-jobs" role="tabpanel" aria-labelledby="discovery-mode-jobs">
            <DiscoveryWorkspace
              candidates={candidates}
              leads={jobLeads}
              runs={discoveryRuns}
              state={discoveryState === "loading" ? "loading" : goalLibraryError ? "error" : discoveryState}
              message={goalLibraryError ? `目标岗位库读取失败：${goalLibraryError}。已保留可用内容。` : discoveryMessage}
              query={discoveryQuery}
              activeGoal={activeGoal}
              requestedGoal={trackingGoal}
              onTrackApplication={trackApplication}
              trackingApplication={preparingApplication}
              goalLibrary={mergedGoalLibrary}
              candidatesLoaded={candidatesLoaded}
              leadsLoaded={leadsLoaded}
              libraryLoading={goalLibraryLoading}
              searchStarting={searchStarting}
              refreshToken={discoveryRefreshToken}
              onGoalChange={chooseGoal}
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
              onQueryChange={(value) => { queryEditedRef.current = true; setDiscoveryQuery(value); }}
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
              onRefresh={retryDiscovery}
              onOpen={openCandidate}
              onPasteJD={(leadId) => openManualJD(leadId)}
              onUpdate={updateCandidate}
              onCheckAvailability={checkJobAvailability}
            />
            </div>
          ) : (
            <ApplicationBoard
              applications={applications}
              focusedApplicationId={focusedApplicationId}
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
          description={resumeAdvancedOpen ? "这些资料只在准备申请时使用。" : "上传后先核对脱敏预览，确认后再解析经历。"}
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
          description="粘贴完整的岗位描述，系统会解析要求并与你已保存的经历进行匹配。"
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
              <span>{profileSummary.evidenceCount > 0 ? `将使用 ${profileSummary.evidenceCount} 条已保存经历` : "尚无已保存经历，匹配结果可能信息不足"}</span>
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
  });
  const [educations, setEducations] = useState<EducationRecord[]>([]);
  const [educationComplete, setEducationComplete] = useState(false);
  const [educationTouched, setEducationTouched] = useState(false);
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
        setEducations(profile.educations ?? []);
        setEducationComplete(profile.education_history_complete ?? false);
        setEducationTouched(false);
        setProfileForm({
          displayName: profile.display_name ?? "",
          graduationYear: profile.graduation_year?.toString() ?? "",
          degree: profile.degree ?? "",
          major: profile.major ?? "",
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
          ...(educations.length || educationTouched || educationComplete ? {
            educations,
            education_history_complete: educationComplete,
          } : {
          graduation_year: graduationYear ? Number(graduationYear) : null,
          degree: profileForm.degree.trim() || null,
          major: profileForm.major.trim() || null,
          }),
        }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const savedProfile = (await response.json()) as ProfileRecord;
      setEducations(savedProfile.educations ?? []);
      setEducationComplete(savedProfile.education_history_complete ?? false);
      setState("ready");
      setMessage("简历资料已保存。下一次岗位分析会使用这份资料。");
      onProfileChange?.();
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "简历资料保存失败。");
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

  async function keepEvidenceValues(item: EvidenceRecord) {
    setSavingEvidence(true);
    try {
      const response = await fetch(`${apiUrl}/api/evidence/${item.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({ keep_current: true }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const saved = await response.json() as EvidenceRecord;
      setEvidence(current => current.map(record => record.id === saved.id ? saved : record));
      setMessage("已保留当前经历值。");
      onProfileChange?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败。");
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

  return (
    <section className="profile-layout">
      <aside className="profile-identity-panel">
        <div className="section-kicker">基本信息</div>
        <h2>简历基本资料</h2>
        <p className="profile-panel-note">按每段教育经历核对学历、专业和毕业年份，用于判断招聘资格。修改后需重新分析岗位。</p>

        <div className="profile-form-grid">
          <label>
            <span>姓名 / 显示名</span>
            <input
              value={profileForm.displayName}
              onChange={(event) => setProfileForm((current) => ({ ...current, displayName: event.target.value }))}
              placeholder="例如：王永峥"
            />
          </label>
          {!educations.length && !educationTouched && !educationComplete ? <>
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
          </> : null}
        </div>

        <EducationEditor records={educations} complete={educationComplete} disabled={state === "loading" || state === "saving"}
          onChange={records => { setEducations(records); setEducationTouched(true); }}
          onCompleteChange={value => { setEducationComplete(value); setEducationTouched(true); }} />

        <button className="profile-save-button" disabled={state === "loading" || state === "saving"} onClick={saveProfile} type="button">
          {state === "saving" ? "正在保存…" : "保存简历资料 ↗"}
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
        <p className="profile-section-note">上传简历并确认脱敏预览后，系统会把项目和工作经历解析到这里。请核对事实；岗位匹配只会引用你保留的内容。</p>

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
        {state === "loading" ? <div className="profile-empty">正在取回简历资料与经历…</div> : null}
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
                <FactDifferences provenance={item.provenance} current={item} disabled={savingEvidence}
                  onKeep={() => void keepEvidenceValues(item)} />
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
  mode = "entries",
  leads,
  onExpanded,
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
  mode?: "entries" | "composer";
  leads: JobLeadItem[];
  onExpanded: () => void;
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
  const [expanding, setExpanding] = useState<string | null>(null);
  const [expandMessage, setExpandMessage] = useState("");
  async function expand(leadId: string) {
    setExpanding(leadId); setExpandMessage("");
    try {
      const response = await fetch(`${apiUrl}/api/discovery/leads/${leadId}/expand`, { method: "POST", headers: { "X-User-ID": userId } });
      if (!response.ok) throw new Error(await readError(response));
      const found = await response.json() as JobLeadItem[];
      setExpandMessage(found.length ? `找到 ${found.length} 个具体岗位链接，已加入岗位列表。` : "本次未读取到具体职位链接，原入口已保留，可打开官网查看。");
      onExpanded();
    } catch (error) { setExpandMessage(error instanceof Error ? error.message : "暂时无法读取入口"); }
    finally { setExpanding(null); }
  }
  const [filter, setFilter] = useState<LeadQueueFilter>("all");
  const actionableStatuses = new Set<JobLeadStatus>(["NEW", "VERIFYING", "DEFERRED", "NEEDS_BROWSER", "NEEDS_USER", "FAILED"]);
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
          <h2>{mode === "composer" ? "添加岗位链接" : "已找到的招聘页面"}</h2>
          <p>{mode === "composer" ? "保存你找到的岗位链接，后续可继续提取正文和核验。" : "招聘首页、职位列表及补充线索，不计入岗位数量。"}</p>
        </div>
        {mode === "entries" && <span className="job-lead-counter">{leads.length} 个页面</span>}
      </summary>

      {expandMessage && <p role="status">{expandMessage}</p>}
      {mode === "composer" && <div className="job-lead-composer">
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

      }
      {mode === "entries" && <>
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
        <span className="job-lead-boundary">具体岗位会显示在岗位列表</span>
      </div>

      {filteredLeads.length > 0 ? (
        <div className="job-lead-list">
          {filteredLeads.map((lead) => {
            const canVerify = lead.status === "NEW" || lead.status === "FAILED" || lead.status === "DEFERRED";
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
                  <button type="button" disabled={expanding !== null} onClick={() => void expand(lead.id)}>{expanding === lead.id ? "正在找具体职位…" : "继续寻找职位"}</button>
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
      </>}
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
  activeGoal,
  requestedGoal,
  onTrackApplication,
  trackingApplication,
  goalLibrary,
  candidatesLoaded,
  leadsLoaded,
  libraryLoading,
  searchStarting,
  refreshToken,
  onGoalChange,
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
  activeGoal: SearchGoal | null;
  requestedGoal: SearchGoal | null;
  onTrackApplication: (jobId: string) => Promise<boolean>;
  trackingApplication: boolean;
  goalLibrary: GoalLibrary | null;
  candidatesLoaded: boolean;
  leadsLoaded: boolean;
  libraryLoading: boolean;
  searchStarting: boolean;
  refreshToken: number;
  onGoalChange: (goal: SearchGoal | null) => void;
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
  onRun: (goal: SearchGoal, continueCompanyId?: string) => void;
  onManualRun: () => void;
  onSubmitLead: () => void;
  onVerifyLead: (leadId: string) => void;
  onBrowserLead: (leadId: string) => void;
  onRefresh: () => void;
  onOpen: (jobId: string) => void;
  onPasteJD: (leadId?: string) => void;
  onUpdate: (candidateId: string, status: CandidateStatus) => Promise<boolean>;
  onCheckAvailability: (jobId: string) => void;
}) {
  const [reviewStarting, setReviewStarting] = useState(false);
  const [reviewError, setReviewError] = useState("");
  const [discoveryStarting, setDiscoveryStarting] = useState(false);
  const [discoveryError, setDiscoveryError] = useState("");
  const [newRequest, setNewRequest] = useState(false);
  async function startCompanyDiscovery() {
    if (!activeGoal) return;
    setDiscoveryStarting(true); setDiscoveryError("");
    try {
      const response = await fetch(`${apiUrl}/api/discovery/goals/${activeGoal.id}/discover`, {
        method: "POST", headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({ expected_version: activeGoal.version }),
      });
      if (!response.ok) throw new Error(await readError(response));
      onRefresh();
    } catch (error) { setDiscoveryError(error instanceof Error ? error.message : "公司发现启动失败"); }
    finally { setDiscoveryStarting(false); }
  }
  async function startBodyReview() {
    if (!activeGoal) return;
    setReviewStarting(true); setReviewError("");
    try {
      const response = await fetch(`${apiUrl}/api/discovery/goals/${activeGoal.id}/review`, {
        method: "POST", headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({ expected_version: activeGoal.version }),
      });
      if (!response.ok) throw new Error(await readError(response));
      onRefresh();
    } catch (error) { setReviewError(error instanceof Error ? error.message : "复核启动失败"); }
    finally { setReviewStarting(false); }
  }
  const previousGoalRun = activeGoal ? runs.find(run => run.search_goal_id === activeGoal.id) : undefined;
  const searchBusy = searchStarting || runs.some(run => run.status === "RUNNING" && run.search_goal_id === activeGoal?.id);
  const latestRun = activeGoal ? runs.find(run => run.search_goal_id === activeGoal.id && run.search_goal_version === activeGoal.version) : newRequest ? undefined : runs[0];
  const latestMatches = activeGoal ? goalLibrary?.result_matches ?? [] : latestRun?.result_matches ?? [];
  const filterLabels: Record<string, string> = { locations: "地点", preferred_locations: "优先地点", excluded_locations: "排除地点", roles: "方向", excluded_roles: "排除方向", job_types: "招聘类型", excluded_job_types: "排除类型", graduation_years: "届别", keywords: "关键词", preferred_keywords: "优先关键词", pending_conditions: "需进一步核实" };
  const knownJobUrls = new Set(candidates.map(c => c.job.source_url));
  const scopedLeads = (activeGoal ? leads.filter(lead => goalLibrary?.lead_ids.includes(lead.id)) : leads)
    .filter(lead => lead.job_posting_id || !knownJobUrls.has(lead.normalized_url || lead.source_url));
  const currentLeads = scopedLeads.filter((lead, index, all) =>
    (!activeGoal || Boolean(latestRun))
    &&
    (!latestRun || lead.discovery_run_id === latestRun.id)
    && all.findIndex((other) => (other.normalized_url || other.source_url) === (lead.normalized_url || lead.source_url)
      && (!latestRun || other.discovery_run_id === latestRun.id)) === index);
  const entryUrls = new Set<string>();
  const recruitmentEntries = (activeGoal ? scopedLeads : latestRun ? currentLeads : []).filter(lead => {
    const url = lead.normalized_url || lead.source_url;
    if (lead.job_posting_id || lead.discovery_kind === "job" || lead.selection_status === "IGNORED" || entryUrls.has(url)) return false;
    entryUrls.add(url);
    return true;
  });
  const resumableCompanies = goalLibrary?.company_progress?.filter(item => item.can_continue) || [];
  const pendingCount = currentLeads.filter((lead) => !lead.job_posting_id && lead.discovery_kind === "job" && lead.status !== "CLOSED").length;
  const entryCount = currentLeads.filter((lead) => !lead.job_posting_id && lead.discovery_kind !== "job").length;
  const libraryPendingCount = scopedLeads.filter((lead, index, all) => !lead.job_posting_id && lead.discovery_kind === "job" && lead.status !== "CLOSED"
    && all.findIndex(other => (other.normalized_url || other.source_url) === (lead.normalized_url || lead.source_url)) === index).length;
  return (
    <section className="discovery-shell">
      <div className="discovery-control-panel">
        <SearchGoalControls requestedGoal={requestedGoal} apiUrl={apiUrl} userId={userId} query={query}
          historyContent={<DiscoveryRunHistory runs={runs} />}
          historyDates={Object.fromEntries([...runs].reverse().filter(run => run.search_goal_id).map(run => [run.search_goal_id!, run.started_at]))}
          extraTools={<>
            <button type="button" onClick={() => onPasteJD()}>粘贴岗位 JD</button>
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
      <JobLeadQueue mode="composer"
        onExpanded={onRefresh}
        leads={[]}
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
          </>}
          currentLibrary={goalLibrary}
          refreshToken={refreshToken} onReload={onRefresh}
          selectedCompanyIds={selectedCompanyIds} searching={searchBusy}
          onQueryChange={onQueryChange} onGoalChange={goal => { setNewRequest(!goal); onGoalChange(goal); }} onSearch={onRun} />
        {!activeGoal && latestRun?.filter_conditions && <div className="discovery-message" aria-label="本次筛选条件">
          <strong>本次搜索采用的条件</strong>
          <p>{Object.entries(latestRun.filter_conditions).filter(([, values]) => values.length).map(([key, values]) => `${filterLabels[key] || key}：${values.join("、")}`).join("；") || "未识别出可直接筛选的条件"}</p>
          <small>对应搜索：{latestRun.search_query}。修改上方描述后重新搜索即可调整。</small>
        </div>}

      </div>

      {(latestRun || activeGoal || (!newRequest && message)) && <SearchActivity
        key={activeGoal ? `${activeGoal.id}:${activeGoal.version}` : latestRun?.id || "search"}
        summary={latestRun ? <SearchProgress status={latestRun.status} startedAt={latestRun.started_at} finishedAt={latestRun.finished_at}
          verified={latestRun.result_matches.length} unread={pendingCount} reconnecting={message.includes("自动重连")} />
          : <p className="search-idle-status" role="status">{activeGoal ? `${previousGoalRun ? "条件已更新，尚未按当前条件搜索。" : "尚未按当前目标搜索。"}下方岗位库按已保存条件筛选已有岗位。` : message}</p>}
        continuation={activeGoal && resumableCompanies.length > 0 ? <>{resumableCompanies.map(progress => <article key={progress.source_id}>
          <div><strong>{progress.company}</strong><span>已检查 {progress.checked_count} 个岗位{progress.remaining_count ? ` · 至少 ${progress.remaining_count} 个线索待检查` : progress.status === "failed" ? " · 查询失败，可重试" : " · 官网尚未查完"}</span></div>
          <button type="button" disabled={searchBusy} onClick={() => onRun(activeGoal, progress.source_id)}>{progress.status === "failed" ? "重试查询" : "继续查找"}</button>
        </article>)}</> : undefined}>
        {latestRun && <div className="search-round-details" aria-label="本轮详细统计">
          <strong>本轮搜索</strong>
          <p>{latestRun.result_matches.length} 个岗位正文已核验 · {pendingCount} 个待核验 · {reviewCounts(latestRun.result_matches).pending} 个岗位条件待确认 · {entryCount} 个招聘页面</p>
          <small>搜索条件是否符合与个人资格匹配分别核对。</small>
        </div>}
        {recruitmentEntries.length > 0 && (
      <JobLeadQueue
        onExpanded={onRefresh}
        leads={recruitmentEntries}
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
        )}
      {latestRun?.agent_trace?.filter((step) => step.tool === "multiround_search").slice(-1).map((step) => (
        <details className="discovery-message" key="search-progress">
          <summary>查看搜索过程</summary>
          <strong>{latestRun.status === "RUNNING" ? step.observation : "本次搜索已结束"}</strong>
          <p>{step.decision}</p>
          {latestRun.analysis_target_count > 0 ? <p>岗位分析：{latestRun.analysis_completed_count}/{latestRun.analysis_target_count} 已完成</p> : null}
          <small>具体岗位发现后即可查看；核验完成后自动更新筛选结果。</small>
        </details>
      ))}
      {goalLibrary && <div className="goal-library-summary" role="status" aria-label="岗位库统计">
        <strong>已核验 {goalLibrary.result_matches.length} 个岗位 · 待核实 {reviewCounts(goalLibrary.result_matches).pending} 个 · 明确不符 {goalLibrary.counts.excluded || 0} 个（其中 {goalLibrary.counts.closed || 0} 个已关闭）</strong>
        <p>按当前目标筛选全部已保存岗位；另有 {libraryPendingCount} 个岗位链接待核验。</p>
        {goalLibrary.review_queue && <div className="body-review-queue" aria-label="正文复核进度">
          <strong>{({ idle: "正文复核", queued: "正文复核排队中", running: "正在复核已有正文", completed: "本批正文复核完成", blocked: "部分正文需要处理", failed: "正文复核暂停" } as Record<string, string>)[goalLibrary.review_queue.status] || "正文复核"}</strong>
          {goalLibrary.review_queue.lanes ? <>
            <p>岗位判断：等待 {goalLibrary.review_queue.lanes.source.waiting} 个 · 稍后重试 {goalLibrary.review_queue.lanes.source.cooldown} 个 · 多次失败 {goalLibrary.review_queue.lanes.source.blocked} 个</p>
            <p>任职条件补全：等待 {goalLibrary.review_queue.lanes.qualifications.waiting} 个 · 稍后重试 {goalLibrary.review_queue.lanes.qualifications.cooldown} 个 · 多次失败 {goalLibrary.review_queue.lanes.qualifications.blocked} 个</p>
            <small>优先完成岗位判断和到期重试，任职条件在后台逐步补全。使用已保存的正文，无需重复搜索；原文缺失的信息仍保留待核实。</small>
          </> : <p>已完成理解 {goalLibrary.review_queue.completed} 个 · 等待 {goalLibrary.review_queue.waiting} 个 · 稍后重试 {goalLibrary.review_queue.cooldown} 个 · 多次失败 {goalLibrary.review_queue.blocked} 个</p>}
          <button type="button" disabled={reviewStarting || !goalLibrary.review_queue.enabled || ["queued", "running"].includes(goalLibrary.review_queue.status) || !goalLibrary.review_queue.remaining} onClick={() => void startBodyReview()}>{reviewStarting ? "正在启动…" : goalLibrary.review_queue.blocked ? "重试正文复核" : "复核已有正文"}</button>
          {!goalLibrary.review_queue.enabled && <p>需先配置 AI 原文理解。</p>}
          {(reviewError || goalLibrary.review_queue.error) && <p role="alert">{reviewError || goalLibrary.review_queue.error}</p>}
        </div>}
        {goalLibrary.latest_run_id && <details><summary>{latestRun?.status === "RUNNING" ? "本轮更新中" : "最近一轮更新"}：新增 {goalLibrary.updates.filter(u => u.kind === "new").length} · 变更 {goalLibrary.updates.filter(u => u.kind === "changed").length} · 关闭 {goalLibrary.updates.filter(u => u.kind === "closed").length}</summary>
          {goalLibrary.updates.map(u => <p key={`${u.kind}:${u.job_posting_id}`}>{({new: "新增", changed: "变更", closed: "关闭"})[u.kind]} · {u.company || "公司待确认"} · {u.title}</p>)}
        </details>}
      </div>}
      {goalLibrary?.company_discovery_queue && !activeGoal?.company_ids?.length && <div className="body-review-queue" aria-label="公司发现进度">
        <strong>发现更多公司 · {({ idle: "待启动", queued: "等待继续", running: "正在处理", completed: "本批完成", blocked: "部分来源待处理", superseded: "目标已更新" } as Record<string, string>)[goalLibrary.company_discovery_queue.status] || "已保存进度"}</strong>
        <p>已处理查询 {goalLibrary.company_discovery_queue.queries_completed}/{goalLibrary.company_discovery_queue.queries_total} · 已保存线索 {goalLibrary.company_discovery_queue.links_saved} 条 · 已核验公司 {goalLibrary.company_discovery_queue.companies_verified} 家 · 待核验 {goalLibrary.company_discovery_queue.companies_pending} 家</p>
        <small>当前步骤：{({ search: "搜索公司线索", extract: "从来源提取公司", verify: "核验官方招聘入口", done: "已完成" } as Record<string, string>)[goalLibrary.company_discovery_queue.stage]}。关闭页面后，后端运行时仍会继续；新官网会用于后续岗位搜索。</small>
        {goalLibrary.company_discovery_queue.status === "queued" && goalLibrary.company_discovery_queue.next_run_at && <small>下次自动续接：{formatDate(goalLibrary.company_discovery_queue.next_run_at)}</small>}
        <button type="button" disabled={discoveryStarting || !goalLibrary.company_discovery_queue.enabled || ["queued", "running"].includes(goalLibrary.company_discovery_queue.status)} onClick={() => void startCompanyDiscovery()}>{discoveryStarting ? "正在启动…" : goalLibrary.company_discovery_queue.status === "blocked" ? "继续核验公司" : "发现更多公司"}</button>
        {(discoveryError || goalLibrary.company_discovery_queue.error) && <p role="status">{discoveryError || goalLibrary.company_discovery_queue.error}</p>}
      </div>}
      <CompanyDiscoveryPanel apiUrl={apiUrl} userId={userId} sources={goalLibrary?.company_discovery}
        refreshToken={refreshToken} onChanged={onRefresh} />
      {activeGoal && Boolean(goalLibrary?.company_progress?.length) && <details className="company-search-progress" aria-label="官网查询进度">
        <summary>官网查询进度 · 共 {goalLibrary!.company_progress!.length} 家 · {goalLibrary!.company_progress!.filter(item => item.status !== "not_checked").length} 家已尝试 · {goalLibrary!.company_progress!.filter(item => item.status === "not_checked").length} 家待查询</summary>
        <p>分批查询，每家公司本轮最多检查 3 个岗位，待核实、不符合和读取失败也计入。剩余线索会保留，点击“继续查找”接着处理。补搜无结果不代表官网没有岗位。</p>
        <button type="button" disabled={state === "loading" || runs.some(run => run.status === "RUNNING" && run.search_goal_id === activeGoal.id)} onClick={() => onRun(activeGoal)}>继续扩大搜索</button>
        <div className="company-search-cards">{goalLibrary!.company_progress!.map(progress => <article key={progress.source_id}>
          <strong>{progress.company}</strong>
          <span>{progress.strategy === "web_search" && progress.status === "paused" ? "已补搜，官网未查全" : ({ not_checked: "尚未查询", running: "正在查询", paused: "未查完，可能还有更多", completed: "当前条件与关键词已查完", failed: "查询失败，进度已保留", stale: "查询进度已过期，请更新搜索" })[progress.status]}</span>
          {progress.status !== "not_checked" && <small>已检查 {progress.checked_count} 个岗位 · {progress.matched_count} 个搜索条件已确认 · {progress.strategy === "web_search" ? `已尝试 ${progress.search_attempts || 0} 次官网补搜` : `已检查 ${progress.pages_checked} 页`}</small>}
          {Boolean(progress.pending_count || progress.remaining_count) && <small>{progress.pending_count || 0} 个已交给核验 · 至少还有 {progress.remaining_count || 0} 个列表线索待检查</small>}
          <div>{progress.can_continue && <button type="button" disabled={state === "loading" || runs.some(run => run.status === "RUNNING" && run.search_goal_id === activeGoal.id)} onClick={() => onRun(activeGoal, progress.source_id)}>{progress.status === "failed" ? "重试查询" : "继续查找"}</button>}
          <a href={progress.official_url} target="_blank" rel="noopener noreferrer">招聘官网 ↗</a></div>
        </article>)}</div>
      </details>}
      </SearchActivity>}

      {state === "error" ? (
        <div className="discovery-empty discovery-error">
          <h3>这次来源同步没有完成。</h3>
          <p>{message || "请确认来源入口可公开访问，或检查后端服务是否正在运行。"}</p>
          <button className="retry-button" onClick={onRefresh} type="button">重试 ↗</button>
        </div>
      ) : null}
      <DiscoveryTable
        onRefresh={onRefresh}
        workspaceId={activeGoal ? `${activeGoal.id}:${activeGoal.version}` : undefined}
        candidatesLoaded={candidatesLoaded}
        leadsLoaded={leadsLoaded}
        libraryLoaded={!activeGoal || Boolean(goalLibrary)}
        refreshing={libraryLoading || state === "loading"}
        loadError={state === "error"}
        searchBusy={searchBusy}
        candidates={candidates} leads={leads} goalLeadIds={activeGoal ? goalLibrary?.lead_ids || [] : undefined}
        goalScoped={Boolean(activeGoal)} onVerifyLead={onVerifyLead} onBrowserLead={onBrowserLead} onPasteJD={onPasteJD} matches={latestMatches} latestRunId={latestRun?.id}
        updatingId={updatingCandidateId} onOpen={onOpen} onUpdate={onUpdate}
        onTrackApplication={onTrackApplication} trackingApplication={trackingApplication}
        onCheckAvailability={onCheckAvailability} checkingId={updatingAvailabilityJobId} updatingLeadId={updatingLeadId}
      />

    </section>
  );
}

function DiscoveryTable({ onTrackApplication, trackingApplication, onRefresh, candidates, leads, goalLeadIds, workspaceId, goalScoped = false, candidatesLoaded, leadsLoaded, libraryLoaded, refreshing, loadError, onVerifyLead, onBrowserLead, onPasteJD, matches, latestRunId, updatingId, onOpen, onUpdate, onCheckAvailability, checkingId, updatingLeadId, searchBusy }: {
  onRefresh: () => void;
  onTrackApplication: (jobId: string) => Promise<boolean>;
  trackingApplication: boolean;
  workspaceId?: string;
  candidatesLoaded: boolean; leadsLoaded: boolean; libraryLoaded: boolean; refreshing: boolean; loadError: boolean; goalLeadIds?: string[];
  searchBusy: boolean;
  leads: JobLeadItem[]; onVerifyLead: (id: string) => void;
  onBrowserLead: (id: string) => void; onPasteJD: (leadId?: string) => void;
  candidates: CandidateItem[]; matches: DiscoveryResultMatch[]; latestRunId?: string;
  goalScoped?: boolean;
  updatingId: string | null; onOpen: (id: string) => void;
  onUpdate: (id: string, status: CandidateStatus) => Promise<boolean>;
  onCheckAvailability: (id: string) => void; checkingId: string | null; updatingLeadId: string | null;
}) {
  const [scope, setScope] = useState("current");
  const [keyword, setKeyword] = useState("");
  const [selected, setSelected] = useState<CandidateItem | null>(null);
  const [detailTab, setDetailTab] = useState<"description" | "evidence">("description");
  const [showOther, setShowOther] = useState(false);
  const [rowLimit, setRowLimit] = useState(30);
  const [leadSelections, setLeadSelections] = useState<Record<string, CandidateStatus>>({});
  const [selectionError, setSelectionError] = useState("");
  const filterKey = `jobflow:job-filters:${userId}:${workspaceId || latestRunId || "new"}`;
  const [hydratedFilters, setHydratedFilters] = useState("");
  const dataReady = hydratedFilters === filterKey && candidatesLoaded && leadsLoaded && (scope !== "current" || libraryLoaded);
  useEffect(() => {
    let saved: Record<string, unknown> = {};
    try { saved = JSON.parse(localStorage.getItem(filterKey) || "{}") || {}; } catch { /* Storage is optional. */ }
    dialog.current?.close(); setSelected(null); setScope("current"); setShowOther(false);
    setKeyword(saved.viewVersion === 3 && typeof saved.keyword === "string" ? saved.keyword : "");
    setRowLimit(30); setHydratedFilters(filterKey);
  }, [filterKey]);
  useEffect(() => {
    if (hydratedFilters !== filterKey) return;
    try { localStorage.setItem(filterKey, JSON.stringify({ viewVersion: 3, keyword })); } catch { /* Storage is optional. */ }
  }, [filterKey, hydratedFilters, keyword]);
  useEffect(() => { setRowLimit(30); }, [scope, keyword, showOther]);
  const [detail, setDetail] = useState<{
    raw_content: string;
    availability_status?: JobAvailabilityStatus;
    recruitment_context?: { status?: string; batch_name?: string; eligibility_text?: string; source_url?: string; checked_at?: string };
  } | null>(null);
  const [result, setResult] = useState<AnalysisResponse | null>(null);
  const [detailError, setDetailError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const matchMap = new Map(matches.map((m) => [m.job_posting_id, m]));
  const filterStatus = (c: CandidateItem) => c.job.availability_status === "CLOSED" || c.pendingLead?.status === "CLOSED" ? "excluded" : c.pendingLead ? "pending" : matchMap.get(c.job_posting_id)?.filter_status ?? "pending";
  const priority = (c: CandidateItem) => filterStatus(c) === "excluded" ? "excluded" : c.pendingLead ? "pending" : reviewStatus(matchMap.get(c.job_posting_id));
  const pending: CandidateItem[] = [];
  const seenUrls = new Set(candidates.map((c) => c.job.source_url));
  for (const lead of leads) {
    if (lead.job_posting_id || lead.discovery_kind !== "job" || seenUrls.has(lead.normalized_url || lead.source_url)) continue;
    if (scope === "current" && (goalScoped ? !goalLeadIds?.includes(lead.id) : !latestRunId || lead.discovery_run_id !== latestRunId)) continue;
    seenUrls.add(lead.normalized_url || lead.source_url);
    pending.push({ id: lead.id, pendingLead: lead, user_id: userId, job_posting_id: lead.id,
      status: leadSelections[lead.id] || lead.selection_status || "DISCOVERED", available_transitions: ["SAVED", "IGNORED"],
      job: { id: lead.id, title: lead.extracted_fields?.title || (lead.title_hint && !/^(?:https?:\/\/)?[a-z0-9.-]+\.[a-z]{2,}\/?$/i.test(lead.title_hint) ? lead.title_hint : "具体岗位（名称待核验）"), company: lead.extracted_fields?.company || lead.company_hint,
        source_url: lead.source_url, locations: lead.extracted_fields?.locations || [], job_type: lead.extracted_fields?.job_type || null, last_verified_at: lead.verified_at },
      analysis: null, created_at: lead.created_at, updated_at: lead.updated_at });
  }
  const allRows = [...candidates, ...pending];
  const selectedCurrent = selected ? allRows.find(c => c.id === selected.id) || selected : null;
  const tier = (c: CandidateItem) => ({ recommended: 0, pending: 1, excluded: 2 })[priority(c)];
  const rowOrder = (c: CandidateItem) => Number(Boolean(c.pendingLead)) * 2 - reviewRelevance(matchMap.get(c.job_posting_id));
  async function updateRow(c: CandidateItem, status: CandidateStatus) {
    setSelectionError("");
    if (!c.pendingLead) {
      if (!(await onUpdate(c.id, status))) setSelectionError("收藏状态更新失败，请重试。");
      return;
    }
    try {
      const response = await fetch(`${apiUrl}/api/discovery/leads/${c.id}/selection`, {
        method: "PATCH", headers: { "Content-Type": "application/json", "X-User-ID": userId }, body: JSON.stringify({ status }),
      });
      if (!response.ok) throw new Error(await readError(response));
      setLeadSelections((old) => ({ ...old, [c.id]: status }));
    } catch (error) { setSelectionError(error instanceof Error ? error.message : "保存失败，请重试"); }
  }
  const rows = allRows.filter((c) =>
    (scope === "ignored" ? c.status === "IGNORED" : c.status !== "IGNORED")
    && (scope !== "current" || ((goalScoped || Boolean(latestRunId)) && (Boolean(c.pendingLead) || matchMap.has(c.job_posting_id))))
    && (showOther || scope === "saved" || scope === "ignored" || filterStatus(c) !== "excluded")
    && (scope !== "saved" || c.status === "SAVED")
    && (!keyword || `${c.job.company ?? ""} ${c.job.title ?? ""}`.toLowerCase().includes(keyword.toLowerCase()))
  ).sort((a, b) => tier(a) - tier(b) || rowOrder(a) - rowOrder(b));
  const companyName = (value?: string | null) => {
    const name = value?.trim().replace(/\s+/g, " ");
    return !name || /^(未知|待确认|公司待确认|尚未识别|unknown|moka|mokahr|北森)$/i.test(name) ? "公司待确认" : name;
  };
  const rowTypes = new Set(rows.map(c => jobTypeShortLabel[c.job.job_type ?? ""] || "未注明"));
  const showJobType = rowTypes.size !== 1 || rowTypes.has("未注明") || rowTypes.has("类型待确认");
  const uniformJobType = !showJobType ? [...rowTypes][0] : null;
  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    setDetail(null); setResult(null); setDetailError("");
    setDetailTab("description");
    dialog.current?.showModal();
    dialog.current?.scrollTo(0, 0);
    if (selected.pendingLead) {
      setDetail({ raw_content: selected.pendingLead.extracted_fields?.raw_content || selected.pendingLead.search_snippet || "暂无搜索摘要。可直接打开原始链接查看，也可以继续核验正文。" });
      return () => controller.abort();
    }
    void (async () => {
      try {
        const [job, analysis] = await Promise.all([
          fetch(`${apiUrl}/api/jobs/${selected.job.id}`, { signal: controller.signal }),
          fetch(`${apiUrl}/api/jobs/${selected.job.id}/analysis`, { headers: { "X-User-ID": userId }, signal: controller.signal }),
        ]);
        if (!job.ok) throw new Error("岗位正文加载失败");
        const body = await job.json();
        const parsed = analysis.ok ? await analysis.json() as AnalysisResponse : null;
        if (!controller.signal.aborted) { setDetail(body); setResult(parsed); }
      } catch (error) {
        if (!controller.signal.aborted) setDetailError(error instanceof Error ? error.message : "加载失败");
      }
    })();
    return () => controller.abort();
  }, [selected]);
  const safeUrl = (url: string | null) => url && /^https?:\/\//i.test(url) ? url : null;
  const selectedMatch = selected ? matchMap.get(selected.job_posting_id) : undefined;
  function selectDetailTab(tab: "description" | "evidence", focus = false) {
    setDetailTab(tab);
    if (focus) dialog.current?.querySelector<HTMLButtonElement>(`#job-detail-tab-${tab}`)?.focus();
  }
  return <section className="job-results" aria-label="岗位列表">
    <div className="job-results-toolbar">
      <div className="job-results-heading"><h2>{scope === "saved" ? "收藏夹" : scope === "ignored" ? "已忽略岗位" : scope === "all" ? "全部候选" : "岗位列表"}</h2>
        {dataReady && <span className="job-result-count" aria-label="岗位数量">{rows.length}</span>}
        <label className="result-scope"><span className="sr-only">岗位范围</span><select value={scope} onChange={e => { setScope(e.target.value); setShowOther(false); }}>
          <option value="current">{goalScoped ? "当前目标" : "本轮搜索"}</option><option value="saved">收藏夹</option><option value="all">全部候选</option><option value="ignored">已忽略</option>
        </select></label>
        {dataReady && uniformJobType && <span className="result-type-summary">{uniformJobType}</span>}
      </div>
      <div className="job-results-tools">
        <label className="results-search"><span className="sr-only">在结果中搜索</span><input type="search" value={keyword} onChange={e => setKeyword(e.target.value)} placeholder="在结果中搜索" /></label>
        <details className="result-options"><summary>查看选项</summary><div>
          <label className="result-checkbox"><input type="checkbox" checked={showOther} onChange={e => setShowOther(e.target.checked)} />显示不符或已关闭的岗位</label>
        </div></details>
        <button type="button" className="quiet-button" onClick={onRefresh} disabled={refreshing}>{refreshing ? "更新中…" : "刷新"}</button>
      </div>
    </div>
    {selectionError && <p role="alert">{selectionError}</p>}
    {!dataReady && <p className="results-notice" role="status">{loadError ? "岗位读取失败，请刷新重试。" : "正在读取岗位…"}</p>}
    <div className="job-list-scroll" id="discovery-jobs"><table className={`job-list${showJobType ? "" : " job-list-uniform-type"}`}>
      <colgroup><col className="company-column"/><col className="title-column"/><col className="location-column"/>{showJobType && <col className="type-column"/>}<col className="advice-column"/><col className="website-column"/></colgroup>
      <thead><tr><th scope="col">公司</th><th scope="col">岗位名称</th><th scope="col">工作地点</th>{showJobType && <th scope="col">招聘类型</th>}<th scope="col">查看建议</th><th scope="col">原始页面</th></tr></thead>
      <tbody>{dataReady && rows.slice(0, rowLimit).map(c => {
        const advice = jobReviewSummary(matchMap.get(c.job_posting_id), {
          closed: c.job.availability_status === "CLOSED" || c.pendingLead?.status === "CLOSED",
          pendingLeadStatus: c.pendingLead?.status,
          missingCompany: companyName(c.job.company) === "公司待确认",
          missingLocation: !c.job.locations?.length,
        });
        const websiteUrl = safeUrl(c.job.source_url);
        return <tr key={c.id} data-filter-status={filterStatus(c)} data-review-status={priority(c)} onClick={() => setSelected(c)}>
        <td data-label="公司" className="job-company">{companyName(c.job.company)}</td>
        <td data-label="岗位名称" className="job-position"><button type="button" className="job-title" onClick={e => { e.stopPropagation(); setSelected(c); }}>{c.job.title || "岗位标题待补全"}</button></td>
        <td data-label="工作地点" className={!c.job.locations?.length ? "job-unknown" : ""}>{c.job.locations?.join("、") || "待核实"}</td>
        {showJobType && <td data-label="招聘类型" className={!c.job.job_type ? "job-unknown" : ""}>{jobTypeShortLabel[c.job.job_type ?? ""] || "未注明"}</td>}
        <td data-label="查看建议" className={`job-advice advice-${advice.tone}`}><span className="job-advice-label">{advice.label}</span><small className="job-advice-reason" title={advice.reason}>{advice.reason}</small></td>
        <td data-label="原始页面" className="job-website-cell">{websiteUrl ? <a className="job-website-link" href={websiteUrl} target="_blank" rel="noopener noreferrer"
          aria-label={`前往 ${c.job.title || "该岗位"} 的原始页面（新标签页）`} onClick={event => event.stopPropagation()}>前往 ↗</a>
          : <span className="job-unknown" aria-label="暂无原始页面链接">—</span>}</td>
      </tr>})}</tbody>
    </table></div>
    {dataReady && !loadError && !rows.length && <div className="job-results-empty">
      <p>{keyword ? "没有找到匹配的公司或岗位。" : searchBusy ? "正在查找岗位，结果会陆续显示。" : scope === "saved" ? "还没有收藏岗位。" : scope === "ignored" ? "暂无已忽略的岗位。" : "暂无可展示的岗位。"}</p>
      {keyword ? <button type="button" onClick={() => setKeyword("")}>清除关键词</button> : scope === "current" && !searchBusy && <small>在上方描述求职需求，开始查找。</small>}
    </div>}
    {dataReady && rows.length > rowLimit && <button type="button" className="load-more-jobs" onClick={() => setRowLimit(n => n + 30)}>显示更多岗位（还有 {rows.length - rowLimit} 个）</button>}
    <dialog ref={dialog} className="jobs-detail" aria-label="岗位详情" onClose={() => setSelected(null)} onClick={(e) => { if (e.target === e.currentTarget) dialog.current?.close(); }}>
      {selected && <><header><div><small>{selected.job.company || "公司待确认"} · {selected.job.locations?.join("、") || "地点待确认"} · {jobTypeShortLabel[selected.job.job_type ?? ""] || "类型未注明"}</small><h2>{selected.job.title || "岗位详情"}</h2></div><button aria-label="关闭岗位详情" onClick={() => dialog.current?.close()}>关闭 ×</button></header>
      <div className="jobs-detail-actions">{safeUrl(selected.job.source_url) && <a href={selected.job.source_url!} target="_blank" rel="noopener noreferrer">打开原始页面 ↗</a>}
        {selectedCurrent && <>
          <span role="status">{candidateStatusLabel[selectedCurrent.status]}</span>
          {selectedCurrent.available_transitions.includes("SAVED") && selectedCurrent.status !== "SAVED" && <button disabled={updatingId === selected.id} onClick={() => void updateRow(selectedCurrent, "SAVED")}>收藏岗位</button>}
        </>}
        {selected.pendingLead ? <>
          {["NEW", "FAILED", "DEFERRED"].includes(selected.pendingLead.status) && <button disabled={updatingLeadId === selected.id} onClick={() => { dialog.current?.close(); onVerifyLead(selected.id); }}>继续核验正文</button>}
          {selected.pendingLead.status === "NEEDS_BROWSER" && <button disabled={updatingLeadId === selected.id} onClick={() => { dialog.current?.close(); onBrowserLead(selected.id); }}>浏览器验证</button>}
          {["NEEDS_BROWSER", "NEEDS_USER", "REJECTED_NON_JOB"].includes(selected.pendingLead.status) && <button onClick={() => { dialog.current?.close(); onPasteJD(selected.id); }}>粘贴 JD 接管</button>}
        </> : <button className="job-detail-primary" onClick={() => { dialog.current?.close(); onOpen(selected.job.id); }}>{result ? "查看匹配结果" : "分析匹配"}</button>}
        {!selected.pendingLead && <button disabled={trackingApplication} onClick={async () => {
          setSelectionError("");
          if (await onTrackApplication(selected.job.id)) dialog.current?.close();
          else setSelectionError("加入申请进度失败，请检查服务后重试。");
        }}>{trackingApplication ? "正在加入…" : selectedCurrent?.status === "CONVERTED" ? "查看申请进度" : "加入申请进度"}</button>}
        {selectedCurrent?.available_transitions.includes("IGNORED") && selectedCurrent.status !== "IGNORED" && <button className="job-detail-secondary" disabled={updatingId === selected.id} onClick={() => void updateRow(selectedCurrent, "IGNORED")}>忽略岗位</button>}
      </div>
      {selectionError && <p role="alert">{selectionError}</p>}
      <JobDetailStatus match={selectedMatch} pendingLeadStatus={selected.pendingLead?.status}
        closed={selected.job.availability_status === "CLOSED" || detail?.availability_status === "CLOSED" || selected.pendingLead?.status === "CLOSED"} />
      <div className="job-detail-tabs" role="tablist" aria-label="岗位详情内容">
        {(["description", "evidence"] as const).map(tab => <button key={tab} type="button" role="tab"
          id={`job-detail-tab-${tab}`} aria-controls={`job-detail-panel-${tab}`} aria-selected={detailTab === tab}
          tabIndex={detailTab === tab ? 0 : -1} onClick={() => selectDetailTab(tab)}
          onKeyDown={event => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            selectDetailTab(event.key === "Home" ? "description" : event.key === "End" ? "evidence" : tab === "description" ? "evidence" : "description", true);
          }}>{tab === "description" ? "岗位描述" : "筛选依据"}</button>)}
      </div>
      {detailTab === "description" ? <div id="job-detail-panel-description" role="tabpanel" aria-labelledby="job-detail-tab-description" tabIndex={0}>
        {detailError ? <p role="alert">{detailError}</p> : !detail ? <p>正在加载岗位正文…</p> :
          <section className="job-detail-description"><h3>{selected.pendingLead ? (selected.pendingLead.extracted_fields?.basis === "screenshot" ? "截图识别正文（可能不完整，待核验）" : selected.pendingLead.extracted_fields?.raw_content ? "已读取的页面正文（待核验）" : "搜索摘要（未经正文核验）") : "岗位原文"}</h3><JobDescription content={detail.raw_content}/></section>}
      </div> : <div id="job-detail-panel-evidence" role="tabpanel" aria-labelledby="job-detail-tab-evidence" tabIndex={0}>
        {selected.pendingLead ? <p className="job-detail-note">正文尚未核验，完成核验后可查看筛选依据。</p> : <>
          <JobDetailReview match={selectedMatch} />
          <button className="job-detail-availability" disabled={checkingId === selected.job.id} onClick={() => onCheckAvailability(selected.job.id)}>{checkingId === selected.job.id ? "正在检查…" : "检查开放状态"}</button>
        </>}
        {detail?.recruitment_context?.status === "verified" && <details className="job-detail-quote" aria-label="关联招聘批次"><summary>关联招聘批次 · {detail.recruitment_context.batch_name}</summary><div>
          <p>{detail.recruitment_context.batch_name}</p>
          {detail.recruitment_context.eligibility_text && <div className="jobs-jd-text">{detail.recruitment_context.eligibility_text}</div>}
          {detail.recruitment_context.checked_at && <small>核验时间：{formatDate(detail.recruitment_context.checked_at)}{Date.now() - Date.parse(detail.recruitment_context.checked_at) > 7 * 86400000 ? "（证据已过期，需重新核验）" : ""}</small>}
          <p>{detail.availability_status === "ACTIVE" ? "已找到开放投递的证据。" : detail.availability_status === "CLOSED" ? "岗位已关闭。" : "已确认岗位所属批次；当前是否开放投递仍待核实。"}</p>
          {safeUrl(detail.recruitment_context.source_url ?? null) && <a href={detail.recruitment_context.source_url} target="_blank" rel="noopener noreferrer">查看批次来源 ↗</a>}
        </div></details>}
        {result && <section><h3>经历匹配</h3>{result.matches.map((m, i) => <details className="job-detail-quote" key={i}><summary>{m.requirement.name}</summary><div><p>{m.explanation}</p>{m.evidence_ids.length > 0 && <small>经历证据：{m.evidence_ids.join("、")}</small>}</div></details>)}</section>}
      </div>}</>}
    </dialog>
  </section>;
}

function JobDetailStatus({ match, pendingLeadStatus, closed }: { match?: DiscoveryResultMatch; pendingLeadStatus?: string; closed: boolean }) {
  const stages = match?.result_status;
  const conflict = match?.personal_requirements?.find(hint => hint.status === "attention");
  const hasConflict = Boolean(conflict || match?.personal_gate_conflict || stages?.personal.state === "conflict");
  const search = closed ? "岗位已关闭" : pendingLeadStatus ? "正文待核验"
    : stages?.analysis.state && stages.analysis.state !== "completed" ? stages.analysis.label
    : stages?.search.label || (match?.filter_status === "matched" ? "符合搜索条件" : match?.filter_status === "excluded" ? "不符搜索条件" : "搜索条件待核对");
  const personal = hasConflict ? conflict?.reason || "个人门槛存在冲突" : stages?.personal.label || "个人资格待核对";
  return <p className="job-detail-status" aria-label="岗位状态"><span>{search}</span>
    {!pendingLeadStatus && <span className={hasConflict ? "job-detail-conflict" : ""}>{personal}</span>}
  </p>;
}

function JobDetailReview({ match }: { match?: DiscoveryResultMatch }) {
  const hints = match?.personal_requirements || [];
  const profileMissing = match?.result_status?.personal.state === "profile_missing";
  // Repeated pending checks can share the same explanation and quote.
  const checks = (match?.checks || []).filter((check, index, all) => all.findIndex(other =>
    other.reason === check.reason && other.status === check.status && JSON.stringify(other.evidence) === JSON.stringify(check.evidence) && other.source_url === check.source_url) === index);
  return <>
    <section aria-label="搜索条件核对"><h3>搜索条件</h3>
      {checks.length ? checks.map((check, index) => <div className="job-detail-check" key={index}>
        <p className={check.status === "excluded" ? "job-detail-conflict" : ""}>{check.reason}</p>
        {!!check.evidence.length && <details className="job-detail-quote"><summary>查看原文依据</summary><div>
          {check.evidence.map((quote, i) => <blockquote key={i}>{quote}</blockquote>)}
        </div></details>}
      </div>) : <p className="job-detail-note">尚未按当前需求完成核对。</p>}
    </section>
    {!!hints.length && <section aria-label="任职要求"><h3>任职要求</h3>
      <p className="job-detail-note">{profileMissing ? "补充个人资料后，可核对以下任职要求。" : "以下为已识别的要求；完整资格与经历匹配可进入岗位分析。"}</p>
      {hints.map((hint, index) => <details className="job-detail-quote job-detail-requirement" key={index}>
        <summary><span className="job-detail-requirement-label">{hint.label}
          {hint.status === "attention" ? <em className="job-detail-conflict">存在冲突</em> : hint.status === "preferred" ? <em>优先项</em> : hint.status === "satisfied" ? <em>已满足</em> : !profileMissing && <em>待核对</em>}
        </span><span className="job-detail-requirement-text">{hint.evidence}</span></summary>
        <div>{!profileMissing && <p>{hint.reason}</p>}<blockquote>{hint.evidence}</blockquote></div>
      </details>)}
    </section>}
  </>;
}

function ResultStages({ match, detailed = false }: { match?: DiscoveryResultMatch; detailed?: boolean }) {
  const stages = match?.result_status;
  if (!stages?.analysis || !stages?.search || !stages?.personal) return null;
  return <div className="jobs-result-stages" aria-label="岗位判断进度">
    {(detailed || stages.analysis.state !== "completed") && <small data-stage="analysis" title={stages.analysis.reason}>{stages.analysis.label}{detailed && `：${stages.analysis.reason}`}</small>}
    {stages.analysis.state !== "reading_required" && <small data-stage="search" className={stages.search.state === "conflict" ? "personal-hint-attention" : ""}>{stages.search.label}</small>}
    <small data-stage="personal" title={stages.personal.reason} className={stages.personal.state === "conflict" ? "personal-hint-attention" : ""}>{stages.personal.label}</small>
    {detailed && <small>{stages.personal.reason}</small>}
  </div>;
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
        : candidate.job.source_url ? "网页来源" : "人工录入岗位";
  const sourceUrl = candidate.job.source_url && /^https?:\/\//i.test(candidate.job.source_url)
    ? candidate.job.source_url : null;
  const needsInformation = Boolean(match?.mismatch_labels.length
    && match.mismatch_labels.every((label) => label.includes("待确认")));
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
      : needsInformation ? "待补全信息" : "待手动分析"
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
          {match ? <span className={`discovery-match-tier discovery-match-tier-${match.match_tier}`}>{match.match_tier === "strict" ? "严格匹配" : needsInformation ? "信息待补全" : "条件有差异"}</span> : null}
          <span className="discovery-status">{candidateStatusLabel[candidate.status]}</span>
        </div>
      </div>
      <div className="discovery-card-body">
        <div>
          <p className="discovery-company">{candidate.job.company ?? "未识别公司"}</p>
          <h3>{sourceUrl
            ? <a href={sourceUrl} target="_blank" rel="noopener noreferrer">{candidate.job.title ?? "未识别岗位"} ↗</a>
            : candidate.job.title ?? "未识别岗位"}</h3>
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
        {sourceUrl ? <a href={sourceUrl} target="_blank" rel="noopener noreferrer">打开原始页面 ↗</a> : <span>未保存原始链接</span>}
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
  const [details, setDetails] = useState<Record<string, DiscoveryRunItem>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const loading = useRef(new Set<string>());
  const [older, setOlder] = useState<DiscoveryRunItem[]>([]);
  const [visibleCount, setVisibleCount] = useState(5);
  const [hasMore, setHasMore] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const allRuns = [...new Map([...older, ...runs].map(run => [run.id, run])).values()]
    .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id));
  async function loadDetails(run: DiscoveryRunItem) {
    if (loading.current.has(run.id) || (details[run.id] && run.status !== "RUNNING")) return;
    loading.current.add(run.id);
    setErrors(old => ({ ...old, [run.id]: "" }));
    try {
      const response = await fetch(`${apiUrl}/api/discovery/runs/${run.id}`, { headers: { "X-User-ID": userId }, cache: "no-store" });
      if (!response.ok) throw new Error(await readError(response));
      const detail = await response.json() as DiscoveryRunItem;
      setDetails(old => ({ ...old, [run.id]: detail }));
    } catch (error) { setErrors(old => ({ ...old, [run.id]: error instanceof Error ? error.message : "搜索过程读取失败" })); }
    finally { loading.current.delete(run.id); }
  }
  async function showMore() {
    if (visibleCount < allRuns.length) { setVisibleCount(count => count + 5); return; }
    setLoadingMore(true); setHistoryError("");
    try {
      const response = await fetch(`${apiUrl}/api/discovery/runs?compact=true&limit=20&offset=${allRuns.length}`, { headers: { "X-User-ID": userId }, cache: "no-store" });
      if (!response.ok) throw new Error(await readError(response));
      const next = await response.json() as DiscoveryRunItem[];
      setOlder(old => [...old, ...next]); setHasMore(next.length === 20);
      setVisibleCount(count => count + 5);
    } catch (error) { setHistoryError(error instanceof Error ? error.message : "历史记录读取失败"); }
    finally { setLoadingMore(false); }
  }
  return (
    <details className="discovery-history">
      <summary className="discovery-history-heading">
        <div>
          <div className="section-kicker">搜索记录</div>
          <h2>执行记录</h2>
        </div>
        <span>{runs.length} 次搜索</span>
      </summary>
      {runs.length === 0 ? (
        <p className="discovery-history-empty">还没有搜索记录。第一次即时搜索后，这里会记录搜索目标、来源数量和核验筛选结果。</p>
      ) : (
        <div className="discovery-history-list">
          {allRuns.slice(0, visibleCount).map((summary) => {
            const run = details[summary.id] || summary;
            return (
            <div className="discovery-history-row" key={run.id}>
              <span className="discovery-history-source">{run.search_query || run.source}</span>
              <strong>{discoveryRunStatusLabel[run.status]}</strong>
              <span>优先查看 {reviewCounts(run.result_matches).recommended}（搜索条件已确认 {reviewCounts(run.result_matches).confirmed}）/ 待核实 {reviewCounts(run.result_matches).pending} / 不符 {reviewCounts(run.result_matches).excluded}</span>
              <time>{formatDate(run.created_at)}</time>
              {run.usage_metrics ? <p className="discovery-run-metrics" aria-label="搜索实际效果">
                首次出结果 {run.usage_metrics.first_result_ms === null ? "尚无" : `${(run.usage_metrics.first_result_ms / 1000).toFixed(1)} 秒`}
                {run.usage_metrics.first_recommended_ms !== undefined ? <>
                  {" · "}首次优先查看（含缓存）{run.usage_metrics.first_recommended_ms === null ? "尚无" : `${(run.usage_metrics.first_recommended_ms / 1000).toFixed(1)} 秒`}
                </> : null}
                {run.usage_metrics.first_fresh_recommended_ms !== undefined ? <>
                  {" · "}本轮新读首次优先查看 {run.usage_metrics.first_fresh_recommended_ms === null ? "尚无" : `${(run.usage_metrics.first_fresh_recommended_ms / 1000).toFixed(1)} 秒`}
                </> : null}
                {run.usage_metrics.first_new_recommended_ms !== undefined ? <>
                  {" · "}首个新推荐岗位 {run.usage_metrics.first_new_recommended_ms === null ? "尚无" : `${(run.usage_metrics.first_new_recommended_ms / 1000).toFixed(1)} 秒`}
                </> : null}
                {" · "}首次全部条件确认（含缓存）{run.usage_metrics.first_useful_ms === null ? "尚无" : `${(run.usage_metrics.first_useful_ms / 1000).toFixed(1)} 秒`}
                {run.usage_metrics.first_fresh_useful_ms !== undefined ? <>
                  {" · "}本轮新读首次全部条件确认 {run.usage_metrics.first_fresh_useful_ms === null ? "尚无" : `${(run.usage_metrics.first_fresh_useful_ms / 1000).toFixed(1)} 秒`}
                </> : null}
                {run.usage_metrics.source_read_attempts !== undefined ? <>
                  {" · "}官网列表读取 {run.usage_metrics.source_read_successes ?? 0}/{run.usage_metrics.source_read_attempts} 家
                  {run.usage_metrics.source_read_success_rate == null ? "（本轮未读取）" : `（${Math.round(run.usage_metrics.source_read_success_rate * 100)}%）`}
                  {" · "}官网续查恢复 {run.usage_metrics.source_retry_recovered ?? 0}/{run.usage_metrics.source_retry_attempts ?? 0} 家
                </> : null}
                {" · "}正文读取 {run.usage_metrics.read_successes}/{run.usage_metrics.read_attempts}
                {run.usage_metrics.read_success_rate === null ? "（本轮未读取）" : `（${Math.round(run.usage_metrics.read_success_rate * 100)}%）`}
                {" · "}复用缓存 {run.usage_metrics.cache_hits}
                {" · "}正文续查恢复 {run.usage_metrics.retry_recovered}/{run.usage_metrics.retry_attempts}
                {run.usage_metrics.new_recommended_jobs !== undefined ? <> · 新增优先查看 {run.usage_metrics.new_recommended_jobs} · 已有岗位转优先查看 {run.usage_metrics.resolved_recommended_jobs ?? 0}</> : null}
                {" · "}新增全部条件确认 {run.usage_metrics.new_effective_jobs}
                {" · "}已有岗位转全部条件确认 {run.usage_metrics.resolved_effective_jobs}
              </p> : null}
              {run.failure_summary ? (
                <p className="discovery-history-warning" title={run.failure_summary}>
                  {run.failure_summary.split("\n").slice(0, 2).join("；")}
                </p>
              ) : null}
              {run.agent_trace?.length ? (
                <details className="discovery-agent-trace" onToggle={event => { if (event.currentTarget.open) void loadDetails(summary); }}>
                  <summary>查看搜索过程{details[run.id] ? ` / ${run.agent_trace.length} 步` : ""}</summary>
                  {errors[run.id] && <p role="alert">{errors[run.id]} <button onClick={() => void loadDetails(summary)}>重试读取过程</button></p>}
                  {run.search_plan ? (
                    <div className="discovery-plan-contract">
                      <div className="discovery-plan-heading">
                        <span>{run.search_plan.version.toUpperCase()}</span>
                        <strong>
                          来源 {run.search_plan.allowed_source_ids.length} · 岗位上限 {run.search_plan.budget.max_results} · 简历匹配按需进行
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
                        {Array.isArray(step.details?.actual_queries) && step.details.actual_queries.length > 0 ? <p>服务商实际查询：{step.details.actual_queries.join("；")}</p> : step.tool === "search_query" ? <p>服务商未返回内部查询明细；上方为本次提交的查询。</p> : null}
                        {step.tool === "search_query" ? <p>新增链接 {String(step.details?.new_links ?? 0)} · 重复 {String(step.details?.duplicate_count ?? 0)} · 新增具体岗位 {String(step.details?.new_details ?? 0)}</p> : null}
                        {typeof step.details?.failure_reason === "string" ? <p>失败原因：{step.details.failure_reason}</p> : null}
                        {step.details?.partial === true ? <p>响应未整体完成，已保留可用链接和原始响应。</p> : null}
                        <p className="discovery-agent-decision">决策：{step.decision}</p>
                      </article>
                    ))}
                  </div>
                </details>
              ) : null}
            </div>
          ); })}
          {(visibleCount < allRuns.length || hasMore) && <button type="button" disabled={loadingMore} onClick={() => void showMore()}>{loadingMore ? "正在读取…" : "查看更多搜索记录"}</button>}
          {historyError && <p role="alert">{historyError}</p>}
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
          <span className="summary-label">下一步</span>
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
          <Fact label="学历及专业条件" value={educationConditionSummary(jd)} />
          <Fact label="届别原文" value={jd.graduation_source_text ?? "未识别"} />
          <Fact label="必备技能" value={compactList(jd.required_skills)} accent />
          <Fact label="加分技能" value={compactList(jd.preferred_skills)} />
          <Fact label="截止时间" value={jd.deadline ?? "原文未明确"} />
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
              <div><strong>{qualificationName(check.field, check.rule_name)}</strong><p>{check.reason}</p>
                {Array.from(new Set(check.jd_evidence?.map((item) => item.source_text))).map((quote) => <p key={quote}>岗位原文：{quote}</p>)}
                {check.education_evidence?.map(item => <p key={item.id}>教育依据（{educationLabels[item.level]}／{item.major_raw ?? "专业未填"}）：{item.source_text}</p>)}
                {check.missing_information.map((item) => <p key={item}>待确认：{item}</p>)}
              </div>
              <span className={`check-word check-word-${check.result}`}>{{ pass: "符合", fail: "不符合", unknown: "待确认" }[check.result]}</span>
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
  focusedApplicationId,
  state,
  message,
  updatingApplicationId,
  onRefresh,
  onTransition,
}: {
  applications: ApplicationItem[];
  focusedApplicationId: string | null;
  state: BoardState;
  message: string;
  updatingApplicationId: string | null;
  onRefresh: () => void;
  onTransition: (applicationId: string, status: ApplicationStatus) => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(focusedApplicationId);
  useEffect(() => { if (focusedApplicationId) setSelectedId(focusedApplicationId); }, [focusedApplicationId]);
  const [activeTool, setActiveTool] = useState<ApplicationTool | null>(null);
  const selected = applications.find((item) => item.id === selectedId) ?? applications[0] ?? null;
  const toolTitle = activeTool === "packet"
    ? "准备并审核申请材料"
    : activeTool === "attempt"
      ? "记录投递过程"
      : activeTool === "assisted"
        ? "浏览器辅助填写"
        : "安排后续跟进";
  const toolDescription = activeTool === "packet"
    ? "冻结本次使用的岗位、简历和回答，确认无误后再批准。"
    : activeTool === "attempt"
      ? "记录官网填写、人工接管和提交回执，不自动替你确认投递。"
      : activeTool === "assisted"
        ? "检查受支持的申请表单；敏感字段和最终提交仍由你确认。"
        : "集中管理面试、补充材料和联系招聘方等后续任务。";

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
          <p>在岗位详情点击“加入申请进度”，即可开始记录投递和后续安排。</p>
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
          <section className="application-next-actions" aria-label="所选申请的后续操作">
            <div className="application-next-heading">
              <div>
                <span>所选申请</span>
                <strong>{selected ? `${selected.job.company ?? "未命名公司"} / ${selected.job.title ?? "未命名岗位"}` : "请选择一条申请"}</strong>
              </div>
              <p>按当前进度选择下一步；每一步都需要你核对后才会继续。</p>
            </div>
            <div className="application-tool-grid">
              <button aria-label="准备申请材料" onClick={() => setActiveTool("packet")} type="button">
                <span>01</span><strong>准备申请材料</strong><small>冻结并审核本次材料</small>
              </button>
              <button aria-label="记录投递过程" onClick={() => setActiveTool("attempt")} type="button">
                <span>02</span><strong>记录投递过程</strong><small>处理阻塞并保存回执</small>
              </button>
              <button aria-label="浏览器辅助填写" onClick={() => setActiveTool("assisted")} type="button">
                <span>03</span><strong>浏览器辅助填写</strong><small>敏感内容仍需确认</small>
              </button>
              <button aria-label="安排后续跟进" onClick={() => setActiveTool("followup")} type="button">
                <span>04</span><strong>安排后续跟进</strong><small>管理面试和待办</small>
              </button>
            </div>
          </section>
          {selected?.status === "PREPARING" && <ManualSubmission key={selected.id} apiUrl={apiUrl} userId={userId} applicationId={selected.id} onSaved={() => { onRefresh(); window.dispatchEvent(new Event("jobflow:tracking-changed")); }} />}
          <TimelinePanel application={selected} />
          <SuggestionPanel application={selected} />
        </>
      ) : null}
      {activeTool ? (
        <ModalShell
          title={toolTitle}
          description={toolDescription}
          onClose={() => setActiveTool(null)}
          wide
        >
          {activeTool === "packet" ? <PacketWorkspace apiUrl={apiUrl} userId={userId} /> : null}
          {activeTool === "attempt" ? <AttemptWorkspace apiUrl={apiUrl} userId={userId} /> : null}
          {activeTool === "assisted" ? <AtsWorkspace apiUrl={apiUrl} userId={userId} /> : null}
          {activeTool === "followup" ? <FollowUpWorkspace apiUrl={apiUrl} userId={userId} initialApplicationId={selected?.id} /> : null}
        </ModalShell>
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
  const portalEvent = [...application.events].reverse().find(event =>
    ["PortalApplicationObserved", "PortalApplicationUnlinked"].includes(event.event_type));
  return (
    <article className={`application-card ${selected ? "application-card-selected" : ""}`} onClick={onSelect}>
      <div className="application-card-topline">
        <span>{application.job.company ?? "未命名公司"}</span>
        <span>{formatDate(application.updated_at)}</span>
      </div>
      <h3>{application.job.title ?? "未命名岗位"}</h3>
      {portalEvent?.event_type === "PortalApplicationObserved" && <p>官网：{String(portalEvent.payload.raw_status || "待确认")} · {formatDate(portalEvent.created_at)}</p>}
      {application.events.some(e => e.event_type === "ManualSubmissionRecorded") && <p>用户确认投递</p>}
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
  if (event.event_type === "PortalApplicationObserved") return `官网状态：${String(event.payload.raw_status || "待确认")}${event.payload.previous_status ? `（原为${String(event.payload.previous_status)}）` : ""}`;
  if (event.event_type === "PortalApplicationUnlinked") return "已解除官网记录关联，历史观察仍保留。";
  if (event.event_type === "ManualSubmissionRecorded") return `用户确认已在官网投递${event.payload.note ? ` · ${String(event.payload.note)}` : ""}`;
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
  const date = parseApiTimestamp(value);
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
  const citationCount = match.evidence_ids.length + (match.education_evidence?.length ?? 0);
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
        {match.requirement.description !== match.requirement.name && <p>{match.requirement.description}</p>}
        <div className="match-explanation"><span className="quote-mark">“</span>{match.explanation}</div>
        {match.item_checks?.some(check => check.evidence_quotes.length > 0) && <details className="fact-differences">
          <summary>查看经历依据与尚缺条件</summary>
          {match.item_checks.map((check, index) => <div key={index}>
            <p>{check.condition_text || check.source_text}：{supportLabel[check.support_level]}</p>
            {check.evidence_quotes.map((quote, i) => <blockquote key={i}>{quote}</blockquote>)}
            {check.unresolved.map((reason, i) => <p key={i}>{reason}</p>)}
          </div>)}
        </details>}
        {match.education_evidence?.map(item => <p key={item.id}>教育依据{item.reviewed ? "（已核对）" : ""}：{item.source_text}</p>)}
      </div>
      <div className="match-status"><span className="match-status-dot" /><strong>{supportLabel[match.support_level]}</strong><small>{citationCount > 0 ? `${citationCount} 条引用` : "需要补充"}</small></div>
    </article>
  );
}

function internshipCopy(jd: AnalysisResponse["structured_jd"]): string {
  const parts: string[] = [];
  if (jd.internship_duration_months !== null) parts.push(`${jd.internship_duration_months} 个月`);
  if (jd.weekly_days !== null) parts.push(`每周 ${jd.weekly_days} 天`);
  return parts.length > 0 ? parts.join(" · ") : "未识别";
}
