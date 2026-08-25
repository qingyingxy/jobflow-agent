"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

type AttemptStatus =
  | "CREATED"
  | "FORM_IN_PROGRESS"
  | "NEEDS_USER"
  | "BLOCKED"
  | "READY_TO_SUBMIT"
  | "SUBMITTED"
  | "FAILED"
  | "ABANDONED";

type ApplicationItem = {
  id: string;
  job_posting_id: string;
  status: string;
  job: {
    company: string | null;
    title: string | null;
    source_url: string | null;
  };
};

type PacketRevision = {
  id: string;
  revision_number: number;
  status: "DRAFT" | "NEEDS_REVIEW" | "APPROVED" | "SUPERSEDED";
  source_changed: boolean;
  job_snapshot: {
    company?: string | null;
    title?: string | null;
    source_url?: string | null;
  };
};

type ApplicationPacket = {
  id: string;
  application_id: string;
  current_revision_id: string;
  status: "DRAFT" | "NEEDS_REVIEW" | "APPROVED" | "SUPERSEDED";
  current_revision: PacketRevision;
};

type AttemptBlocker = {
  id: string;
  category: string;
  observation: string;
  stop_reason: string;
  retryable: boolean;
  next_strategy: string | null;
  required_user_action: string | null;
  status: "OPEN" | "RESOLVED";
  created_at: string;
};

type AttemptReceipt = {
  id: string;
  confirmation_text: string | null;
  confirmation_url: string | null;
  application_number: string | null;
  screenshot_metadata: Record<string, unknown>;
  is_valid: boolean;
  validation_codes: string[];
  receipt_hash: string;
  captured_at: string;
};

type ChecklistItem = {
  code: string;
  label: string;
  complete: boolean;
  blocking: boolean;
};

type ApplicationAttempt = {
  id: string;
  application_id: string;
  job_posting_id: string;
  packet_revision_id: string;
  application_url: string;
  status: AttemptStatus;
  available_transitions: AttemptStatus[];
  checklist: ChecklistItem[];
  blockers: AttemptBlocker[];
  receipt: AttemptReceipt | null;
  created_at: string;
  updated_at: string;
  form_opened_at: string | null;
  ready_at: string | null;
  submitted_at: string | null;
};

type QueueItem = {
  packet: ApplicationPacket;
  application: ApplicationItem;
  attempt: ApplicationAttempt | null;
};

type BlockerDraft = {
  category: string;
  observation: string;
  stop_reason: string;
  retryable: boolean;
  next_strategy: string;
  required_user_action: string;
};

type ReceiptDraft = {
  confirmation_text: string;
  confirmation_url: string;
  application_number: string;
  user_confirmed: boolean;
  include_screenshot: boolean;
  screenshot_name: string;
  screenshot_type: "image/png" | "image/jpeg" | "image/webp";
  screenshot_size: string;
  screenshot_sha256: string;
  screenshot_redacted: boolean;
};

const statusLabel: Record<AttemptStatus, string> = {
  CREATED: "待打开",
  FORM_IN_PROGRESS: "填写中",
  NEEDS_USER: "需要你处理",
  BLOCKED: "已阻塞",
  READY_TO_SUBMIT: "待确认提交",
  SUBMITTED: "已验证投递",
  FAILED: "本次失败",
  ABANDONED: "已结束",
};

const emptyBlocker: BlockerDraft = {
  category: "login",
  observation: "",
  stop_reason: "",
  retryable: true,
  next_strategy: "",
  required_user_action: "",
};

const emptyReceipt: ReceiptDraft = {
  confirmation_text: "",
  confirmation_url: "",
  application_number: "",
  user_confirmed: false,
  include_screenshot: false,
  screenshot_name: "submission-confirmation.png",
  screenshot_type: "image/png",
  screenshot_size: "",
  screenshot_sha256: "",
  screenshot_redacted: true,
};

async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as {
      error?: { message?: string };
    };
    return payload.error?.message ?? `请求失败（${response.status}）`;
  } catch {
    return `请求失败（${response.status}）`;
  }
}

export default function AttemptWorkspace({ apiUrl, userId }: { apiUrl: string; userId: string }) {
  const [applications, setApplications] = useState<ApplicationItem[]>([]);
  const [packets, setPackets] = useState<ApplicationPacket[]>([]);
  const [attempts, setAttempts] = useState<ApplicationAttempt[]>([]);
  const [selectedApplicationId, setSelectedApplicationId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");
  const [blockerDraft, setBlockerDraft] = useState<BlockerDraft>(emptyBlocker);
  const [receiptDraft, setReceiptDraft] = useState<ReceiptDraft>(emptyReceipt);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const headers = { "X-User-ID": userId };
      const [applicationResponse, packetResponse, attemptResponse] = await Promise.all([
        fetch(`${apiUrl}/api/applications`, { headers, cache: "no-store" }),
        fetch(`${apiUrl}/api/application-packets`, { headers, cache: "no-store" }),
        fetch(`${apiUrl}/api/application-attempts`, { headers, cache: "no-store" }),
      ]);
      if (!applicationResponse.ok) throw new Error(await readError(applicationResponse));
      if (!packetResponse.ok) throw new Error(await readError(packetResponse));
      if (!attemptResponse.ok) throw new Error(await readError(attemptResponse));
      const nextApplications = (await applicationResponse.json()) as ApplicationItem[];
      const nextPackets = (await packetResponse.json()) as ApplicationPacket[];
      const nextAttempts = (await attemptResponse.json()) as ApplicationAttempt[];
      setApplications(nextApplications);
      setPackets(nextPackets);
      setAttempts(nextAttempts);
      const eligibleIds = nextPackets
        .filter((packet) => packet.status === "APPROVED" || nextAttempts.some((attempt) => attempt.application_id === packet.application_id))
        .map((packet) => packet.application_id);
      setSelectedApplicationId((current) => current && eligibleIds.includes(current) ? current : eligibleIds[0] ?? null);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "投递执行数据加载失败。");
    } finally {
      setLoading(false);
    }
  }, [apiUrl, userId]);

  useEffect(() => {
    void load();
  }, [load]);

  const queue = useMemo<QueueItem[]>(() => {
    const applicationMap = new Map(applications.map((item) => [item.id, item]));
    const attemptMap = new Map(attempts.map((item) => [item.application_id, item]));
    return packets
      .filter((packet) => packet.status === "APPROVED" || attemptMap.has(packet.application_id))
      .map((packet) => ({
        packet,
        application: applicationMap.get(packet.application_id),
        attempt: attemptMap.get(packet.application_id) ?? null,
      }))
      .filter((item): item is QueueItem => Boolean(item.application));
  }, [applications, attempts, packets]);

  const selected = queue.find((item) => item.application.id === selectedApplicationId) ?? null;

  async function request(path: string, init: RequestInit, successMessage: string) {
    setWorking(true);
    setMessage("");
    try {
      const response = await fetch(`${apiUrl}${path}`, {
        ...init,
        headers: {
          "Content-Type": "application/json",
          "X-User-ID": userId,
          ...(init.headers ?? {}),
        },
      });
      if (!response.ok) throw new Error(await readError(response));
      await load(true);
      setMessage(successMessage);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "操作失败，请重试。");
    } finally {
      setWorking(false);
    }
  }

  async function createAttempt() {
    if (!selected) return;
    await request(
      `/api/packet-revisions/${selected.packet.current_revision_id}/attempts`,
      { method: "POST", body: "{}" },
      "投递尝试已绑定到当前冻结版本。打开官网后再开始填写。",
    );
  }

  async function transition(status: AttemptStatus) {
    if (!selected?.attempt) return;
    await request(
      `/api/application-attempts/${selected.attempt.id}/status`,
      { method: "PATCH", body: JSON.stringify({ status }) },
      status === "FORM_IN_PROGRESS" ? "已记录表单开始时间。" : status === "READY_TO_SUBMIT" ? "检查完成，现在可以在官网提交并保存凭证。" : "投递尝试状态已更新。",
    );
  }

  async function addBlocker() {
    if (!selected?.attempt || !blockerDraft.observation.trim() || !blockerDraft.stop_reason.trim()) {
      setMessage("请填写页面观察和停止原因。");
      return;
    }
    await request(
      `/api/application-attempts/${selected.attempt.id}/blockers`,
      {
        method: "POST",
        body: JSON.stringify({
          ...blockerDraft,
          next_strategy: blockerDraft.next_strategy.trim() || null,
          required_user_action: blockerDraft.required_user_action.trim() || null,
        }),
      },
      "阻塞已记录。解决前不会允许确认提交。",
    );
    setBlockerDraft(emptyBlocker);
  }

  async function resolveBlocker(blockerId: string) {
    if (!selected?.attempt) return;
    await request(
      `/api/application-attempts/${selected.attempt.id}/blockers/${blockerId}/resolve`,
      { method: "POST", body: "{}" },
      "阻塞已解决，可以继续检查表单。",
    );
  }

  async function saveReceipt() {
    if (!selected?.attempt) return;
    const screenshot = receiptDraft.include_screenshot ? {
      file_name: receiptDraft.screenshot_name.trim() || null,
      content_type: receiptDraft.screenshot_type,
      size_bytes: Number(receiptDraft.screenshot_size),
      sha256: receiptDraft.screenshot_sha256.trim(),
      redacted: receiptDraft.screenshot_redacted,
    } : null;
    await request(
      `/api/application-attempts/${selected.attempt.id}/receipt`,
      {
        method: "POST",
        body: JSON.stringify({
          confirmation_text: receiptDraft.confirmation_text.trim() || null,
          confirmation_url: receiptDraft.confirmation_url.trim() || null,
          application_number: receiptDraft.application_number.trim() || null,
          screenshot_metadata: screenshot,
          user_confirmed: receiptDraft.user_confirmed,
        }),
      },
      "提交凭证已验证并冻结。申请仍未标记为已投递。",
    );
  }

  async function finalize() {
    if (!selected?.attempt) return;
    await request(
      `/api/application-attempts/${selected.attempt.id}/finalize`,
      { method: "POST", body: "{}" },
      "投递已确认：申请、冻结版本、Attempt 与 Receipt 已完成关联。",
    );
  }

  if (loading) {
    return <section className="attempt-workspace attempt-loading">正在核对已批准投递包与执行记录…</section>;
  }

  return (
    <section className="attempt-workspace">
      <div className="attempt-command-bar">
        <div>
          <span>MANUAL APPLY CONTROL</span>
          <strong>{queue.length} 条可执行申请</strong>
        </div>
        <p>官网由你操作；系统只负责冻结材料、记录阻塞并验证提交凭证。</p>
        <button onClick={() => void load()} disabled={working} type="button" title="刷新投递执行数据" aria-label="刷新投递执行数据">↻</button>
      </div>

      {message ? <div className="attempt-message" role="status">{message}</div> : null}

      {queue.length === 0 ? (
        <div className="attempt-empty">
          <span>NO APPROVED PACKET</span>
          <h2>还没有可以执行的投递。</h2>
          <p>先在“投递审核”中批准一个冻结版本，它才会进入这里。</p>
        </div>
      ) : (
        <div className="attempt-layout">
          <aside className="attempt-queue" aria-label="投递执行队列">
            <header><span>01</span><strong>执行队列</strong></header>
            {queue.map((item, index) => (
              <button
                className={selected?.application.id === item.application.id ? "attempt-queue-item attempt-queue-item-active" : "attempt-queue-item"}
                key={item.application.id}
                onClick={() => setSelectedApplicationId(item.application.id)}
                type="button"
              >
                <span className="attempt-queue-index">{String(index + 1).padStart(2, "0")}</span>
                <span className="attempt-queue-copy">
                  <small>{item.application.job.company ?? "未命名公司"}</small>
                  <strong>{item.application.job.title ?? "未命名岗位"}</strong>
                </span>
                <span className={`attempt-status attempt-status-${(item.attempt?.status ?? "CREATED").toLowerCase()}`}>
                  {item.attempt ? statusLabel[item.attempt.status] : "待创建"}
                </span>
              </button>
            ))}
          </aside>

          {selected ? (
            <div className="attempt-detail">
              <header className="attempt-detail-header">
                <div>
                  <span>02 / EXECUTION</span>
                  <h2>{selected.application.job.company ?? "未命名公司"} / {selected.application.job.title ?? "未命名岗位"}</h2>
                  <p>Packet revision {selected.packet.current_revision.revision_number} · {selected.packet.current_revision_id.slice(-8).toUpperCase()}</p>
                </div>
                <span className={`attempt-status attempt-status-large attempt-status-${(selected.attempt?.status ?? "CREATED").toLowerCase()}`}>
                  {selected.attempt ? statusLabel[selected.attempt.status] : "尚未执行"}
                </span>
              </header>

              {!selected.attempt ? (
                <section className="attempt-launch">
                  <div className="attempt-launch-proof">
                    <span>APPROVED PACKET</span>
                    <strong>冻结版本已批准</strong>
                    <p>Attempt 会固定绑定这条申请、岗位、官方 URL 和当前投递包版本。</p>
                  </div>
                  <button onClick={createAttempt} disabled={working || selected.packet.current_revision.source_changed} type="button">
                    创建投递尝试 <span>↗</span>
                  </button>
                </section>
              ) : (
                <>
                  <section className="attempt-official-row">
                    <div>
                      <span>OFFICIAL APPLICATION URL</span>
                      <a href={selected.attempt.application_url} target="_blank" rel="noreferrer">{selected.attempt.application_url}</a>
                    </div>
                    {selected.attempt.status === "CREATED" ? (
                      <button onClick={() => transition("FORM_IN_PROGRESS")} disabled={working} type="button">已打开，开始填写</button>
                    ) : selected.attempt.status === "FAILED" ? (
                      <button onClick={() => transition("FORM_IN_PROGRESS")} disabled={working} type="button">重新进入表单</button>
                    ) : (
                      <a className="attempt-open-link" href={selected.attempt.application_url} target="_blank" rel="noreferrer">打开官网 ↗</a>
                    )}
                  </section>

                  <section className="attempt-checklist">
                    <header><span>03</span><div><strong>执行检查</strong><p>只有全部关键项完成后，Application 才能进入已投递。</p></div></header>
                    <div className="attempt-check-grid">
                      {selected.attempt.checklist.map((item, index) => (
                        <div className={item.complete ? "attempt-check attempt-check-complete" : "attempt-check"} key={item.code}>
                          <span>{item.complete ? "✓" : String(index + 1).padStart(2, "0")}</span>
                          <strong>{item.label}</strong>
                          <small>{item.complete ? "已确认" : "待完成"}</small>
                        </div>
                      ))}
                    </div>
                    {selected.attempt.status === "FORM_IN_PROGRESS" && selected.attempt.blockers.every((item) => item.status === "RESOLVED") ? (
                      <button className="attempt-ready-button" onClick={() => transition("READY_TO_SUBMIT")} disabled={working} type="button">表单检查完成，进入待提交</button>
                    ) : null}
                  </section>

                  <section className="attempt-blockers">
                    <header><span>04</span><div><strong>阻塞队列</strong><p>登录、验证码、敏感问题和页面异常都应在这里暂停。</p></div></header>
                    {selected.attempt.blockers.length > 0 ? (
                      <div className="attempt-blocker-list">
                        {selected.attempt.blockers.map((blocker) => (
                          <article className={blocker.status === "RESOLVED" ? "attempt-blocker attempt-blocker-resolved" : "attempt-blocker"} key={blocker.id}>
                            <div className="attempt-blocker-topline">
                              <span>{blocker.category.toUpperCase()}</span>
                              <small>{blocker.status === "OPEN" ? "OPEN" : "RESOLVED"}</small>
                            </div>
                            <strong>{blocker.observation}</strong>
                            <p>{blocker.stop_reason}</p>
                            {blocker.required_user_action ? <div><span>需要你做</span>{blocker.required_user_action}</div> : null}
                            {blocker.next_strategy ? <div><span>下一策略</span>{blocker.next_strategy}</div> : null}
                            {blocker.status === "OPEN" ? <button onClick={() => resolveBlocker(blocker.id)} disabled={working} type="button">标记已解决</button> : null}
                          </article>
                        ))}
                      </div>
                    ) : <p className="attempt-no-blocker">当前没有阻塞记录。</p>}

                    {!["SUBMITTED", "ABANDONED"].includes(selected.attempt.status) ? (
                      <div className="attempt-blocker-form">
                        <label><span>类别</span><select value={blockerDraft.category} onChange={(event) => setBlockerDraft((current) => ({ ...current, category: event.target.value }))}><option value="login">登录</option><option value="captcha">验证码 / CAPTCHA</option><option value="sensitive_question">敏感问题</option><option value="upload">材料上传</option><option value="page_change">页面变化</option><option value="other">其他</option></select></label>
                        <label className="attempt-wide-field"><span>页面观察</span><input value={blockerDraft.observation} onChange={(event) => setBlockerDraft((current) => ({ ...current, observation: event.target.value }))} placeholder="例如：页面要求短信验证码" /></label>
                        <label className="attempt-wide-field"><span>停止原因</span><input value={blockerDraft.stop_reason} onChange={(event) => setBlockerDraft((current) => ({ ...current, stop_reason: event.target.value }))} placeholder="说明为什么不能继续" /></label>
                        <label><span>下一策略</span><input value={blockerDraft.next_strategy} onChange={(event) => setBlockerDraft((current) => ({ ...current, next_strategy: event.target.value }))} placeholder="例如：验证后重试" /></label>
                        <label><span>需要你的动作</span><input value={blockerDraft.required_user_action} onChange={(event) => setBlockerDraft((current) => ({ ...current, required_user_action: event.target.value }))} placeholder="留空则记为系统阻塞" /></label>
                        <label className="attempt-checkbox"><input type="checkbox" checked={blockerDraft.retryable} onChange={(event) => setBlockerDraft((current) => ({ ...current, retryable: event.target.checked }))} /><span>解决后可以重试</span></label>
                        <button onClick={addBlocker} disabled={working} type="button">记录并暂停</button>
                      </div>
                    ) : null}
                  </section>

                  {selected.attempt.status === "READY_TO_SUBMIT" || selected.attempt.receipt ? (
                    <section className="attempt-receipt">
                      <header><span>05</span><div><strong>提交凭证</strong><p>先在官网真正提交，再保存确认信息。保存凭证本身不会改变 Application 状态。</p></div></header>
                      {selected.attempt.receipt ? (
                        <div className="attempt-receipt-proof">
                          <div><span>RECEIPT VERIFIED</span><strong>{selected.attempt.receipt.application_number ?? "未提供申请编号"}</strong></div>
                          <p>{selected.attempt.receipt.confirmation_text ?? "已使用脱敏截图元数据确认"}</p>
                          <dl><div><dt>捕获时间</dt><dd>{new Date(selected.attempt.receipt.captured_at).toLocaleString("zh-CN")}</dd></div><div><dt>证据类型</dt><dd>{selected.attempt.receipt.validation_codes.join(" / ")}</dd></div><div><dt>凭证哈希</dt><dd>{selected.attempt.receipt.receipt_hash.slice(0, 16)}…</dd></div></dl>
                          {selected.attempt.status === "READY_TO_SUBMIT" ? <button onClick={finalize} disabled={working} type="button">确认真实投递并更新申请</button> : <span className="attempt-finalized">Application 已进入 SUBMITTED</span>}
                        </div>
                      ) : (
                        <div className="attempt-receipt-form">
                          <label className="attempt-wide-field"><span>确认文本</span><textarea value={receiptDraft.confirmation_text} onChange={(event) => setReceiptDraft((current) => ({ ...current, confirmation_text: event.target.value }))} rows={3} placeholder="粘贴成功页上的确认文本" /></label>
                          <label><span>确认页面 URL</span><input value={receiptDraft.confirmation_url} onChange={(event) => setReceiptDraft((current) => ({ ...current, confirmation_url: event.target.value }))} placeholder="https://…/confirmation" /></label>
                          <label><span>申请 / Reference 编号</span><input value={receiptDraft.application_number} onChange={(event) => setReceiptDraft((current) => ({ ...current, application_number: event.target.value }))} placeholder="例如：APP-2026-001" /></label>
                          <details className="attempt-screenshot-fields">
                            <summary><input type="checkbox" checked={receiptDraft.include_screenshot} onChange={(event) => setReceiptDraft((current) => ({ ...current, include_screenshot: event.target.checked }))} /> 添加脱敏截图元数据</summary>
                            <div><label><span>文件名</span><input value={receiptDraft.screenshot_name} onChange={(event) => setReceiptDraft((current) => ({ ...current, screenshot_name: event.target.value }))} /></label><label><span>类型</span><select value={receiptDraft.screenshot_type} onChange={(event) => setReceiptDraft((current) => ({ ...current, screenshot_type: event.target.value as ReceiptDraft["screenshot_type"] }))}><option value="image/png">PNG</option><option value="image/jpeg">JPEG</option><option value="image/webp">WEBP</option></select></label><label><span>字节数</span><input inputMode="numeric" value={receiptDraft.screenshot_size} onChange={(event) => setReceiptDraft((current) => ({ ...current, screenshot_size: event.target.value }))} /></label><label className="attempt-wide-field"><span>SHA-256</span><input value={receiptDraft.screenshot_sha256} onChange={(event) => setReceiptDraft((current) => ({ ...current, screenshot_sha256: event.target.value }))} /></label><label className="attempt-checkbox"><input type="checkbox" checked={receiptDraft.screenshot_redacted} onChange={(event) => setReceiptDraft((current) => ({ ...current, screenshot_redacted: event.target.checked }))} /><span>截图已经脱敏</span></label></div>
                          </details>
                          <label className="attempt-confirmation"><input type="checkbox" checked={receiptDraft.user_confirmed} onChange={(event) => setReceiptDraft((current) => ({ ...current, user_confirmed: event.target.checked }))} /><span>我确认官网已经显示提交成功，上述信息来自真实成功页面。</span></label>
                          <button onClick={saveReceipt} disabled={working || !receiptDraft.user_confirmed} type="button">验证并冻结凭证</button>
                        </div>
                      )}
                    </section>
                  ) : null}
                </>
              )}
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}

