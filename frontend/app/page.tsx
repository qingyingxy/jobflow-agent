"use client";

import { useState } from "react";

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
  const [rawContent, setRawContent] = useState(SAMPLE_JD);
  const [company, setCompany] = useState("示例公司");
  const [title, setTitle] = useState("AI 应用开发实习生");
  const [state, setState] = useState<AnalysisState>("empty");
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [demoMessage, setDemoMessage] = useState("");

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

  return (
    <main className="workspace-shell">
      <div className="workspace-orb workspace-orb-acid" />
      <div className="workspace-orb workspace-orb-coral" />

      <header className="workspace-topbar">
        <div className="brand-lockup">
          <span className="brand-mark">JF</span>
          <span className="brand-name">JobFlow Agent</span>
        </div>
        <div className="topbar-trail">
          <span className="topbar-path">岗位分析工作台</span>
          <span className="build-pill"><span className="live-dot" />M07 / LOCAL</span>
        </div>
      </header>

      <section className="workspace-intro">
        <div>
          <p className="eyebrow">CAREER SIGNAL LAB / 02</p>
          <h1>
            先看清岗位，
            <em>再决定</em>
            要不要申请。
          </h1>
        </div>
        <p className="intro-note">
          把一条非结构化 JD 拆成资格、要求和证据。Agent 负责整理与解释，最终决定权留在你手里。
        </p>
      </section>

      <section className="analysis-layout">
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
          {state === "success" && analysis ? <AnalysisResult analysis={analysis} /> : null}
        </section>
      </section>

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

function AnalysisResult({ analysis }: { analysis: AnalysisResponse }) {
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
