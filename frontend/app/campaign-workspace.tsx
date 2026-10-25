"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiError } from "./api-error";
import { parseApiTimestamp } from "./api-time";

export type CampaignCompany = {
  company_id: string; company: string; career_url: string; followed: boolean;
  status: string; checked_at: string | null; succeeded_at: string | null;
  next_check_at: string | null; error: string | null;
};
type DateEvidence = { value: string; quote: string } | null;
export type Campaign = {
  id: string; company_id: string; company: string; year: number; title: string;
  batch: string; batch_label: string; source_url: string; status: string;
  first_seen_at: string; last_seen_at: string; changed_at: string;
  cohort_status?: "confirmed" | "unspecified";
  application_url?: string | null; entry_url?: string | null;
  availability_checked_at?: string | null; availability_stale?: boolean;
  availability_scope?: "job" | "listing" | "project" | "campaign";
  latest_event: { kind: string; at: string } | null;
  facts: { year_quote: string; batch_quote: string; status_quote: string;
    entry?: { title: string; quote: string; campus_quote: string; year_quote: string; origin_url: string; link_text: string; checked_at: string; job_titles?: string[]; job_presence?: string };
    published: DateEvidence; starts: DateEvidence; deadline: DateEvidence; directions: string[] };
};
export type CampaignTarget = Pick<Campaign, "company_id" | "company" | "year">;
export type CampaignCompanyCard = CampaignCompany & CampaignTarget & {
  recruitment_status: "open" | "upcoming" | "empty" | "unknown"; status_note: string;
  recruitment_url: string; cohort_status: "confirmed" | "unspecified";
  availability_checked_at: string | null; availability_stale: boolean;
  first_seen_at: string | null; opening_date: string | null; directions: string[];
  evidence_ids: string[]; evidence_count: number;
  job_titles?: string[];
  judgment_reason?: string; citations?: { url: string; quote: string }[];
};
type Discovery = {
  enabled: boolean; status: string; stage: string; queries_completed: number; queries_total: number;
  companies_found: number; companies_verified: number; companies_queued: number;
  pending_companies: { company: string; reason: string }[]; next_run_at: string | null; error: string | null;
};
type Snapshot = { year: number | null; companies: CampaignCompany[]; campaigns: Campaign[];
  company_cards: CampaignCompanyCard[]; discovery: Discovery };

const statusLabels: Record<string, string> = { open: "网申开放", announced: "开放状态待确认", upcoming: "即将开放", closed: "已截止", unknown: "开放状态待确认" };
const eventLabels: Record<string, string> = { first_seen: "首次发现", updated: "公告有更新", deadline_changed: "截止时间变更", closed: "已结束", opened: "新开放" };
const checkLabels: Record<string, string> = { idle: "尚未检查", queued: "等待检查", running: "检查中", ready: "已检查", partial: "部分完成", failed: "检查未完成" };
export const campaignTime = (value: string | null | undefined) => value ? parseApiTimestamp(value).toLocaleString("zh-CN", {
  timeZone: "Asia/Shanghai", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
}) : "尚未检查";

export default function CampaignWorkspace({ apiUrl, userId, initialYear, onFindJobs }: {
  apiUrl: string; userId: string; initialYear?: number; onFindJobs: (campaign: CampaignTarget) => Promise<void>;
}) {
  const [year, setYear] = useState<number | undefined>(initialYear);
  const [data, setData] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [keyword, setKeyword] = useState("");
  const [followedOnly, setFollowedOnly] = useState(false);
  const [openOnly, setOpenOnly] = useState(false);
  const [selected, setSelected] = useState<Campaign | null>(null);
  const [loading, setLoading] = useState(true);
  const revision = useRef(0);
  const details = useRef<HTMLDialogElement>(null);
  const headers = { "Content-Type": "application/json", "X-User-ID": userId };

  const load = useCallback(async () => {
    const request = ++revision.current;
    try {
      const response = await fetch(`${apiUrl}/api/campaigns${year ? `?year=${year}` : ""}`, { headers: { "X-User-ID": userId }, cache: "no-store" });
      if (!response.ok) throw new Error("秋招动态暂时无法读取，请检查服务后重试。");
      const next = await response.json() as Snapshot;
      if (!Array.isArray(next.companies) || !Array.isArray(next.campaigns) || !Array.isArray(next.company_cards)) throw new Error("秋招动态返回异常，请重试。");
      if (revision.current === request) { setData(next); setError(""); }
    } catch (e) { if (revision.current === request) setError(e instanceof Error ? e.message : "读取失败"); }
    finally { if (revision.current === request) setLoading(false); }
  }, [apiUrl, userId, year]);

  useEffect(() => {
    setData(null); setLoading(true); void load();
    const timer = window.setInterval(() => void load(), 6000);
    return () => { revision.current++; window.clearInterval(timer); };
  }, [load]);
  useEffect(() => { if (selected) details.current?.showModal(); }, [selected]);

  const activeYear = year ?? data?.year ?? undefined;
  const following = new Set(data?.companies.filter(c => c.followed).map(c => c.company_id));
  const visible = data?.company_cards.filter(c => (!followedOnly || c.followed) && (!openOnly || c.recruitment_status === "open")
    && c.company.toLowerCase().includes(keyword.toLowerCase())) || [];
  const active = data?.companies.filter(c => ["queued", "running"].includes(c.status)) || [];
  const discovery = data?.discovery;
  const discovering = !!discovery && ["queued", "running"].includes(discovery.status);
  const yearOptions = [...new Set([activeYear, new Date().getFullYear(), new Date().getFullYear() + 1, new Date().getFullYear() + 2].filter((v): v is number => !!v))].sort();

  async function mutate(path: string, method: string, body: object, key: string) {
    setBusy(key); setError("");
    ++revision.current;
    try {
      const response = await fetch(`${apiUrl}/api/campaigns${path}`, { method, headers, body: JSON.stringify(body) });
      const next = await response.json();
      if (!response.ok) throw new Error(apiError(next, "操作未完成，请重试。"));
      setData(next);
      window.dispatchEvent(new Event("jobflow:tracking-changed"));
    } catch (e) { setError(e instanceof Error ? e.message : "操作失败"); }
    finally { setBusy(""); }
  }
  async function findJobs(campaign: CampaignTarget) {
    setBusy(campaign.company_id); setError("");
    try { await onFindJobs(campaign); }
    catch (e) { setError(e instanceof Error ? e.message : "岗位搜索未启动，请重试。"); }
    finally { setBusy(""); }
  }

  function companyCard(c: CampaignCompanyCard) {
    const evidence = data?.campaigns.filter(item => c.evidence_ids.includes(item.id)) || [];
    return <article className="campaign-card" key={c.company_id} aria-label={`${c.company}校招`}>
      <div className="campaign-card-main"><div className="campaign-card-title"><h3>{c.company}</h3><span>{c.cohort_status === "confirmed" ? `${c.year} 届` : "届别待核实"}</span><span className={`campaign-status campaign-status-${c.recruitment_status}`}>{c.recruitment_status === "open" ? "有校招岗位" : c.recruitment_status === "empty" ? "暂未发现校招岗位" : "待确认"}</span></div>
        <p className="campaign-company-note">{c.status_note}</p>
        {c.judgment_reason && <details className="campaign-company-evidence"><summary>判断依据</summary>
          <p>{c.judgment_reason}</p>
          {c.citations?.map((citation, index) => <p key={`${citation.url}-${index}`}>
            <q>{citation.quote}</q> <a href={citation.url} target="_blank" rel="noreferrer">查看来源 ↗</a>
          </p>)}
        </details>}
        <p className="campaign-dates">
          {c.opening_date && <span>已知网申开始：{c.opening_date}</span>}
          {c.first_seen_at && <span>首次收录校招信息 {campaignTime(c.first_seen_at)}</span>}
          {c.availability_checked_at && <span>{c.availability_stale ? "待重新检查，上次读取" : "最近检查"} {campaignTime(c.availability_checked_at)}</span>}
        </p>
        {!!c.job_titles?.length && <p className="campaign-directions">已发现岗位：{c.job_titles.slice(0, 3).join("、")}</p>}
        {!!c.directions.length && <p className="campaign-directions">{c.directions.join(" · ")}</p>}
        <p className="campaign-check-state">{checkLabels[c.status]}{c.checked_at && ` · ${campaignTime(c.checked_at)}`}{c.error && ` · ${c.error}`}</p>
        {!!evidence.length && <details className="campaign-company-evidence"><summary>查看 {c.evidence_count} 条招聘依据</summary>
          {evidence.map(item => <div className="campaign-evidence-row" key={item.id}>
            <button className="campaign-title-link" type="button" onClick={() => setSelected(item)}>{item.title}</button>
            <p>{item.batch_label} · {item.facts.entry?.job_presence === "found" ? "已发现岗位" : statusLabels[item.status]}{item.facts.deadline && ` · ${item.facts.deadline.value} 截止`}</p>
            {item.latest_event && item.latest_event.kind !== "first_seen" && <p>{eventLabels[item.latest_event.kind]} · {campaignTime(item.latest_event.at)}</p>}
            <a href={item.source_url} target="_blank" rel="noreferrer">查看官方依据 ↗</a>
            {item.application_url && <a href={item.application_url} target="_blank" rel="noreferrer">该岗位或项目的投递入口 ↗</a>}
          </div>)}
        </details>}
      </div>
      <div className="campaign-card-actions">
        <a className="campaign-apply-link" href={c.recruitment_url} target="_blank" rel="noreferrer">官方招聘入口 ↗</a>
        <button type="button" disabled={!!busy} onClick={() => void findJobs(c)}>查看相关岗位</button>
        <button type="button" disabled={!!busy || ["queued", "running"].includes(c.status)} onClick={() => void mutate("/refresh", "POST", { year: c.year, company_ids: [c.company_id] }, c.company_id)}>检查状态</button>
        <button className="campaign-follow" type="button" aria-pressed={following.has(c.company_id)} disabled={!!busy || !activeYear}
          onClick={() => void mutate(`/companies/${c.company_id}/watch`, "PUT", { year: activeYear, followed: !following.has(c.company_id) }, c.company_id)}>{following.has(c.company_id) ? "已关注" : "关注公司"}</button>
      </div>
    </article>;
  }

  return <section className="campaign-workspace" aria-label="秋招动态">
    <div className="campaign-toolbar">
      <div><h2>哪些公司有校招岗位</h2><p>查看官网有校招岗位的公司，从招聘入口继续了解。</p></div>
      <div className="campaign-toolbar-actions">
        <label>毕业届别<select aria-label="秋招毕业届别" value={activeYear || ""} disabled={!!busy} onChange={e => setYear(Number(e.target.value) || undefined)}>
          <option value="">请选择届别</option>{yearOptions.map(y => <option key={y} value={y}>{y} 届</option>)}
        </select></label>
        <button type="button" className="campaign-primary" disabled={!activeYear || !!busy || discovering || !discovery?.enabled}
          onClick={() => void mutate("/discover", "POST", { year: activeYear }, "discover")}>{discovering ? "正在发现公司…" : discovery?.status === "blocked" ? "重试公司发现" : "发现更多公司"}</button>
        <button type="button" disabled={!activeYear || !!busy || active.length > 0}
          onClick={() => void mutate("/refresh", "POST", { year: activeYear }, "refresh")}>{active.length ? `正在检查 ${active.length} 家` : "检查已收录公司"}</button>
      </div>
    </div>
    {error && <p role="alert" className="goal-error">{error} <button type="button" onClick={() => void load()}>重新读取</button></p>}
    {discovery && discovery.status !== "idle" && <div className="campaign-discovery-progress" role="status">
      <p>{discovering ? "正在搜索和核验公司" : discovery.status === "completed" ? "本轮公司发现完成" : discovery.status === "waiting" ? "本轮搜索完成，部分公司等待复核；可继续发现更多公司" : "公司发现待继续"} · 搜索进度 {discovery.queries_completed}/{discovery.queries_total} · 发现 {discovery.companies_found} 家 · 已核验官网 {discovery.companies_verified} 家 · 已安排校招检查 {discovery.companies_queued} 家</p>
      {discovery.error && <p>{discovery.error}</p>}
      {(discovering || discovery.status === "waiting") && discovery.next_run_at && new Date(discovery.next_run_at).getTime() > Date.now() + 60000 && <p>下一次继续核验：{campaignTime(discovery.next_run_at)}</p>}
      {!!discovery.pending_companies.length && <details><summary>待核验公司 · {discovery.pending_companies.length} 家</summary>{discovery.pending_companies.map(c => <p key={c.company}>{c.company}：{c.reason}</p>)}</details>}
    </div>}
    {discovery && !discovery.enabled && <p className="campaign-footnote">启用公司发现并配置模型服务后，可搜索更多公司。</p>}
    {active.length > 0 && <p className="campaign-progress" role="status">正在检查公司校招状态：{active.filter(c => c.status === "running").map(c => c.company).join("、") || "等待开始"}。确认结果会陆续显示。</p>}
    <div className="campaign-filterbar">
      <div className="campaign-view-options" role="group" aria-label="秋招范围"><button type="button" aria-pressed={!followedOnly} onClick={() => setFollowedOnly(false)}>全部公司</button><button type="button" aria-pressed={followedOnly} onClick={() => setFollowedOnly(true)}>我关注的{following.size > 0 ? ` · ${following.size}` : ""}</button></div>
      <input aria-label="搜索秋招公司" type="search" value={keyword} onChange={e => setKeyword(e.target.value)} placeholder="搜索公司名称" />
    </div>
    <div className="campaign-sortbar"><span>有校招岗位优先 · {visible.length} 家公司</span><label className="campaign-open-filter"><input type="checkbox" checked={openOnly} onChange={e => setOpenOnly(e.target.checked)} />只看有岗位</label></div>
    {loading ? <p className="campaign-empty" role="status">正在读取秋招动态…</p> : !visible.length ? <div className="campaign-empty">
      <h3>{!activeYear ? "先选择你关注的毕业届别" : openOnly ? "当前范围暂无已发现校招岗位的公司" : keyword || followedOnly ? "当前范围暂无公司" : "还没有收录公司"}</h3>
      <p>{openOnly ? "关闭“只看有岗位”可查看其他公司，也可以检查最新状态。" : "点击“发现更多公司”扩大范围，或检查已收录公司的校招状态。"}</p>
    </div> : <div className="campaign-list">{visible.map(companyCard)}</div>}
    <p className="campaign-footnote">以官网校招列表中的实际岗位为依据，首次收录时间与网申开始时间分别展示。超过 24 小时未检查的信息标为待确认。关注后每小时复查，自动更新需要后端服务运行。检查已收录公司会逐家完成，结果陆续显示。</p>
    <dialog ref={details} className="campaign-evidence-dialog" aria-label="公告依据" onClose={() => setSelected(null)} onClick={e => { if (e.target === e.currentTarget) details.current?.close(); }}>
      {selected && <><header><div><small>{selected.company} · {selected.cohort_status === "unspecified" ? "届别未注明" : `${selected.year} 届`}</small><h2>{selected.title}</h2></div><button type="button" onClick={() => details.current?.close()} aria-label="关闭公告依据">×</button></header>
        <p>{statusLabels[selected.status]} · 最近读取：{campaignTime(selected.last_seen_at)}</p>
        <dl>{[["招聘届别", selected.facts.year_quote], ["招聘批次", selected.facts.batch_quote], ["开放状态", selected.facts.status_quote], ["发布日期", selected.facts.published?.quote], ["开始时间", selected.facts.starts?.quote], ["截止时间", selected.facts.deadline?.quote]].map(([label, quote]) => <div key={label}><dt>{label}</dt><dd>{quote || "官网未明确"}</dd></div>)}</dl>
        {selected.facts.entry && <div className="campaign-entry-evidence"><h3>官网岗位依据</h3><p>{selected.facts.entry.title} · {campaignTime(selected.facts.entry.checked_at)}</p><dl>
          {!!selected.facts.entry.job_titles?.length && <div><dt>发现的岗位</dt><dd>{selected.facts.entry.job_titles.join("、")}</dd></div>}
          <div><dt>入口状态依据</dt><dd>{selected.facts.entry.quote || "尚未确认开放状态"}</dd></div>
          <div><dt>校招与届别依据</dt><dd>{[selected.facts.entry.campus_quote, selected.facts.entry.year_quote].filter(Boolean).join(" · ") || "官网未明确"}</dd></div>
          <div><dt>官网链接来源</dt><dd><a href={selected.facts.entry.origin_url} target="_blank" rel="noreferrer">{selected.facts.entry.link_text || "查看入口来源"} ↗</a></dd></div>
        </dl></div>}
        <a href={selected.source_url} target="_blank" rel="noreferrer">打开官方{selected.batch === "campus" ? "专题" : "公告"} ↗</a>
      </>}
    </dialog>
  </section>;
}
