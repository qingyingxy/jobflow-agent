"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

type AttemptStatus = "CREATED" | "FORM_IN_PROGRESS" | "NEEDS_USER" | "BLOCKED" | "READY_TO_SUBMIT" | "SUBMITTED" | "FAILED" | "ABANDONED";
type AtsStatus = "INSPECTED" | "NEEDS_USER" | "READY_FOR_APPROVAL" | "AUTHORIZED" | "SUBMITTING" | "SUBMITTED" | "FAILED";
type AtsProvider = "GREENHOUSE" | "LEVER";
type FieldRisk = "LOW" | "PERSONAL" | "HIGH_IMPACT" | "LEGAL";
type FieldAction = "FILL" | "NEEDS_CONFIRMATION" | "NEEDS_VALUE" | "SKIP";

type ApplicationItem = {
  id: string;
  status: string;
  job: { company: string | null; title: string | null; source_url: string | null };
};

type AttemptItem = {
  id: string;
  application_id: string;
  job_posting_id: string;
  packet_revision_id: string;
  application_url: string;
  status: AttemptStatus;
  receipt: { id: string; is_valid: boolean } | null;
};

type FieldPlan = {
  field_key: string;
  label: string;
  name: string;
  input_type: string;
  required: boolean;
  canonical_name: string;
  risk: FieldRisk;
  action: FieldAction;
  source: string | null;
  value: string | null;
  reason: string;
  options: string[];
};

type AtsSession = {
  id: string;
  attempt_id: string;
  application_id: string;
  job_posting_id: string;
  packet_revision_id: string;
  application_url: string;
  provider: AtsProvider;
  status: AtsStatus;
  page_fingerprint: string;
  plan_hash: string;
  field_plan: FieldPlan[];
  handoff_reasons: Array<{ code?: string; category?: string; field_key?: string; label?: string; message?: string }>;
  final_summary: {
    company?: string | null;
    job_title?: string | null;
    resume?: string | null;
    field_count?: number;
    fill_count?: number;
    key_answers?: Array<{ field_key?: string; label?: string; value?: string; risk?: string; source?: string }>;
  };
  authorization_expires_at: string | null;
  authorization_used: boolean;
  inspected_at: string;
  prepared_at: string | null;
  submitted_at: string | null;
};

const attemptStatusLabel: Record<AttemptStatus, string> = {
  CREATED: "待检查",
  FORM_IN_PROGRESS: "填写中",
  NEEDS_USER: "待接管",
  BLOCKED: "已阻塞",
  READY_TO_SUBMIT: "待授权",
  SUBMITTED: "已提交",
  FAILED: "失败",
  ABANDONED: "已结束",
};

const sessionStatusLabel: Record<AtsStatus, string> = {
  INSPECTED: "已检查",
  NEEDS_USER: "需要你确认",
  READY_FOR_APPROVAL: "等待最终授权",
  AUTHORIZED: "一次性授权有效",
  SUBMITTING: "正在提交",
  SUBMITTED: "提交已验证",
  FAILED: "结果需人工核对",
};

const riskLabel: Record<FieldRisk, string> = {
  LOW: "低风险",
  PERSONAL: "个人敏感",
  HIGH_IMPACT: "高影响",
  LEGAL: "法律确认",
};

const actionLabel: Record<FieldAction, string> = {
  FILL: "自动填写",
  NEEDS_CONFIRMATION: "等待确认",
  NEEDS_VALUE: "缺少来源",
  SKIP: "保持为空",
};

const pipeline = ["检测", "检查", "映射", "填写", "验证", "授权", "提交", "凭证"];

async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { error?: { message?: string } };
    return payload.error?.message ?? `请求失败（${response.status}）`;
  } catch {
    return `请求失败（${response.status}）`;
  }
}

function shortId(value: string): string {
  return value.slice(-8).toUpperCase();
}

function maskedValue(field: FieldPlan): string {
  if (!field.value) return "—";
  if (field.canonical_name === "contact_email") {
    const [name, host] = field.value.split("@");
    return host ? `${name.slice(0, 2)}***@${host}` : "已提供";
  }
  if (field.canonical_name === "contact_phone") return `${field.value.slice(0, 3)}****${field.value.slice(-2)}`;
  if (field.canonical_name === "resume") return "已绑定冻结简历";
  return field.value;
}

export default function AtsWorkspace({ apiUrl, userId }: { apiUrl: string; userId: string }) {
  const [applications, setApplications] = useState<ApplicationItem[]>([]);
  const [attempts, setAttempts] = useState<AttemptItem[]>([]);
  const [sessions, setSessions] = useState<AtsSession[]>([]);
  const [selectedAttemptId, setSelectedAttemptId] = useState<string | null>(null);
  const [selectedConfirmations, setSelectedConfirmations] = useState<string[]>([]);
  const [approvalConfirmed, setApprovalConfirmed] = useState(false);
  const [authorizationToken, setAuthorizationToken] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const headers = { "X-User-ID": userId };
      const [applicationResponse, attemptResponse, sessionResponse] = await Promise.all([
        fetch(`${apiUrl}/api/applications`, { headers, cache: "no-store" }),
        fetch(`${apiUrl}/api/application-attempts`, { headers, cache: "no-store" }),
        fetch(`${apiUrl}/api/ats-sessions`, { headers, cache: "no-store" }),
      ]);
      if (!applicationResponse.ok) throw new Error(await readError(applicationResponse));
      if (!attemptResponse.ok) throw new Error(await readError(attemptResponse));
      if (!sessionResponse.ok) throw new Error(await readError(sessionResponse));
      const nextApplications = (await applicationResponse.json()) as ApplicationItem[];
      const nextAttempts = (await attemptResponse.json()) as AttemptItem[];
      const nextSessions = (await sessionResponse.json()) as AtsSession[];
      const usable = nextAttempts.filter((item) => item.status !== "ABANDONED");
      setApplications(nextApplications);
      setAttempts(usable);
      setSessions(nextSessions);
      setSelectedAttemptId((current) => current && usable.some((item) => item.id === current) ? current : usable[0]?.id ?? null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATS 辅助数据加载失败。");
    } finally {
      setLoading(false);
    }
  }, [apiUrl, userId]);

  useEffect(() => { void load(); }, [load]);

  const applicationMap = useMemo(() => new Map(applications.map((item) => [item.id, item])), [applications]);
  const sessionMap = useMemo(() => new Map(sessions.map((item) => [item.attempt_id, item])), [sessions]);
  const selectedAttempt = attempts.find((item) => item.id === selectedAttemptId) ?? null;
  const selectedSession = selectedAttempt ? sessionMap.get(selectedAttempt.id) ?? null : null;
  const selectedApplication = selectedAttempt ? applicationMap.get(selectedAttempt.application_id) : undefined;
  const confirmableFields = selectedSession?.field_plan.filter((field) => field.action === "NEEDS_CONFIRMATION") ?? [];
  const submissionUnverified = selectedSession?.handoff_reasons.some((reason) => reason.category === "submission") ?? false;

  useEffect(() => {
    setSelectedConfirmations([]);
    setApprovalConfirmed(false);
    setAuthorizationToken("");
  }, [selectedAttemptId]);

  async function mutate(path: string, init: RequestInit, success: string) {
    setWorking(true);
    setMessage("");
    try {
      const response = await fetch(`${apiUrl}${path}`, {
        ...init,
        headers: { "Content-Type": "application/json", "X-User-ID": userId, ...(init.headers ?? {}) },
      });
      if (!response.ok) throw new Error(await readError(response));
      const payload = await response.json();
      await load(true);
      setMessage(success);
      return payload;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATS 操作失败。");
      return null;
    } finally {
      setWorking(false);
    }
  }

  async function inspectAttempt() {
    if (!selectedAttempt) return;
    await mutate(`/api/application-attempts/${selectedAttempt.id}/ats-session`, { method: "POST", body: "{}" }, "ATS 表单检查完成。只会填写来源明确的字段。");
  }

  async function confirmFields() {
    if (!selectedSession || selectedConfirmations.length === 0) return;
    const result = await mutate(`/api/ats-sessions/${selectedSession.id}/confirm-fields`, { method: "POST", body: JSON.stringify({ field_keys: selectedConfirmations, confirmed: true }) }, "已确认本次表单中的高影响字段，并重新验证填写结果。");
    if (result) setSelectedConfirmations([]);
  }

  async function retrySession() {
    if (!selectedSession) return;
    await mutate(`/api/ats-sessions/${selectedSession.id}/retry`, { method: "POST", body: JSON.stringify({ user_completed_handoff: true }) }, "已重新检查页面；旧授权不会被沿用。");
  }

  async function authorize() {
    if (!selectedSession || !approvalConfirmed) return;
    const result = await mutate(`/api/ats-sessions/${selectedSession.id}/authorization`, { method: "POST", body: JSON.stringify({ confirmed: true }) }, "一次性授权已签发，只绑定当前岗位、URL、投递包和页面指纹。") as { authorization_token?: string } | null;
    if (result?.authorization_token) setAuthorizationToken(result.authorization_token);
  }

  async function submit() {
    if (!selectedSession || !authorizationToken) return;
    const result = await mutate(`/api/ats-sessions/${selectedSession.id}/submit`, { method: "POST", body: JSON.stringify({ authorization_token: authorizationToken }) }, "ATS 已返回可验证成功信息，凭证已冻结，Application 已进入 SUBMITTED。");
    if (result) setAuthorizationToken("");
  }

  return (
    <section className="ats-workspace">
      <header className="ats-command-bar">
        <div><span>LIMITED ATS CONTROL / M18</span><strong>只支持 Greenhouse 与 Lever</strong></div>
        <div className="ats-command-metrics"><span><b>{attempts.length}</b> ATTEMPTS</span><span><b>{sessions.filter((item) => item.status === "NEEDS_USER").length}</b> HANDOFFS</span><span><b>{sessions.filter((item) => item.status === "SUBMITTED").length}</b> VERIFIED</span></div>
        <button onClick={() => void load()} disabled={working} title="刷新 ATS 控制台" aria-label="刷新 ATS 控制台" type="button">↻</button>
      </header>

      {message ? <div className="ats-message" role="status">{message}</div> : null}

      <div className="ats-shell">
        <aside className="ats-attempt-index">
          <div className="ats-index-heading"><span>01 / ATTEMPT BINDING</span><strong>待执行队列</strong></div>
          {loading ? <p className="ats-empty-copy">正在加载已批准投递尝试…</p> : null}
          {!loading && attempts.length === 0 ? <p className="ats-empty-copy">先在 M16 使用已批准投递包创建 Attempt，浏览器辅助不会绕过材料审批。</p> : null}
          <div className="ats-attempt-list">
            {attempts.map((attempt) => {
              const application = applicationMap.get(attempt.application_id);
              const atsSession = sessionMap.get(attempt.id);
              return <button className={selectedAttemptId === attempt.id ? "ats-attempt-active" : ""} key={attempt.id} onClick={() => setSelectedAttemptId(attempt.id)} type="button"><span>{atsSession?.provider ?? "UNINSPECTED"} / {shortId(attempt.id)}</span><strong>{application?.job.company ?? "未命名公司"}</strong><small>{application?.job.title ?? "未命名岗位"}</small><em>{atsSession ? sessionStatusLabel[atsSession.status] : attemptStatusLabel[attempt.status]}</em></button>;
            })}
          </div>
        </aside>

        <main className="ats-surface">
          {!selectedAttempt ? <div className="ats-empty-state"><span>NO APPROVED ATTEMPT</span><h2>没有可进入浏览器辅助的投递尝试。</h2></div> : !selectedSession ? (
            <div className="ats-inspection-state"><div><span>02 / DETECT</span><h2>{selectedApplication?.job.company} / {selectedApplication?.job.title}</h2><p>系统会打开当前 Attempt 绑定的官方 URL，只检测受支持 ATS、字段结构和人工验证门槛。此时不会点击提交。</p><code>{selectedAttempt.application_url}</code></div><button onClick={() => void inspectAttempt()} disabled={working || selectedAttempt.status === "SUBMITTED"} type="button">检测并检查 ATS</button></div>
          ) : (
            <>
              <section className="ats-binding-strip">
                <div><span>{selectedSession.provider}</span><strong>{selectedApplication?.job.company} / {selectedApplication?.job.title}</strong><small>REV {shortId(selectedSession.packet_revision_id)} · URL {shortId(selectedSession.page_fingerprint)}</small></div>
                <b className={`ats-session-status ats-session-${selectedSession.status.toLowerCase()}`}>{sessionStatusLabel[selectedSession.status]}</b>
              </section>

              <ol className="ats-pipeline" aria-label="ATS 辅助执行阶段">
                {pipeline.map((step, index) => <li className={index <= (selectedSession.status === "SUBMITTED" ? 7 : selectedSession.status === "AUTHORIZED" || selectedSession.status === "SUBMITTING" ? 5 : selectedSession.status === "READY_FOR_APPROVAL" ? 4 : 2) ? "ats-pipeline-done" : ""} key={step}><span>{String(index + 1).padStart(2, "0")}</span><strong>{step}</strong></li>)}
              </ol>

              <div className="ats-review-grid">
                <section className="ats-field-review">
                  <header><div><span>03 / FIELD PLAN</span><h2>字段映射与风险</h2></div><strong>{selectedSession.field_plan.filter((field) => field.action === "FILL").length} / {selectedSession.field_plan.length} 可填写</strong></header>
                  <div className="ats-field-table">
                    {selectedSession.field_plan.map((field) => (
                      <article className={`ats-field-row ats-risk-${field.risk.toLowerCase()}`} key={field.field_key}>
                        <div className="ats-field-identity"><span>{field.required ? "REQUIRED" : "OPTIONAL"} · {field.input_type.toUpperCase()}</span><strong>{field.label}</strong><small>{field.source ?? "NO APPROVED SOURCE"}</small></div>
                        <div className="ats-field-value"><span>冻结值</span><strong>{maskedValue(field)}</strong></div>
                        <div className="ats-field-decision"><span className={`ats-risk ats-risk-${field.risk.toLowerCase()}`}>{riskLabel[field.risk]}</span><strong>{actionLabel[field.action]}</strong>{field.action === "NEEDS_CONFIRMATION" ? <label><input type="checkbox" checked={selectedConfirmations.includes(field.field_key)} onChange={(event) => setSelectedConfirmations((current) => event.target.checked ? [...current, field.field_key] : current.filter((key) => key !== field.field_key))} /><span>本次确认</span></label> : null}</div>
                      </article>
                    ))}
                  </div>
                  {confirmableFields.length > 0 ? <div className="ats-confirm-bar"><p>确认只适用于当前岗位、URL、投递包版本和字段值哈希。</p><button onClick={() => void confirmFields()} disabled={working || selectedConfirmations.length === 0} type="button">确认所选高影响字段</button></div> : null}
                </section>

                <aside className="ats-approval-panel">
                  <header><span>04 / FINAL APPROVAL</span><h2>最终提交摘要</h2></header>
                  <dl><div><dt>公司</dt><dd>{selectedSession.final_summary.company ?? selectedApplication?.job.company ?? "—"}</dd></div><div><dt>岗位</dt><dd>{selectedSession.final_summary.job_title ?? selectedApplication?.job.title ?? "—"}</dd></div><div><dt>简历</dt><dd>{selectedSession.final_summary.resume ?? "—"}</dd></div><div><dt>Adapter</dt><dd>{selectedSession.provider}</dd></div><div><dt>填写字段</dt><dd>{selectedSession.final_summary.fill_count ?? 0} / {selectedSession.final_summary.field_count ?? 0}</dd></div></dl>

                  {selectedSession.handoff_reasons.length > 0 ? <div className="ats-handoff"><span>HUMAN HANDOFF</span>{selectedSession.handoff_reasons.map((reason, index) => <div key={`${reason.code}-${index}`}><strong>{reason.label ?? reason.code ?? "需要人工处理"}</strong><p>{reason.message}</p></div>)}</div> : null}

                  {selectedSession.status === "NEEDS_USER" && confirmableFields.length === 0 && !submissionUnverified ? <button className="ats-retry" onClick={() => void retrySession()} disabled={working} type="button">已人工处理，重新检查</button> : null}
                  {submissionUnverified ? <div className="ats-stop"><strong>禁止自动重试</strong><p>先在官网核对是否已经收到申请，再回到 M16 人工保存真实凭证。</p></div> : null}

                  {selectedSession.status === "READY_FOR_APPROVAL" || selectedSession.status === "AUTHORIZED" ? <label className="ats-final-confirm"><input type="checkbox" checked={approvalConfirmed} onChange={(event) => setApprovalConfirmed(event.target.checked)} /><span>我已核对公司、岗位、简历版本、关键答案和风险，并授权这一次提交。</span></label> : null}
                  {selectedSession.status === "READY_FOR_APPROVAL" || selectedSession.status === "AUTHORIZED" ? <button className="ats-authorize" onClick={() => void authorize()} disabled={working || !approvalConfirmed} type="button">{selectedSession.status === "AUTHORIZED" ? "重新签发一次性授权" : "签发一次性提交授权"}</button> : null}
                  {authorizationToken ? <div className="ats-token-ready"><span>ONE-TIME TOKEN IN MEMORY</span><strong>授权不会保存到浏览器存储</strong><button onClick={() => void submit()} disabled={working} type="button">提交并捕获凭证</button></div> : null}
                  {selectedSession.status === "SUBMITTED" ? <div className="ats-receipt-ok"><span>RECEIPT VERIFIED</span><strong>官网成功信息已通过 M16 凭证校验。</strong></div> : null}
                </aside>
              </div>
            </>
          )}
        </main>
      </div>
    </section>
  );
}
