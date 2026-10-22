"use client";
import { parseApiTimestamp } from "./api-time";
import { apiError } from "./api-error";

import { useState } from "react";

type Requirement = { category: string; name: string; description: string; mandatory: boolean;
  relation: string; items: string[] | null; education?: { relation: string; [key: string]: unknown } | null;
  [key: string]: unknown };
type Review = { parse_result_id: string; revision: number; raw_content: string; requirements: Requirement[];
  history: { revision: number; reason: string; created_at: string; restored: boolean }[] };

export default function JobCorrectionEditor<T>({ apiUrl, userId, jobId, onSaved }: {
  apiUrl: string; userId: string; jobId: string; onSaved: (analysis: T) => void;
}) {
  const [review, setReview] = useState<Review | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const headers = { "Content-Type": "application/json", "X-User-ID": userId };
  async function load() {
    setBusy(true); setError("");
    try {
      const response = await fetch(`${apiUrl}/api/jobs/${jobId}/corrections`, { headers, cache: "no-store" });
      const body = await response.json();
      if (!response.ok) throw new Error(apiError(body, "读取失败"));
      setReview(body); setRequirements(body.requirements); setReason("");
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(false); }
  }
  async function save(restore = false) {
    if (!review) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`${apiUrl}/api/jobs/${jobId}/corrections`, {
        method: "PUT", headers, body: JSON.stringify({ parse_result_id: review.parse_result_id,
          expected_revision: review.revision, requirements: restore ? null : requirements,
          reason: restore ? "恢复模型解析结果" : reason.trim() }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(apiError(body, "保存失败，请检查条件原文和选项"));
      onSaved(body); setReview(null);
    } catch (e) { setError(e instanceof Error ? e.message : "保存失败"); }
    finally { setBusy(false); }
  }
  function edit(index: number, changes: Partial<Requirement>) {
    setRequirements(rows => rows.map((r, i) => {
      if (i !== index) return r;
      const updated = { ...r, ...changes };
      if (updated.education && changes.relation) updated.education = { ...updated.education, relation: changes.relation };
      return updated;
    }));
  }
  return <section className="product-review">
    <button type="button" disabled={busy} onClick={() => void load()}>纠正岗位条件</button>
    {review && <>
      <p>可调整必须/优先、条件关系、误解析项和遗漏项。引用须来自原文；保存后只重新计算本地匹配，不调用模型。</p>
      <details><summary>查看原始 JD</summary><pre>{review.raw_content}</pre></details>
      {requirements.map((r, i) => <fieldset key={i} disabled={busy}>
        <legend>条件 {i + 1}</legend>
        <label>条件名称<input aria-label={`条件${i + 1}名称`} value={r.name} maxLength={120} onChange={e => edit(i, { name: e.target.value })} /></label>
        {!r.education && <label>类型<select aria-label={`条件${i + 1}类型`} value={r.category} onChange={e => edit(i, { category: e.target.value })}>
          <option value="required_skill">技能</option><option value="preferred_skill">优先技能</option><option value="experience">经历</option><option value="education">学历</option><option value="major">专业</option><option value="other">其他</option>
        </select></label>}
        <label>条件原文<textarea rows={3} aria-label={`条件${i + 1}原文`} value={r.description} readOnly={Boolean(r.education)} onChange={e => edit(i, { description: e.target.value })} /></label>
        <label>强度<select aria-label={`条件${i + 1}强度`} value={r.mandatory ? "required" : "preferred"} onChange={e => edit(i, { mandatory: e.target.value === "required" })}>
          <option value="required">必须</option><option value="preferred">优先</option></select></label>
        <label>条件关系<select aria-label={`条件${i + 1}关系`} value={r.relation} onChange={e => edit(i, { relation: e.target.value })}>
          <option value="all_of">全部满足</option><option value="any_of">任选其一</option><option value="uncertain">待核实</option></select></label>
        <label>条件选项（每行一项）<textarea rows={3} aria-label={`条件${i + 1}选项`} value={(r.items || []).join("\n")} readOnly={Boolean(r.education)} onChange={e => edit(i, { items: e.target.value.trim() ? e.target.value.split("\n") : null })} /></label>
        {Boolean(r.education) && <small>学历分支保留原解析，可调整强度和关系；不确定时请选择待核实。</small>}
        <button type="button" onClick={() => setRequirements(rows => rows.filter((_, j) => j !== i))}>移除这条误解析条件</button>
      </fieldset>)}
      <button type="button" disabled={busy || requirements.length >= 50} onClick={() => setRequirements(rows => [...rows, {
        category: "required_skill", name: "补充条件", description: "", mandatory: true, relation: "all_of", items: null,
      }])}>补充遗漏条件</button>
      <label>修改原因<input aria-label="纠错原因" value={reason} maxLength={500} onChange={e => setReason(e.target.value)} /></label>
      <div className="product-actions"><button type="button" disabled={busy || !reason.trim()} onClick={() => void save()}>保存并重新匹配</button>
        <button type="button" disabled={busy || !review.revision} onClick={() => void save(true)}>恢复模型结果</button>
        <button type="button" disabled={busy} onClick={() => setReview(null)}>取消</button></div>
      {!!review.history.length && <details><summary>修改记录（{review.history.length}）</summary>{review.history.map(item => <p key={item.revision}>#{item.revision} · {item.reason} · {parseApiTimestamp(item.created_at).toLocaleString()}</p>)}</details>}
    </>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
