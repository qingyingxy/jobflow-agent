"use client";
import { apiError } from "./api-error";

import { useState } from "react";

export default function ManualSubmission({ apiUrl, userId, applicationId, onSaved }: {
  apiUrl: string; userId: string; applicationId: string; onSaved: () => void;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save() {
    if (!confirmed || busy) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`${apiUrl}/api/applications/${applicationId}/manual-submission`, {
        method: "POST", headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({ confirmed: true, note: note.trim() || null }),
      });
      if (!response.ok) { const body = await response.json(); throw new Error(apiError(body, "记录失败")); }
      onSaved();
    } catch (e) { setError(e instanceof Error ? e.message : "记录失败"); }
    finally { setBusy(false); }
  }
  return <details className="product-review"><summary>已经在官网投递？记录一下</summary>
    <p>保存后标注为“用户确认投递”。如需保存系统核验的回执，可使用“记录投递过程”。</p>
    <label>备注（可选）<input value={note} maxLength={1000} onChange={e => setNote(e.target.value)} /></label>
    <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />我确认已经在官网提交了这份申请</label>
    <button type="button" disabled={busy || !confirmed} onClick={() => void save()}>{busy ? "保存中…" : "记录为已投递"}</button>
    {error && <p role="alert">{error}</p>}
  </details>;
}
