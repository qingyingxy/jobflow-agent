"use client";

import { useEffect, useState, type FormEvent } from "react";
import { parseApiTimestamp } from "./api-time";

export type DiscoveredCompanySource = {
  id: string; company: string; homepage_url: string; career_url: string;
  status: "pending" | "verified" | "manually_confirmed"; reason: string; attempts: number;
  evidence_url?: string | null; review_revision?: string;
  verification_method?: "automatic" | "manual" | null; confirmed_at?: string | null;
  entry_chain?: { url: string; linked_url: string; final_url: string; link_text: string; relation: string }[];
};

export default function CompanyDiscoveryPanel({ apiUrl, userId, sources, refreshToken, onChanged }: {
  apiUrl: string; userId: string; sources?: DiscoveredCompanySource[]; refreshToken: number; onChanged: () => void;
}) {
  const [items, setItems] = useState<DiscoveredCompanySource[]>(sources || []);
  const [error, setError] = useState("");
  useEffect(() => {
    if (sources) { setItems(sources); setError(""); return; }
    const abort = new AbortController();
    fetch(`${apiUrl}/api/discovery/companies`, { headers: { "X-User-ID": userId }, cache: "no-store", signal: abort.signal })
      .then(async response => { if (!response.ok) throw new Error(); return response.json() as Promise<DiscoveredCompanySource[]>; })
      .then(value => { if (!abort.signal.aborted) { setItems(value); setError(""); } })
      .catch(() => { if (!abort.signal.aborted) setError("公司候选读取失败，请刷新重试。"); });
    return () => abort.abort();
  }, [apiUrl, userId, sources, refreshToken]);
  if (!items.length && !error) return null;
  return <details className="company-search-progress" aria-label="新公司发现">
    <summary>新公司发现 · {items.filter(item => item.status !== "pending").length} 家已入库 · {items.filter(item => item.status === "pending").length} 家待核实</summary>
    <p>核验通过或经你人工确认的入口加入后续分批查询。待核实入口可以查看证据、修改地址后确认；入库不代表已找到符合岗位。</p>
    {error && <p role="alert">{error}</p>}
    <div className="company-search-cards">{items.map(source => <CompanyReviewCard key={source.id}
      source={source} apiUrl={apiUrl} userId={userId} onSaved={updated => {
        setItems(current => current.map(item => item.id === updated.id ? updated : item)); onChanged();
      }} />)}</div>
  </details>;
}

function CompanyReviewCard({ source, apiUrl, userId, onSaved }: {
  source: DiscoveredCompanySource; apiUrl: string; userId: string; onSaved: (source: DiscoveredCompanySource) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [homepage, setHomepage] = useState(source.homepage_url);
  const [career, setCareer] = useState(source.career_url);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [editingRevision, setEditingRevision] = useState(source.review_revision);
  const pending = source.status === "pending";
  const changedWhileEditing = editing && editingRevision !== source.review_revision;
  useEffect(() => {
    if (!editing) { setHomepage(source.homepage_url); setCareer(source.career_url); }
  }, [editing, source.homepage_url, source.career_url]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!confirmed || busy || !editingRevision || changedWhileEditing) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`${apiUrl}/api/discovery/companies/${source.id}/confirm`, {
        method: "POST", headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({ homepage_url: homepage.trim(), career_url: career.trim(), confirmed: true, expected_revision: editingRevision }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "确认失败，请检查网址或刷新后重试。");
      onSaved(body as DiscoveredCompanySource);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "确认失败，请重试。");
    } finally { setBusy(false); }
  }
  return <article aria-label={`${source.company}公司入口`}>
    <strong>{source.company}</strong>
    <span>{source.status === "verified" ? "官方入口已核验 · 已加入公司库" : source.status === "manually_confirmed" ? "人工确认 · 已加入公司库" : "待核实 · 尚未加入查询队列"}</span>
    <small>{source.reason}</small>
    <div className="company-evidence-links"><a href={source.homepage_url} target="_blank" rel="noopener noreferrer">{pending ? "候选主页" : "公司主页"} ↗</a>
      <a href={source.career_url} target="_blank" rel="noopener noreferrer">{pending ? "候选招聘入口" : "招聘入口"} ↗</a>
      {source.evidence_url && <a href={source.evidence_url} target="_blank" rel="noopener noreferrer">核验来源 ↗</a>}</div>
    {!!source.entry_chain?.length && <details><summary>查看核验路径</summary><ol>{source.entry_chain.map((edge, index) => <li key={index}>
      <a href={edge.url} target="_blank" rel="noopener noreferrer">{edge.relation === "same_domain_return_to_homepage" ? "同域招聘页面" : index === 0 ? "公司主页" : "关联页面"}</a>
      {" → "}<a href={edge.linked_url} target="_blank" rel="noopener noreferrer">{edge.link_text || "实际链接"}</a>
    </li>)}</ol></details>}
    {source.confirmed_at && <small>确认时间：{parseApiTimestamp(source.confirmed_at).toLocaleString("zh-CN")}</small>}
    {pending && !editing && <button type="button" onClick={() => { setEditingRevision(source.review_revision); setEditing(true); }}>确认或修改入口</button>}
    {pending && editing && <form className="company-review-form" onSubmit={submit}>
      <label>公司主页<input type="url" required value={homepage} disabled={busy} onChange={event => { setHomepage(event.target.value); setConfirmed(false); }} /></label>
      <label>招聘入口<input type="url" required value={career} disabled={busy} onChange={event => { setCareer(event.target.value); setConfirmed(false); }} /></label>
      <div className="company-evidence-links">{[homepage, career].map((url, index) => /^https?:\/\//i.test(url.trim()) && <a key={index} href={url.trim()} target="_blank" rel="noopener noreferrer">查看{index === 0 ? "填写的主页" : "填写的招聘入口"} ↗</a>)}</div>
      <label className="company-review-ack"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} />我已查看上述网址，确认它们属于{source.company}</label>
      <small>会标记为人工确认，岗位条件仍需逐条核验。</small>
      {error && <p role="alert">{error}</p>}
      {changedWhileEditing && <p role="alert">核验记录已更新，你填写的地址已保留。请取消后重新查看并确认。</p>}
      <div><button type="submit" disabled={!confirmed || busy || !editingRevision || changedWhileEditing}>{busy ? "正在保存…" : "确认并加入公司库"}</button>
        <button type="button" disabled={busy} onClick={() => { setEditing(false); setConfirmed(false); setError(""); }}>取消</button></div>
    </form>}
  </article>;
}
