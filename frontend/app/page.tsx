"use client";

import { useEffect, useState } from "react";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
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

type WorkspaceMode = "analysis" | "board";
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
  };
  events: ApplicationEvent[];
  created_at: string;
  updated_at: string;
};

type BoardState = "idle" | "loading" | "ready" | "error";

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
  }, [mode]);

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
          <span className="topbar-path">{mode === "analysis" ? "岗位分析工作台" : "申请状态工作台"}</span>
          <span className="build-pill"><span className="live-dot" />M08 / LOCAL</span>
        </div>
      </header>

      <section className="workspace-intro">
        <div>
          <p className="eyebrow">CAREER SIGNAL LAB / {mode === "analysis" ? "02" : "03"}</p>
          {mode === "analysis" ? (
            <h1>
              先看清岗位，
              <em>再决定</em>
              要不要申请。
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
          {mode === "analysis"
            ? "把一条非结构化 JD 拆成资格、要求和证据。Agent 负责整理与解释，最终决定权留在你手里。"
            : "把用户确认过的岗位放进申请流程。每一次状态变化都留下时间线，不自动投递，也不替你做决定。"}
        </p>
      </section>

      {mode === "analysis" ? <section className="analysis-layout">
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
      </section> : (
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
        <span>FastAPI · Next.js · SQLite · Fake model</span>
      </footer>
    </main>
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

function eventDescription(event: ApplicationEvent): string {
  const fromStatus = event.payload.from_status;
  const toStatus = event.payload.to_status;
  if (typeof fromStatus === "string" && typeof toStatus === "string") {
    const from = applicationStatusLabel[fromStatus as ApplicationStatus] ?? fromStatus;
    const to = applicationStatusLabel[toStatus as ApplicationStatus] ?? toStatus;
    return `${from} → ${to}`;
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
