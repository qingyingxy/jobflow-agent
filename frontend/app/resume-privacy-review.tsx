"use client";
import { apiError } from "./api-error";

import { useEffect, useState } from "react";

export default function ResumePrivacyReview({ apiUrl, userId, assetId, onDone, onCancel }: {
  apiUrl: string; userId: string; assetId: string; onDone: (parsed: boolean) => void; onCancel: () => void;
}) {
  const [preview, setPreview] = useState<{ text: string; preview_hash: string; model: string } | null>(null);
  const [text, setText] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void fetch(`${apiUrl}/api/resumes/assets/${assetId}/preview`, {
      headers: { "X-User-ID": userId }, signal: controller.signal, cache: "no-store",
    }).then(async response => {
      const body = await response.json();
      if (!response.ok) throw new Error(apiError(body, "无法读取简历预览"));
      setPreview(body); setText(body.text);
    }).catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [apiUrl, userId, assetId]);

  async function parse() {
    if (!preview || !confirmed || busy) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`${apiUrl}/api/resumes/assets/${assetId}/parse`, {
        method: "POST", headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({ confirmed: true, preview_hash: preview.preview_hash, text }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(apiError(body, "解析失败，请重试"));
      onDone(true);
    } catch (e) { setError(e instanceof Error ? e.message : "解析失败"); }
    finally { setBusy(false); }
  }

  return <section className="product-review" aria-label="简历发送前确认">
    <h3>核对将要解析的内容</h3>
    <p>已在本地隐藏常见姓名、联系方式、地址和证件号。请检查是否有遗漏，可继续删除不想发送的内容。</p>
    {preview ? <>
      <p>确认后，下方文字将交给 {preview.model} 解析。原始文件保存在本地。</p>
      <textarea aria-label="脱敏简历预览" rows={12} value={text} disabled={busy}
        onChange={e => { setText(e.target.value); setConfirmed(false); }} />
      <label><input type="checkbox" checked={confirmed} disabled={busy}
        onChange={e => setConfirmed(e.target.checked)} />我已检查，同意解析以上内容</label>
    </> : !error ? <p>正在本地提取和脱敏…</p> : null}
    {error && <p role="alert">{error}</p>}
    <div className="product-actions">
      <button type="button" onClick={() => void parse()} disabled={!preview || !confirmed || busy}>{busy ? "解析中…" : "确认并解析"}</button>
      <button type="button" disabled={busy} onClick={() => onDone(false)}>仅保存文件，不解析</button>
      <button type="button" disabled={busy} onClick={onCancel}>取消</button>
    </div>
  </section>;
}
