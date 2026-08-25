"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type PacketStatus = "DRAFT" | "NEEDS_REVIEW" | "APPROVED" | "SUPERSEDED";
type Sensitivity = "standard" | "personal" | "high_impact";

type ApplicationItem = {
  id: string;
  status: string;
  job: {
    id: string;
    company: string | null;
    title: string | null;
    source_url: string | null;
  };
};

type ResumeVersion = {
  id: string;
  version_number: number;
  label: string;
  job_family: string | null;
  generation_reason: string;
  is_default: boolean;
};

type EvidenceItem = {
  id: string;
  title: string;
  claim: string;
  source: string;
};

type AnswerEntry = {
  id: string;
  question_pattern: string;
  answer: string;
  sensitivity: Sensitivity;
  scope_type: string;
  scope_value: string;
};

type OpenQuestion = {
  id: string;
  question: string;
  answer: string;
  sensitivity: Sensitivity;
  confirmed: boolean;
};

type PacketDecision = {
  id: string;
  decision: "APPROVE";
  actor_type: "user";
  created_at: string;
};

type PacketRevision = {
  id: string;
  revision_number: number;
  status: PacketStatus;
  supersedes_revision_id: string | null;
  job_analysis_id: string;
  jd_content_hash: string;
  profile_revision: number;
  resume_version_id: string | null;
  payload_hash: string;
  job_snapshot: {
    company?: string | null;
    title?: string | null;
    locations?: string[];
    job_type?: string | null;
    source_url?: string | null;
    raw_content?: string;
    verification_status?: string;
  };
  analysis_snapshot: {
    eligibility?: { eligible?: string };
    score?: { score?: number | null; recommendation?: string };
  };
  profile_snapshot: { revision?: number };
  resume_snapshot: {
    id?: string;
    version_number?: number;
    label?: string;
    job_family?: string | null;
    source_version_id?: string | null;
    generation_reason?: string;
    asset?: { original_filename?: string; sha256?: string; media_type?: string };
  };
  evidence_snapshots: Array<{
    id: string;
    title: string;
    claim: string;
    source: string;
  }>;
  form_answer_snapshots: Array<{
    id: string;
    question_pattern: string;
    answer: string;
    sensitivity: Sensitivity;
    confirmed_at: string;
  }>;
  open_questions: Array<{
    id: string;
    question: string;
    answer: string | null;
    sensitivity: Sensitivity;
    confirmed_at: string | null;
  }>;
  risk_snapshots: Array<{
    code: string;
    severity: "high" | "medium" | "low";
    title: string;
    detail: string;
  }>;
  confirmation_items: Array<{ field: string; state: string; reason: string }>;
  blockers: Array<{
    code: string;
    category: string;
    message: string;
    fields?: string[];
    requirement_name?: string | null;
  }>;
  created_by_actor: "user" | "agent";
  source_changed: boolean;
  source_change_codes: string[];
  decisions: PacketDecision[];
  created_at: string;
  approved_at: string | null;
};

type ApplicationPacket = {
  id: string;
  application_id: string;
  current_revision_id: string;
  status: PacketStatus;
  current_revision: PacketRevision;
  revisions: PacketRevision[];
  updated_at: string;
};

const statusLabel: Record<PacketStatus, string> = {
  DRAFT: "草稿",
  NEEDS_REVIEW: "待审核",
  APPROVED: "已批准",
  SUPERSEDED: "已失效",
};

const sensitivityLabel: Record<Sensitivity, string> = {
  standard: "普通",
  personal: "个人",
  high_impact: "高影响",
};

const sourceChangeLabel: Record<string, string> = {
  jd_content_changed: "岗位正文已变化",
  analysis_invalidated: "岗位分析已失效",
  analysis_version_changed: "分析规则已升级",
  analysis_input_changed: "分析输入已变化",
  private_profile_changed: "私密画像已变化",
  source_fingerprint_changed: "材料来源已变化",
  resume_version_not_found: "简历版本已不存在",
  evidence_not_found: "经历证据已不存在",
  answer_not_found: "答案来源已不存在",
};

async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { error?: { message?: string } };
    return payload.error?.message ?? `请求失败（${response.status}）`;
  } catch {
    return `请求失败（${response.status}）`;
  }
}

async function fetchWithRetry(url: string, headers: Record<string, string>): Promise<Response> {
  try {
    return await fetch(url, { headers, cache: "no-store" });
  } catch {
    await new Promise((resolve) => window.setTimeout(resolve, 180));
    return fetch(url, { headers, cache: "no-store" });
  }
}

function shortHash(value?: string): string {
  return value ? `${value.slice(0, 8)}…${value.slice(-6)}` : "—";
}

function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export default function PacketWorkspace({ apiUrl, userId }: { apiUrl: string; userId: string }) {
  const [state, setState] = useState<"loading" | "ready" | "saving" | "error">("loading");
  const [message, setMessage] = useState("");
  const [applications, setApplications] = useState<ApplicationItem[]>([]);
  const [packets, setPackets] = useState<ApplicationPacket[]>([]);
  const [resumes, setResumes] = useState<ResumeVersion[]>([]);
  const [evidence, setEvidence] = useState<EvidenceItem[]>([]);
  const [answers, setAnswers] = useState<AnswerEntry[]>([]);
  const [selectedApplicationId, setSelectedApplicationId] = useState("");
  const [inspectedRevisionId, setInspectedRevisionId] = useState("");
  const [selectedResumeId, setSelectedResumeId] = useState("");
  const [selectedEvidenceIds, setSelectedEvidenceIds] = useState<string[]>([]);
  const [selectedAnswerIds, setSelectedAnswerIds] = useState<string[]>([]);
  const [openQuestions, setOpenQuestions] = useState<OpenQuestion[]>([]);
  const loadSequence = useRef(0);

  const selectedApplication = applications.find((item) => item.id === selectedApplicationId) ?? null;
  const selectedPacket = packets.find((item) => item.application_id === selectedApplicationId) ?? null;
  const inspectedRevision = selectedPacket?.revisions.find((item) => item.id === inspectedRevisionId)
    ?? selectedPacket?.current_revision
    ?? null;
  const isCurrentRevision = Boolean(
    selectedPacket && inspectedRevision && selectedPacket.current_revision_id === inspectedRevision.id,
  );
  const canEdit = Boolean(
    isCurrentRevision && inspectedRevision && ["DRAFT", "NEEDS_REVIEW"].includes(inspectedRevision.status),
  );

  const applicationWithoutPacket = useMemo(
    () => applications.filter((application) => !packets.some((packet) => packet.application_id === application.id)).length,
    [applications, packets],
  );

  async function loadWorkspace(preferredApplicationId?: string) {
    const sequence = loadSequence.current + 1;
    loadSequence.current = sequence;
    setState("loading");
    setMessage("");
    const headers = { "X-User-ID": userId };
    try {
      const responses = await Promise.all([
        fetchWithRetry(`${apiUrl}/api/applications`, headers),
        fetchWithRetry(`${apiUrl}/api/application-packets`, headers),
        fetchWithRetry(`${apiUrl}/api/resumes/versions`, headers),
        fetchWithRetry(`${apiUrl}/api/evidence`, headers),
        fetchWithRetry(`${apiUrl}/api/answer-bank`, headers),
      ]);
      for (const response of responses) {
        if (!response.ok) throw new Error(await readError(response));
      }
      const [nextApplications, nextPackets, nextResumes, nextEvidence, nextAnswers] = await Promise.all([
        responses[0].json() as Promise<ApplicationItem[]>,
        responses[1].json() as Promise<ApplicationPacket[]>,
        responses[2].json() as Promise<ResumeVersion[]>,
        responses[3].json() as Promise<EvidenceItem[]>,
        responses[4].json() as Promise<AnswerEntry[]>,
      ]);
      if (sequence !== loadSequence.current) return;
      setApplications(nextApplications);
      setPackets(nextPackets);
      setResumes(nextResumes);
      setEvidence(nextEvidence);
      setAnswers(nextAnswers);
      const targetId = preferredApplicationId
        ?? selectedApplicationId
        ?? nextApplications[0]?.id
        ?? "";
      setSelectedApplicationId(
        nextApplications.some((item) => item.id === targetId) ? targetId : (nextApplications[0]?.id ?? ""),
      );
      setState("ready");
    } catch (error) {
      if (sequence !== loadSequence.current) return;
      setMessage(error instanceof Error ? error.message : "投递包工作台加载失败。");
      setState("error");
    }
  }

  useEffect(() => {
    void loadWorkspace();
    // The request sequence guard absorbs React development-mode duplicate effects.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selectedPacket) {
      setInspectedRevisionId("");
      setSelectedResumeId(resumes.find((item) => item.is_default)?.id ?? resumes[0]?.id ?? "");
      setSelectedEvidenceIds([]);
      setSelectedAnswerIds([]);
      setOpenQuestions([]);
      return;
    }
    const revision = selectedPacket.current_revision;
    setInspectedRevisionId(revision.id);
    setSelectedResumeId(revision.resume_version_id ?? "");
    setSelectedEvidenceIds(revision.evidence_snapshots.map((item) => item.id));
    setSelectedAnswerIds(revision.form_answer_snapshots.map((item) => item.id));
    setOpenQuestions(revision.open_questions.map((item) => ({
      id: item.id,
      question: item.question,
      answer: item.answer ?? "",
      sensitivity: item.sensitivity,
      confirmed: Boolean(item.confirmed_at),
    })));
  }, [selectedPacket?.current_revision_id, selectedApplicationId, resumes]);

  function applyPacket(packet: ApplicationPacket) {
    setPackets((current) => {
      const exists = current.some((item) => item.id === packet.id);
      return exists
        ? current.map((item) => (item.id === packet.id ? packet : item))
        : [packet, ...current];
    });
    setInspectedRevisionId(packet.current_revision_id);
  }

  async function requestPacket(path: string, method: "POST" | "PATCH", body?: object) {
    setState("saving");
    setMessage("");
    try {
      const response = await fetch(`${apiUrl}${path}`, {
        method,
        headers: { "Content-Type": "application/json", "X-User-ID": userId, "X-Actor-Type": "user" },
        body: JSON.stringify(body ?? {}),
      });
      if (!response.ok) throw new Error(await readError(response));
      const packet = (await response.json()) as ApplicationPacket;
      applyPacket(packet);
      setState("ready");
      return packet;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "投递包操作失败。");
      setState("error");
      return null;
    }
  }

  async function generatePacket() {
    if (!selectedApplicationId) return;
    const packet = await requestPacket(
      `/api/applications/${selectedApplicationId}/packet`,
      "POST",
      selectedResumeId ? { resume_version_id: selectedResumeId } : {},
    );
    if (packet) setMessage("投递包草稿已生成。先核对来源，再提交审核。");
  }

  async function saveDraft() {
    if (!selectedPacket || !isCurrentRevision) return;
    const packet = await requestPacket(
      `/api/packet-revisions/${selectedPacket.current_revision_id}/items`,
      "PATCH",
      {
        resume_version_id: selectedResumeId || null,
        evidence_ids: selectedEvidenceIds,
        answer_entry_ids: selectedAnswerIds,
        open_questions: openQuestions.map((item) => ({ ...item, id: item.id || undefined })),
      },
    );
    if (packet) setMessage("当前修订已按最新来源重新冻结。");
  }

  async function submitReview() {
    if (!selectedPacket) return;
    const packet = await requestPacket(
      `/api/packet-revisions/${selectedPacket.current_revision_id}/review`,
      "POST",
    );
    if (packet) setMessage("投递包已进入待审核状态。阻塞项仍会保留，直到你解决。");
  }

  async function approveRevision() {
    if (!selectedPacket) return;
    const packet = await requestPacket(
      `/api/packet-revisions/${selectedPacket.current_revision_id}/approve`,
      "POST",
      { confirmed: true },
    );
    if (packet) setMessage("该冻结版本已批准，可供后续投递尝试使用。");
  }

  async function createRevision() {
    if (!selectedPacket) return;
    const packet = await requestPacket(
      `/api/application-packets/${selectedPacket.id}/revisions`,
      "POST",
      {},
    );
    if (packet) setMessage("新修订已创建，上一批准版本已标记为失效。");
  }

  function toggleValue(value: string, values: string[], setter: (next: string[]) => void) {
    setter(values.includes(value) ? values.filter((item) => item !== value) : [...values, value]);
  }

  function updateQuestion(index: number, changes: Partial<OpenQuestion>) {
    setOpenQuestions((current) => current.map((item, itemIndex) => (
      itemIndex === index ? { ...item, ...changes } : item
    )));
  }

  return (
    <section className="packet-workspace" aria-live="polite">
      <header className="packet-workspace-heading">
        <div>
          <div className="section-kicker"><span>M15</span> 可审核投递包</div>
          <h2>批准一份冻结材料，<em>不是批准一组会变化的链接。</em></h2>
        </div>
        <button
          className="packet-refresh"
          type="button"
          onClick={() => void loadWorkspace(selectedApplicationId)}
          disabled={state === "loading" || state === "saving"}
          aria-label="刷新投递包"
          title="刷新投递包"
        >
          ↻
        </button>
      </header>

      {message ? <div className={`packet-message packet-message-${state}`}>{message}</div> : null}

      <div className="packet-shell">
        <aside className="packet-index">
          <div className="packet-index-summary">
            <span>{applications.length.toString().padStart(2, "0")}</span>
            <p>申请记录</p>
            <strong>{applicationWithoutPacket} 份待建包</strong>
          </div>
          <div className="packet-application-list" role="listbox" aria-label="选择申请">
            {applications.map((application) => {
              const packet = packets.find((item) => item.application_id === application.id);
              return (
                <button
                  key={application.id}
                  className={application.id === selectedApplicationId ? "packet-application-active" : ""}
                  onClick={() => setSelectedApplicationId(application.id)}
                  type="button"
                  role="option"
                  aria-selected={application.id === selectedApplicationId}
                >
                  <span>{application.job.company ?? "未命名公司"}</span>
                  <strong>{application.job.title ?? "未命名岗位"}</strong>
                  <small>{packet ? statusLabel[packet.status] : "尚未建包"}</small>
                </button>
              );
            })}
            {applications.length === 0 && state !== "loading" ? (
              <p className="packet-index-empty">先从岗位分析创建一条申请记录。</p>
            ) : null}
          </div>
        </aside>

        <div className="packet-review-surface">
          {state === "loading" && !selectedApplication ? (
            <div className="packet-empty"><span>SYNC</span><h3>正在装载冻结材料。</h3></div>
          ) : null}
          {selectedApplication && !selectedPacket ? (
            <div className="packet-create-state">
              <div>
                <span>APPLICATION / {selectedApplication.id.slice(-8).toUpperCase()}</span>
                <h3>{selectedApplication.job.company ?? "未命名公司"} / {selectedApplication.job.title ?? "未命名岗位"}</h3>
                <p>系统会绑定当前有效分析、JD 哈希、私密画像修订和所选简历。资料缺失会成为阻塞项，不会被猜测。</p>
              </div>
              <label>
                <span>初始简历版本</span>
                <select value={selectedResumeId} onChange={(event) => setSelectedResumeId(event.target.value)}>
                  <option value="">暂不选择</option>
                  {resumes.map((resume) => (
                    <option key={resume.id} value={resume.id}>V{resume.version_number} · {resume.label}</option>
                  ))}
                </select>
              </label>
              <button className="packet-primary-action" type="button" onClick={() => void generatePacket()} disabled={state === "saving"}>
                生成冻结草稿 <span>↗</span>
              </button>
            </div>
          ) : null}

          {selectedPacket && inspectedRevision ? (
            <>
              <div className="packet-review-toolbar">
                <div>
                  <span>PACKET {selectedPacket.id.slice(-8).toUpperCase()}</span>
                  <strong>{inspectedRevision.job_snapshot.company ?? "未命名公司"} / {inspectedRevision.job_snapshot.title ?? "未命名岗位"}</strong>
                </div>
                <span className={`packet-status packet-status-${inspectedRevision.status.toLowerCase()}`}>
                  {statusLabel[inspectedRevision.status]}
                </span>
              </div>

              <div className="packet-version-strip" aria-label="投递包版本历史">
                {selectedPacket.revisions.map((revision) => (
                  <button
                    key={revision.id}
                    className={revision.id === inspectedRevision.id ? "packet-version-active" : ""}
                    onClick={() => setInspectedRevisionId(revision.id)}
                    type="button"
                  >
                    <span>R{revision.revision_number.toString().padStart(2, "0")}</span>
                    <strong>{statusLabel[revision.status]}</strong>
                    <small>{formatTime(revision.approved_at ?? revision.created_at)}</small>
                  </button>
                ))}
              </div>

              {inspectedRevision.source_changed ? (
                <div className="packet-drift-alert">
                  <strong>冻结来源与当前资料不一致</strong>
                  <p>{inspectedRevision.source_change_codes.map((code) => sourceChangeLabel[code] ?? code).join(" · ")}</p>
                </div>
              ) : null}

              <section className="packet-review-section packet-jd-section">
                <div className="packet-section-heading">
                  <div><span>01 / JOB SNAPSHOT</span><h3>岗位事实与 JD 快照</h3></div>
                  <dl>
                    <div><dt>JD HASH</dt><dd>{shortHash(inspectedRevision.jd_content_hash)}</dd></div>
                    <div><dt>ANALYSIS</dt><dd>{inspectedRevision.job_analysis_id.slice(-8).toUpperCase()}</dd></div>
                    <div><dt>ELIGIBILITY</dt><dd>{inspectedRevision.analysis_snapshot.eligibility?.eligible ?? "unknown"}</dd></div>
                  </dl>
                </div>
                <div className="packet-job-facts">
                  <p><span>地点</span>{inspectedRevision.job_snapshot.locations?.join(" / ") || "未提供"}</p>
                  <p><span>类型</span>{inspectedRevision.job_snapshot.job_type || "未提供"}</p>
                  <p><span>来源</span>{inspectedRevision.job_snapshot.verification_status || "未验证"}</p>
                </div>
                <details className="packet-jd-details">
                  <summary>查看冻结 JD 原文</summary>
                  <pre>{inspectedRevision.job_snapshot.raw_content || "无岗位正文"}</pre>
                </details>
              </section>

              <section className="packet-review-section">
                <div className="packet-section-heading">
                  <div><span>02 / RESUME REVISION</span><h3>简历版本与差异身份</h3></div>
                  <span className="packet-source-lock">PROFILE R{inspectedRevision.profile_revision}</span>
                </div>
                {canEdit && isCurrentRevision ? (
                  <label className="packet-source-select">
                    <span>用于本修订的简历</span>
                    <select value={selectedResumeId} onChange={(event) => setSelectedResumeId(event.target.value)}>
                      <option value="">未选择</option>
                      {resumes.map((resume) => (
                        <option key={resume.id} value={resume.id}>V{resume.version_number} · {resume.label}</option>
                      ))}
                    </select>
                  </label>
                ) : null}
                {inspectedRevision.resume_snapshot.id ? (
                  <div className="packet-resume-diff">
                    <div><span>冻结版本</span><strong>V{inspectedRevision.resume_snapshot.version_number} · {inspectedRevision.resume_snapshot.label}</strong></div>
                    <div><span>来源版本</span><strong>{inspectedRevision.resume_snapshot.source_version_id?.slice(-8).toUpperCase() ?? "原始基线"}</strong></div>
                    <div><span>生成原因</span><strong>{inspectedRevision.resume_snapshot.generation_reason ?? "未记录"}</strong></div>
                    <div><span>文件身份</span><strong>{inspectedRevision.resume_snapshot.asset?.original_filename} / {shortHash(inspectedRevision.resume_snapshot.asset?.sha256)}</strong></div>
                  </div>
                ) : <p className="packet-inline-empty">当前修订没有简历版本。</p>}
              </section>

              <section className="packet-review-section">
                <div className="packet-section-heading">
                  <div><span>03 / EVIDENCE</span><h3>经历证据与来源</h3></div>
                  <span className="packet-source-lock">{inspectedRevision.evidence_snapshots.length} SELECTED</span>
                </div>
                {canEdit && isCurrentRevision ? (
                  <div className="packet-source-picker">
                    {evidence.map((item) => (
                      <label key={item.id}>
                        <input
                          type="checkbox"
                          checked={selectedEvidenceIds.includes(item.id)}
                          onChange={() => toggleValue(item.id, selectedEvidenceIds, setSelectedEvidenceIds)}
                        />
                        <span><strong>{item.title}</strong><small>{item.source}</small></span>
                      </label>
                    ))}
                    {evidence.length === 0 ? <p>资料库暂无经历证据。</p> : null}
                  </div>
                ) : (
                  <div className="packet-evidence-list">
                    {inspectedRevision.evidence_snapshots.map((item) => (
                      <article key={item.id}>
                        <span>{item.source}</span><strong>{item.title}</strong><p>{item.claim}</p>
                      </article>
                    ))}
                    {inspectedRevision.evidence_snapshots.length === 0 ? <p className="packet-inline-empty">未选中经历证据。</p> : null}
                  </div>
                )}
              </section>

              <section className="packet-review-section">
                <div className="packet-section-heading">
                  <div><span>04 / ANSWERS</span><h3>表单答案与开放题</h3></div>
                  <span className="packet-source-lock">USER CONFIRMATION</span>
                </div>
                {canEdit && isCurrentRevision ? (
                  <>
                    <div className="packet-source-picker packet-answer-picker">
                      {answers.map((item) => (
                        <label key={item.id}>
                          <input
                            type="checkbox"
                            checked={selectedAnswerIds.includes(item.id)}
                            onChange={() => toggleValue(item.id, selectedAnswerIds, setSelectedAnswerIds)}
                          />
                          <span><strong>{item.question_pattern}</strong><small>{sensitivityLabel[item.sensitivity]}</small></span>
                        </label>
                      ))}
                    </div>
                    <div className="packet-open-questions">
                      {openQuestions.map((question, index) => (
                        <div className="packet-open-question" key={question.id || index}>
                          <input value={question.question} onChange={(event) => updateQuestion(index, { question: event.target.value })} placeholder="开放题问题" />
                          <textarea value={question.answer} onChange={(event) => updateQuestion(index, { answer: event.target.value, confirmed: false })} placeholder="由用户核对的答案" rows={3} />
                          <div>
                            <select value={question.sensitivity} onChange={(event) => updateQuestion(index, { sensitivity: event.target.value as Sensitivity })}>
                              <option value="standard">普通</option><option value="personal">个人</option><option value="high_impact">高影响</option>
                            </select>
                            <label><input type="checkbox" checked={question.confirmed} onChange={(event) => updateQuestion(index, { confirmed: event.target.checked })} /> 用户已确认</label>
                            <button type="button" onClick={() => setOpenQuestions((current) => current.filter((_, itemIndex) => itemIndex !== index))} aria-label="删除开放题" title="删除开放题">×</button>
                          </div>
                        </div>
                      ))}
                      <button className="packet-add-question" type="button" onClick={() => setOpenQuestions((current) => [...current, { id: `open_${Date.now()}`, question: "", answer: "", sensitivity: "standard", confirmed: false }])}>添加开放题</button>
                    </div>
                  </>
                ) : (
                  <div className="packet-answer-review">
                    {[...inspectedRevision.form_answer_snapshots, ...inspectedRevision.open_questions.map((item) => ({ id: item.id, question_pattern: item.question, answer: item.answer ?? "", sensitivity: item.sensitivity, confirmed_at: item.confirmed_at ?? "" }))].map((item) => (
                      <article key={item.id} className={`packet-sensitive-${item.sensitivity}`}>
                        <span>{sensitivityLabel[item.sensitivity]}</span><strong>{item.question_pattern}</strong><p>{item.answer}</p><small>{item.confirmed_at ? `确认于 ${formatTime(item.confirmed_at)}` : "尚未确认"}</small>
                      </article>
                    ))}
                  </div>
                )}
              </section>

              <section className="packet-review-section packet-blocker-section">
                <div className="packet-section-heading">
                  <div><span>05 / CONTROL REGISTER</span><h3>风险与审批阻塞</h3></div>
                  <span className="packet-source-lock">{inspectedRevision.blockers.length} BLOCKERS</span>
                </div>
                <div className="packet-control-grid">
                  <div>
                    <h4>阻塞项</h4>
                    {inspectedRevision.blockers.map((item) => (
                      <article key={`${item.code}-${item.requirement_name ?? ""}`}><span>{item.category}</span><strong>{item.message}</strong><small>{item.fields?.join(" / ") || item.requirement_name || item.code}</small></article>
                    ))}
                    {inspectedRevision.blockers.length === 0 ? <p className="packet-clear-line">没有阻塞项</p> : null}
                  </div>
                  <div>
                    <h4>分析风险</h4>
                    {inspectedRevision.risk_snapshots.map((risk) => (
                      <article key={risk.code}><span>{risk.severity}</span><strong>{risk.title}</strong><small>{risk.detail}</small></article>
                    ))}
                    {inspectedRevision.risk_snapshots.length === 0 ? <p className="packet-clear-line">没有分析风险</p> : null}
                  </div>
                </div>
              </section>

              {isCurrentRevision ? (
                <footer className="packet-approval-dock">
                  <div>
                    <span>FROZEN PAYLOAD</span>
                    <strong>{shortHash(inspectedRevision.payload_hash)}</strong>
                    <p>批准仅绑定这一个修订号和内容哈希，不改变申请提交状态。</p>
                  </div>
                  <div className="packet-actions">
                    {canEdit ? <button type="button" onClick={() => void saveDraft()} disabled={state === "saving"}>保存并重新冻结</button> : null}
                    {inspectedRevision.status === "DRAFT" ? <button className="packet-review-action" type="button" onClick={() => void submitReview()} disabled={state === "saving"}>提交审核</button> : null}
                    {inspectedRevision.status === "NEEDS_REVIEW" ? <button className="packet-approve-action" type="button" onClick={() => void approveRevision()} disabled={state === "saving" || inspectedRevision.blockers.length > 0 || inspectedRevision.source_changed}>批准此冻结版本</button> : null}
                    {inspectedRevision.status === "APPROVED" && inspectedRevision.source_changed ? <button className="packet-review-action" type="button" onClick={() => void createRevision()} disabled={state === "saving"}>基于当前资料创建新修订</button> : null}
                  </div>
                </footer>
              ) : null}
            </>
          ) : null}
        </div>
      </div>
    </section>
  );
}
