"use client";

import { useEffect, useState } from "react";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:18001";
const userId = "local-user";

const SAMPLE_JD =
  "示例公司招聘 AI 应用开发实习生，负责 RAG 应用开发和评测。工作地点为北京，欢迎计算机相关专业同学。";

type AnalysisState = "empty" | "loading" | "success" | "error";
type SupportLevel = "supported" | "partial" | "unsupported";

type JobRequirement = {
  category: string;
  name: string;
  description: string;
  mandatory: boolean;
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
    last_seen_at?: string | null;
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
};

type DiscoverySourceOption = {
  id: string;
  company: string;
  priority: "A" | "B" | "C";
  search_mode: "dedicated_adapter" | "official_page";
};

const eligibilityLabel: Record<AnalysisResponse["eligibility"]["eligible"], string> = {
  pass: "资格通过",
  fail: "存在硬性风险",
  unknown: "需要确认",
};

const recommendationLabel: Record<AnalysisResponse["score"]["recommendation"], string> = {
  recommended: "值得准备",
  not_recommended: "暂不推荐",
  needs_confirmation: "确认后决定",
  insufficient_data: "信息不足",
};

const supportLabel: Record<SupportLevel, string> = {
  supported: "有证据",
  partial: "部分匹配",
  unsupported: "无证据",
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
  SuggestionCreated: "生成材料建议",
  SuggestionDecisionRecorded: "记录材料决策",
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
  recommended: "建议人工接管",
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
  const [mode, setMode] = useState<WorkspaceMode>("analysis");
  const [rawContent, setRawContent] = useState(SAMPLE_JD);
  const [company, setCompany] = useState("示例公司");
  const [title, setTitle] = useState("AI 应用开发实习生");
  const [state, setState] = useState<AnalysisState>("empty");
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [demoMessage, setDemoMessage] = useState("");
  const [applications, setApplications] = useState<ApplicationItem[]>([]);
  const [boardState, setBoardState] = useState<BoardState>("idle");
  const [boardMessage, setBoardMessage] = useState("");
  const [updatingApplicationId, setUpdatingApplicationId] = useState<string | null>(null);
  const [preparingApplication, setPreparingApplication] = useState(false);
  const [candidates, setCandidates] = useState<CandidateItem[]>([]);
  const [discoveryRuns, setDiscoveryRuns] = useState<DiscoveryRunItem[]>([]);
  const [discoveryState, setDiscoveryState] = useState<DiscoveryState>("idle");
  const [discoveryMessage, setDiscoveryMessage] = useState("");
  const [discoveryQuery, setDiscoveryQuery] = useState("北京 / 上海的 AI Agent、LLM、算法校招岗位");
  const [discoverySources, setDiscoverySources] = useState<DiscoverySourceOption[]>([]);
  const [selectedDiscoveryCompanyIds, setSelectedDiscoveryCompanyIds] = useState<string[]>(["bytedance"]);
  const [discoverySourceUrl, setDiscoverySourceUrl] = useState("");
  const [discoveryCompany, setDiscoveryCompany] = useState("");
  const [updatingCandidateId, setUpdatingCandidateId] = useState<string | null>(null);

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

  async function loadDiscoveryData(options: { quiet?: boolean } = {}) {
    if (!options.quiet) setDiscoveryState("loading");
    try {
      const [candidateResponse, runResponse, sourceResponse] = await Promise.all([
        fetch(`${apiUrl}/api/candidates`, {
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
      if (!runResponse.ok) throw new Error(await readError(runResponse));
      if (!sourceResponse.ok) throw new Error(await readError(sourceResponse));
      setCandidates((await candidateResponse.json()) as CandidateItem[]);
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
    if (selectedDiscoveryCompanyIds.length === 0) {
      setDiscoveryState("error");
      setDiscoveryMessage("请至少选择一家目标公司。");
      return;
    }
    setDiscoveryState("loading");
    setDiscoveryMessage(`正在扫描选中的 ${selectedDiscoveryCompanyIds.length} 家公司，先抓取岗位事实…`);
    try {
      const response = await fetch(`${apiUrl}/api/discovery/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({
          query: discoveryQuery.trim(),
          company_ids: selectedDiscoveryCompanyIds,
        }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const run = (await response.json()) as DiscoveryRunItem;
      setDiscoveryRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]);
      void pollDiscoveryRun(run.id);
    } catch (error) {
      setDiscoveryState("error");
      setDiscoveryMessage(error instanceof Error ? error.message : "官方岗位搜索启动失败。");
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
        setDiscoveryMessage(
          run.analysis_target_count > 0
            ? `严格匹配 ${strictCount} 条，自动分析 ${run.analysis_completed_count}/${run.analysis_target_count} 条；拓展候选 ${expandedCount} 条。`
            : run.discovered_count > 0
              ? `已核验 ${run.discovered_count} 条岗位：严格匹配 ${strictCount} 条，拓展候选 ${expandedCount} 条。`
              : "正在读取官方招聘页…",
        );
        if (run.status !== "RUNNING") {
          await loadDiscoveryData({ quiet: true });
          setDiscoveryState(run.status === "FAILED" ? "error" : "ready");
          setDiscoveryMessage(
            run.discovered_count === 0
              ? "官方来源暂未返回可验证岗位，已转入人工接管。你可以直接粘贴一条 JD 继续分析。"
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
    try {
      const response = await fetch(`${apiUrl}/api/jobs/${jobId}`, { cache: "no-store" });
      if (!response.ok) throw new Error(await readError(response));
      const posting = (await response.json()) as {
        raw_content: string;
        company: string | null;
        title: string | null;
      };
      setRawContent(posting.raw_content);
      setCompany(posting.company ?? "");
      setTitle(posting.title ?? "");
      setAnalysis(null);
      setState("empty");
      setErrorMessage("");
      setMode("analysis");
    } catch (error) {
      setDiscoveryMessage(error instanceof Error ? error.message : "岗位详情加载失败。");
    }
  }

  function openManualJD() {
    setRawContent("");
    setCompany("");
    setTitle("");
    setAnalysis(null);
    setState("empty");
    setErrorMessage("");
    setMode("analysis");
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
      const importResponse = await fetch(`${apiUrl}/api/jobs/import-text`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company: company.trim() || null,
          title: title.trim() || null,
          raw_content: rawContent,
        }),
      });
      if (!importResponse.ok) {
        throw new Error(await readError(importResponse));
      }
      const posting = (await importResponse.json()) as { id: string };

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
      setState("success");
    } catch (error) {
      setState("error");
      setErrorMessage(error instanceof Error ? error.message : "分析失败，请稍后重试。");
    }
  }

  function resetSample() {
    setRawContent(SAMPLE_JD);
    setCompany("示例公司");
    setTitle("AI 应用开发实习生");
    setState("empty");
    setAnalysis(null);
    setErrorMessage("");
  }

  async function loadDemoData() {
    setDemoMessage("正在载入本地演示资料…");
    try {
      const profileResponse = await fetch(`${apiUrl}/api/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({
          display_name: "本地演示用户",
          graduation_year: 2027,
          degree: "硕士",
          major: "计算机科学",
          search_preferences: {
            preferred_locations: ["北京"],
            job_types: ["internship"],
          },
        }),
      });
      if (!profileResponse.ok) throw new Error(await readError(profileResponse));

      const evidenceResponse = await fetch(`${apiUrl}/api/evidence`, {
        headers: { "X-User-ID": userId },
        cache: "no-store",
      });
      if (!evidenceResponse.ok) throw new Error(await readError(evidenceResponse));
      const evidence = (await evidenceResponse.json()) as Array<{ source?: string }>;
      if (!evidence.some((item) => item.source === "local_demo_memory_rag")) {
        const createEvidenceResponse = await fetch(`${apiUrl}/api/evidence`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-User-ID": userId },
          body: JSON.stringify({
            type: "project",
            title: "Memory-RAG",
            claim: "在 Memory-RAG 项目中实现 BM25 与向量检索融合，并加入 rerank。",
            skills: ["RAG", "BM25", "Vector Search", "Reranker"],
            source: "local_demo_memory_rag",
          }),
        });
        if (!createEvidenceResponse.ok) throw new Error(await readError(createEvidenceResponse));
      }
      setDemoMessage("演示画像与 Memory-RAG 证据已载入。现在可以开始分析。 ");
    } catch (error) {
      setDemoMessage(error instanceof Error ? error.message : "演示资料载入失败。");
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

  return (
    <main className="workspace-shell">
      <div className="workspace-orb workspace-orb-acid" />
      <div className="workspace-orb workspace-orb-coral" />

      <header className="workspace-topbar">
        <div className="brand-lockup">
          <span className="brand-mark">JF</span>
          <span className="brand-name">JobFlow Agent</span>
        </div>
        <nav className="workspace-nav" aria-label="工作区导航">
          <button
            className={mode === "profile" ? "workspace-nav-active" : ""}
            onClick={() => setMode("profile")}
            type="button"
          >
            我的资料 <span>CV</span>
          </button>
          <button
            className={mode === "discover" ? "workspace-nav-active" : ""}
            onClick={() => setMode("discover")}
            type="button"
          >
            岗位发现 <span>{candidates.filter((item) => item.status === "DISCOVERED").length.toString().padStart(2, "0")}</span>
          </button>
          <button
            className={mode === "analysis" ? "workspace-nav-active" : ""}
            onClick={() => setMode("analysis")}
            type="button"
          >
            岗位分析 <span>01</span>
          </button>
          <button
            className={mode === "board" ? "workspace-nav-active" : ""}
            onClick={() => setMode("board")}
            type="button"
          >
            申请看板 <span>{applications.length.toString().padStart(2, "0")}</span>
          </button>
        </nav>
        <div className="topbar-trail">
          <span className="topbar-path">
            {mode === "profile" ? "画像与证据工作台" : mode === "analysis" ? "岗位分析工作台" : mode === "discover" ? "岗位发现工作台" : "申请状态工作台"}
          </span>
          <span className="build-pill"><span className="live-dot" />M11 / LOCAL</span>
        </div>
      </header>

      <section className="workspace-intro">
        <div>
          <p className="eyebrow">CAREER SIGNAL LAB / {mode === "profile" ? "00" : mode === "discover" ? "01" : mode === "analysis" ? "02" : "03"}</p>
          {mode === "profile" ? (
            <h1>
              先把经历写清楚，
              <em>再让证据说话。</em>
            </h1>
          ) : mode === "analysis" ? (
            <h1>
              先看清岗位，
              <em>再决定</em>
              要不要申请。
            </h1>
          ) : mode === "discover" ? (
            <h1>
              先把机会浮出来，
              <em>再决定</em>
              往哪走。
            </h1>
          ) : (
            <h1>
              申请不是终点，
              <em>下一步</em>
              才是。
            </h1>
          )}
        </div>
        <p className="intro-note">
          {mode === "profile"
            ? "把学历、求职偏好和项目事实整理成可引用证据。系统不会把整份简历直接交给模型。"
            : mode === "discover"
            ? "从登记的公司官方招聘入口即时读取岗位，最多保存 20 条，只自动分析严格匹配中的前 5 条。"
            : mode === "analysis"
            ? "把一条非结构化 JD 拆成资格、要求和证据。Agent 负责整理与解释，最终决定权留在你手里。"
            : "把用户确认过的岗位放进申请流程。每一次状态变化都留下时间线，不自动投递，也不替你做决定。"}
        </p>
      </section>

      {mode === "profile" ? (
        <ProfileWorkspace apiUrl={apiUrl} userId={userId} />
      ) : mode === "analysis" ? <section className="analysis-layout">
        <aside className="intake-panel">
          <div className="section-kicker"><span>01</span> 导入岗位</div>
          <div className="field-pair">
            <label>
              <span>公司（可选）</span>
              <input value={company} onChange={(event) => setCompany(event.target.value)} placeholder="例如：示例公司" />
            </label>
            <label>
              <span>岗位标题（可选）</span>
              <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：AI 应用开发" />
            </label>
          </div>
          <label className="textarea-label">
            <span>岗位原文 / JD</span>
            <textarea
              value={rawContent}
              onChange={(event) => setRawContent(event.target.value)}
              placeholder="粘贴岗位描述，至少 20 个字符"
              rows={13}
            />
          </label>
          <div className="intake-footer">
            <span className="character-count">{rawContent.length} CHARACTERS</span>
            <button className="quiet-button" onClick={resetSample} type="button">恢复样例</button>
          </div>
          <button className="analyze-button" disabled={state === "loading"} onClick={runAnalysis} type="button">
            <span>{state === "loading" ? "正在拆解岗位…" : "开始岗位分析"}</span>
            <span aria-hidden="true">↗</span>
          </button>
          <div className="intake-principle">
            <span className="principle-mark">◎</span>
            <p><strong>Agent suggests · human decides</strong><br />不会自动投递，也不会替你虚构经历。</p>
          </div>
          <div className="demo-loader">
            <button onClick={loadDemoData} type="button">
              <span>LOCAL DEMO DATA</span><strong>载入演示资料 ↗</strong>
            </button>
            <p>{demoMessage || "仅写入 local-user，方便完整演示证据匹配。"}</p>
          </div>
        </aside>

        <section className={`result-panel result-${state}`} aria-live="polite">
          <div className="result-heading">
            <div>
              <div className="section-kicker"><span>02</span> 分析结果</div>
              <p className="result-subtitle">
                {state === "success" && analysis ? `ANALYSIS ${analysis.analysis_id.slice(-8).toUpperCase()}` : "等待一条岗位"}
              </p>
            </div>
            {state === "success" && analysis ? (
              <span className={`eligibility-badge badge-${analysis.eligibility.eligible}`}>
                <span className="badge-dot" />{eligibilityLabel[analysis.eligibility.eligible]}
              </span>
            ) : null}
          </div>

          {state === "empty" ? <EmptyState /> : null}
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
      </section> : mode === "discover" ? (
        <DiscoveryWorkspace
          candidates={candidates}
          runs={discoveryRuns}
          state={discoveryState}
          message={discoveryMessage}
          query={discoveryQuery}
          sources={discoverySources}
          selectedCompanyIds={selectedDiscoveryCompanyIds}
          sourceUrl={discoverySourceUrl}
          company={discoveryCompany}
          updatingCandidateId={updatingCandidateId}
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
          onRun={runDiscovery}
          onManualRun={runManualDiscovery}
          onRefresh={loadDiscoveryData}
          onOpen={openCandidate}
          onPasteJD={openManualJD}
          onUpdate={updateCandidate}
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
        <span>JobFlow Agent / evidence-first job analysis</span>
        <span>FastAPI · Next.js · SQLite · evidence-first</span>
      </footer>
    </main>
  );
}

function ProfileWorkspace({ apiUrl, userId }: { apiUrl: string; userId: string }) {
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
      setMessage(isEditing ? "经历证据已更新。" : "经历证据已添加。" );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "经历证据保存失败。");
    } finally {
      setSavingEvidence(false);
    }
  }

  function editEvidence(item: EvidenceRecord) {
    setEditingEvidenceId(item.id);
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
        <div className="section-kicker"><span>01</span> 个人画像</div>
        <h2>让系统知道，<em>你是谁。</em></h2>
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
          <div className="profile-subheading"><span>SEARCH PREFERENCES</span><small>可选</small></div>
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
            <div className="section-kicker"><span>02</span> 经历证据</div>
            <h2>不要上传整份简历，<em>拆成可验证事实。</em></h2>
          </div>
          <span className="profile-count">{evidence.length.toString().padStart(2, "0")} 条证据</span>
        </div>
        <p className="profile-section-note">每条记录描述一件真实经历。岗位分析时，Agent 只能从这些记录中引用证据，不能凭空补写项目、技术或指标。</p>

        {message ? <div className={`profile-message ${state === "error" ? "profile-message-error" : ""}`}>{message}</div> : null}

        <div className="evidence-composer">
          <div className="evidence-composer-topline">
            <span>{editingEvidenceId ? "EDIT EVIDENCE" : "ADD EVIDENCE"}</span>
            <small>一条事实 · 一个来源</small>
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

        <div className="evidence-list-heading">
          <span>YOUR EVIDENCE LIBRARY</span>
          <button className="profile-refresh" disabled={state === "loading"} onClick={() => void loadProfileData()} type="button">刷新 ↻</button>
        </div>
        {state === "loading" ? <div className="profile-empty">正在取回你的画像与经历…</div> : null}
        {state !== "loading" && evidence.length === 0 ? (
          <div className="profile-empty">
            <strong>还没有经历证据。</strong>
            <p>从简历中逐条添加项目事实，岗位匹配才会有可靠引用。</p>
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

function EmptyState() {
  return (
    <div className="empty-state">
      <div className="empty-index">READY / 00</div>
      <div className="empty-glyph">＋</div>
      <h2>把一条 JD 放进来。</h2>
      <p>系统会先保存岗位事实，再依次完成结构化解析、资格检查、证据匹配和确定性评分。</p>
      <div className="empty-route"><span>INPUT</span><i>→</i><span>PARSE</span><i>→</i><span>VERIFY</span></div>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="loading-state">
      <div className="loading-orbit"><span /></div>
      <p className="loading-label">AGENT PIPELINE RUNNING</p>
      <h2>正在把岗位变成可判断的信号。</h2>
      <div className="loading-steps">
        <span className="loading-step-active">解析 JD</span><i>→</i><span>检查资格</span><i>→</i><span>匹配证据</span><i>→</i><span>计算评分</span>
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
  const isDedicated = source.search_mode === "dedicated_adapter";
  return (
    <label className={`discovery-company-option${selected ? " is-selected" : ""}`}>
      <input
        type="checkbox"
        checked={selected}
        onChange={() => onToggle(source.id)}
      />
      <span>
        <strong>{source.company}</strong>
        <small className={isDedicated ? "is-adapter" : ""}>
          {isDedicated ? "已适配" : "官网尝试"}
        </small>
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
        <span id="discovery-company-label">公司范围</span>
        <strong>{selectedCompanyIds.length > 0 ? `${selectedCompanyIds.length} 家已选` : "至少选择 1 家"}</strong>
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
      <div className="discovery-company-legend" aria-label="来源能力说明">
        <span><i className="legend-adapter" />已适配：直接读取公开职位接口</span>
        <span><i />官网尝试：动态页面可能暂时无结果</span>
      </div>
    </div>
  );
}

function DiscoveryWorkspace({
  candidates,
  runs,
  state,
  message,
  query,
  sources,
  selectedCompanyIds,
  sourceUrl,
  company,
  updatingCandidateId,
  onQueryChange,
  onToggleCompany,
  onSourceUrlChange,
  onCompanyChange,
  onRun,
  onManualRun,
  onRefresh,
  onOpen,
  onPasteJD,
  onUpdate,
}: {
  candidates: CandidateItem[];
  runs: DiscoveryRunItem[];
  state: DiscoveryState;
  message: string;
  query: string;
  sources: DiscoverySourceOption[];
  selectedCompanyIds: string[];
  sourceUrl: string;
  company: string;
  updatingCandidateId: string | null;
  onQueryChange: (value: string) => void;
  onToggleCompany: (sourceId: string) => void;
  onSourceUrlChange: (value: string) => void;
  onCompanyChange: (value: string) => void;
  onRun: () => void;
  onManualRun: () => void;
  onRefresh: () => void;
  onOpen: (jobId: string) => void;
  onPasteJD: () => void;
  onUpdate: (candidateId: string, status: CandidateStatus) => void;
}) {
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
  const needsHumanJD = Boolean(
    latestRun
      && latestRun.status !== "RUNNING"
      && latestRun.discovered_count === 0
      && state !== "loading",
  );
  return (
    <section className="discovery-shell">
      <div className="discovery-control-panel">
        <div className="discovery-control-heading">
          <div>
            <div className="section-kicker"><span>01</span> 即时发现岗位</div>
            <h2>把模糊目标交给 <em>官方来源。</em></h2>
            <p>描述目标后，Agent 会在登记的官方来源中规划工具路线，依次尝试结构化数据、静态页面和专用 Adapter；无法验证时停止生成岗位并请求人工补充 JD。</p>
          </div>
          <span className="discovery-safety-mark">TOOL ROUTING / HUMAN GATE</span>
        </div>
        <DiscoveryCompanyScope
          sources={sources}
          selectedCompanyIds={selectedCompanyIds}
          onToggle={onToggleCompany}
        />
        <div className="discovery-form">
          <label>
            <span>你想找什么</span>
            <textarea
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="例如：北京 / 上海的 AI Agent、LLM、算法校招岗位"
            />
          </label>
          <button
            className="discovery-sync-button"
            onClick={onRun}
            disabled={state === "loading" || selectedCompanyIds.length === 0}
            type="button"
          >
            <span>{state === "loading" ? "搜索中…" : "搜索并分析"}</span>
            <span aria-hidden="true">↗</span>
          </button>
        </div>
        <div className="discovery-principle">
          <span className="principle-mark">◎</span>
          <p><strong>PLAN → ACT → OBSERVE → HUMAN GATE</strong><br />每次工具选择、观察、回退与停止原因都会留痕；只有严格匹配岗位才进入前 5 条分析。</p>
        </div>
        <details className="discovery-advanced">
          <summary>已有具体来源？使用高级入口</summary>
          <div className="discovery-advanced-form">
            <label>
              <span>Greenhouse board URL</span>
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
              指定来源同步 ↗
            </button>
          </div>
        </details>
      </div>

      {message ? <div className="discovery-message">{message}</div> : null}

      {needsHumanJD ? (
        <div className="discovery-human-gate">
          <div>
            <span>HUMAN GATE / MANUAL JD</span>
            <h3>官网没有给出可靠结果，改由你提供岗位事实。</h3>
            <p>粘贴具体岗位描述后，解析、资格判断、证据匹配和评分会从这里继续，不会虚构候选岗位。</p>
          </div>
          <button onClick={onPasteJD} type="button">粘贴 JD 继续分析 <span aria-hidden="true">↗</span></button>
        </div>
      ) : null}

      <div className="discovery-pool-heading">
        <div>
          <div className="section-kicker"><span>02</span> 岗位候选池</div>
          <h2>先看见，<em>再判断。</em></h2>
          <p>公司、地点、招聘类型和岗位方向同时满足才进入严格匹配；自动分析只处理其中排序靠前的 5 条。</p>
        </div>
        <button className="board-refresh" onClick={onRefresh} disabled={state === "loading"} type="button">
          {state === "loading" ? "读取中…" : "刷新候选池 ↻"}
        </button>
      </div>

      {state === "error" ? (
        <div className="discovery-empty discovery-error">
          <span className="empty-index">DISCOVERY / ERROR</span>
          <h3>这次来源同步没有完成。</h3>
          <p>{message || "请确认来源入口可公开访问，或检查后端服务是否正在运行。"}</p>
          <button className="retry-button" onClick={onRefresh} type="button">重试 ↗</button>
        </div>
      ) : null}
      {state === "loading" && currentPoolSize === 0 ? (
        <div className="discovery-empty">
          <span className="empty-index">DISCOVERY / SYNC</span>
          <div className="board-loader" />
          <h3>正在整理公开岗位。</h3>
          <p>读取来源、标准化字段、计算去重指纹，然后才会进入候选池。</p>
        </div>
      ) : null}
      {state !== "error" && state !== "loading" && currentPoolSize === 0 && (!latestRun || latestRun.discovered_count === 0) ? (
        <div className="discovery-empty">
          <span className="empty-index">DISCOVERY / 00</span>
          <div className="empty-glyph">＋</div>
          <h3>{needsHumanJD ? "这次没有可验证的候选岗位。" : "候选池还是空的。"}</h3>
          <p>{needsHumanJD ? "系统已经停止自动生成结果。你可以粘贴具体 JD 继续，也可以调整目标后重新搜索。" : "描述目标后开始即时搜索。岗位进入这里后，你可以先保存、忽略，或者查看自动分析结果。"}</p>
          <button className="discovery-paste-button" onClick={onPasteJD} type="button">粘贴 JD 继续 <span aria-hidden="true">↗</span></button>
        </div>
      ) : null}
      {latestRun && latestRun.status !== "RUNNING" && latestRun.discovered_count > 0 ? (
        <div className="discovery-result-group-heading">
          <div>
            <span>STRICT MATCH</span>
            <h3>严格匹配</h3>
            <p>满足本次选择的公司范围，以及查询中的地点、招聘类型和岗位方向。</p>
          </div>
          <strong>{strictMatches.length.toString().padStart(2, "0")}</strong>
        </div>
      ) : null}

      {latestRun && latestRun.status !== "RUNNING" && latestRun.discovered_count > 0 && strictMatches.length === 0 ? (
        <div className="discovery-no-strict-match">
          <strong>本次严格匹配为 0</strong>
          <span>下方拓展候选是官方真实岗位，但不代表它们满足你的原始条件。</span>
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
              onOpen={() => onOpen(candidate.job.id)}
              onUpdate={(status) => onUpdate(candidate.id, status)}
            />
          ))}
        </div>
      ) : null}

      {latestRun && latestRun.status !== "RUNNING" && latestRun.discovered_count > 0 ? (
        <details className="discovery-expanded-results">
          <summary>
            <span><strong>拓展候选 / {expandedMatches.length.toString().padStart(2, "0")}</strong>真实岗位，但至少一项条件已放宽，默认不自动分析</span>
            <span aria-hidden="true">＋</span>
          </summary>
          {expandedPool.length > 0 ? (
            <div className="discovery-pool">
              {expandedPool.map(({ candidate, match }) => (
                <DiscoveryCard
                  key={candidate.id}
                  candidate={candidate}
                  match={match}
                  updating={updatingCandidateId === candidate.id}
                  onOpen={() => onOpen(candidate.job.id)}
                  onUpdate={(status) => onUpdate(candidate.id, status)}
                />
              ))}
            </div>
          ) : (
            <p className="discovery-expanded-empty">本次没有需要放宽条件的候选。</p>
          )}
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
                onOpen={() => onOpen(candidate.job.id)}
                onUpdate={(status) => onUpdate(candidate.id, status)}
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
                onOpen={() => onOpen(candidate.job.id)}
                onUpdate={(status) => onUpdate(candidate.id, status)}
              />
            ))}
          </div>
        </details>
      ) : null}

      <DiscoveryRunHistory runs={runs} />
    </section>
  );
}

function DiscoveryCard({
  candidate,
  match,
  updating,
  onOpen,
  onUpdate,
}: {
  candidate: CandidateItem;
  match?: DiscoveryResultMatch;
  updating: boolean;
  onOpen: () => void;
  onUpdate: (status: CandidateStatus) => void;
}) {
  const locations = candidate.job.locations ?? [];
  const canSave = candidate.available_transitions.includes("SAVED");
  const canIgnore = candidate.available_transitions.includes("IGNORED");
  const sourceLabel = candidate.job.source_id?.startsWith("bytedance:")
    ? "BYTEDANCE / PUBLIC ADAPTER"
    : candidate.job.source_id?.startsWith("tencent:")
      ? "TENCENT / PUBLIC ADAPTER"
    : candidate.job.source_id?.replace("greenhouse:", "GREENHOUSE / ") ?? "MANUAL IMPORT";
  const analysisLabel = match?.match_tier === "expanded"
    ? candidate.analysis
      ? candidate.analysis.score === null
        ? "已有历史分析 / 信息不足"
        : `已有历史分析 ${Math.round(candidate.analysis.score)}`
      : "待手动分析"
    : candidate.analysis
      ? candidate.analysis.score === null
        ? "分析完成 / 信息不足"
        : `匹配信号 ${Math.round(candidate.analysis.score)}`
      : "待进入分析";
  const openLabel = match?.match_tier === "expanded"
    ? candidate.analysis ? "查看已有分析 ↗" : "手动分析 ↗"
    : candidate.analysis ? "查看分析 ↗" : "进入分析 ↗";
  return (
    <article className={`discovery-card discovery-card-${candidate.status.toLowerCase()} ${match ? `discovery-card-${match.match_tier}` : ""}`}>
      <div className="discovery-card-topline">
        <span>{sourceLabel}</span>
        <div className="discovery-card-signals">
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
          {match?.mismatch_labels.length ? (
            <div className="discovery-mismatch-list" aria-label="条件放宽原因">
              {match.mismatch_labels.map((label) => <span key={label}>{label}</span>)}
            </div>
          ) : null}
        </div>
        <div className="discovery-date">
          <span>LAST SEEN</span>
          <strong>{formatDate(candidate.job.last_seen_at ?? candidate.updated_at)}</strong>
        </div>
      </div>
      <div className="discovery-card-footer">
        <button className="discovery-open" onClick={onOpen} type="button">{openLabel}</button>
        <div className="discovery-secondary-actions">
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
    <section className="discovery-history">
      <div className="discovery-history-heading">
        <div>
          <div className="section-kicker"><span>03</span> 同步记录</div>
          <h2>每次决策，都留下 <em>工具与回退轨迹。</em></h2>
        </div>
        <span>{runs.length.toString().padStart(2, "0")} RUNS</span>
      </div>
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
                  <summary>AGENT TRACE / {run.agent_trace.length.toString().padStart(2, "0")} STEPS</summary>
                  <div className="discovery-agent-trace-list">
                    {run.agent_trace.map((step, index) => (
                      <article className={`discovery-agent-step trace-${step.outcome}`} key={`${run.id}-${index}-${step.tool}`}>
                        <div>
                          <span>{(index + 1).toString().padStart(2, "0")} · {step.phase.toUpperCase()}</span>
                          <strong>{discoveryTraceOutcomeLabel[step.outcome] ?? step.outcome}</strong>
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
    </section>
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
  const scoreText = analysis.score.score === null ? "—" : `${Math.round(analysis.score.score)}`;

  return (
    <div className="analysis-result">
      <div className="signal-summary">
        <div className="score-block">
          <span className="summary-label">MATCH SIGNAL</span>
          <strong>{scoreText}</strong>
          <span className="score-denominator">/ 100</span>
        </div>
        <div className="recommendation-block">
          <span className="summary-label">NEXT DECISION</span>
          <strong>{recommendationLabel[analysis.score.recommendation]}</strong>
          <span>{analysis.job.company ?? jd.company ?? "未识别公司"} · {analysis.job.title ?? jd.title ?? "未识别岗位"}</span>
        </div>
        <div className="decision-action">
          <span className="summary-label">HUMAN GATE</span>
          <button onClick={onPrepareApplication} disabled={preparing} type="button">
            {preparing ? "正在创建…" : "准备申请 ↗"}
          </button>
          <small>确认后才会进入申请看板</small>
        </div>
        <div className="signal-stamp">{analysis.score.score === null ? "DATA\nGAP" : analysis.score.recommendation === "recommended" ? "GOOD\nSIGNAL" : "REVIEW\nFIRST"}</div>
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
            {analysis.matches.map((match) => <MatchRow key={`${match.requirement.category}-${match.requirement.name}`} match={match} />)}
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
        <div className="match-title-line"><strong>{match.requirement.name}</strong><span className="match-category">{groupLabel[match.requirement.category] ?? match.requirement.category}</span></div>
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
