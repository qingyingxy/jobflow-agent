"use client";

import { useCallback, useEffect, useState } from "react";
import { apiError } from "./api-error";
import { parseApiTimestamp } from "./api-time";

type RecordItem = { id: string; title: string; location: string; recruitment_type: string;
  submitted_at_text: string; raw_status: string; application_id: string | null; missing: boolean;
  last_seen_at: string; changed_at: string;
  history: { at: string; previous_status: string | null; raw_status: string }[] };
type Source = { id: string; url: string; company: string; state: string; error: string | null;
  checked_at: string | null; succeeded_at: string | null; records: RecordItem[] };
type Application = { id: string; job: { company: string | null; title: string | null } };
type PortalResult = { state: string; page_url: string; complete: boolean; rows: unknown[] };
const time = (value: string | null) => value ? parseApiTimestamp(value).toLocaleString("zh-CN", {
  timeZone: "Asia/Shanghai", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
}) : "尚未同步";

export function browserRequest(action: "ping" | "sync", url?: string): Promise<PortalResult | undefined> {
  return new Promise((resolve, reject) => {
    const id = crypto.randomUUID();
    const timer = window.setTimeout(() => {
      window.removeEventListener("message", listener);
      reject(new Error(action === "ping" ? "请先连接浏览器辅助组件，再刷新本页。" : "同步超时，已有记录已保留，请重试。"));
    }, action === "ping" ? 1800 : 85000);
    function listener(event: MessageEvent) {
      if (event.source !== window || event.origin !== location.origin || event.data?.channel !== "jobflow-portal-response" || event.data.id !== id) return;
      clearTimeout(timer); window.removeEventListener("message", listener);
      if (event.data.ok) resolve(event.data.data);
      else reject(new Error(event.data.error || "浏览器连接暂不可用，请刷新页面。"));
    }
    window.addEventListener("message", listener);
    window.postMessage({ channel: "jobflow-portal-request", id, action, url }, location.origin);
  });
}

export default function PortalTracking({ apiUrl, userId }: { apiUrl: string; userId: string }) {
  const [sources, setSources] = useState<Source[]>([]);
  const [applications, setApplications] = useState<Application[]>([]);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [connected, setConnected] = useState(false);
  const [setup, setSetup] = useState(false);
  const [adding, setAdding] = useState(false);
  const headers = { "X-User-ID": userId, "Content-Type": "application/json" };

  const load = useCallback(async () => {
    const result = await fetch(`${apiUrl}/api/portal-tracking`, { headers: { "X-User-ID": userId }, cache: "no-store" });
    if (!result.ok) throw new Error("官网跟进记录暂时无法读取，请重试。");
    const body = await result.json();
    setSources(body.sources || []);
    const apps = await fetch(`${apiUrl}/api/applications`, { headers: { "X-User-ID": userId }, cache: "no-store" });
    if (apps.ok) setApplications(await apps.json());
  }, [apiUrl, userId]);

  useEffect(() => {
    void load().catch(e => setError(e.message));
    void browserRequest("ping").then(() => setConnected(true)).catch(() => setConnected(false));
  }, [load]);

  async function post(path: string, body: unknown, method = "POST") {
    const response = await fetch(`${apiUrl}/api/portal-tracking${path}`, { method, headers, body: JSON.stringify(body) });
    const result = await response.json();
    if (!response.ok) throw new Error(apiError(result, "保存失败，请重试。"));
    return result;
  }

  async function connect() {
    setBusy("connect"); setError(""); setNotice("");
    try {
      await post("", { url: url.trim() });
      await load(); setUrl(""); setAdding(false); setNotice("链接已保存，点击一键同步即可读取官网进度。");
    } catch (e) { setError(e instanceof Error ? e.message : "连接失败"); }
    finally { setBusy(""); }
  }

  async function sync(source: Source) {
    setBusy(source.id); setError(""); setNotice("");
    let token: string | undefined;
    let reported = false;
    try {
      await browserRequest("ping"); setConnected(true);
      token = (await post(`/${source.id}/sync`, {})).token;
      const result = await browserRequest("sync", source.url);
      if (!result) throw new Error("未收到官网结果，请重试。");
      const count = await post(`/${source.id}/report`, { token, ...result });
      reported = true;
      await load();
      if (result.state === "READY") setNotice(`同步完成：新增 ${count.new} 条，状态变化 ${count.changed} 条。`);
      window.dispatchEvent(new Event("jobflow:tracking-changed"));
    } catch (e) {
      if (!token) { setConnected(false); setSetup(true); }
      if (token && !reported) {
        try { await post(`/${source.id}/report`, { token, state: "ERROR", page_url: source.url, complete: false, rows: [] }); await load(); } catch { /* A newer request may have superseded this one. */ }
      }
      setError(e instanceof Error ? e.message : "同步失败，原有记录已保留。");
    } finally { setBusy(""); }
  }

  async function link(record: RecordItem, applicationId: string) {
    setBusy(record.id); setError("");
    try {
      await post(`/records/${record.id}/application`, { application_id: applicationId || null }, "PUT");
      await load(); window.dispatchEvent(new Event("jobflow:tracking-changed"));
    } catch (e) { setError(e instanceof Error ? e.message : "关联失败"); }
    finally { setBusy(""); }
  }

  return <section className="portal-tracking" aria-label="官网申请进度">
    <div className="portal-heading"><div><h3>官网申请进度</h3><p>读取个人投递记录，保留官网状态和变化历史。</p></div>
      <button type="button" onClick={() => setAdding(!adding)} aria-expanded={adding}>添加官网链接</button></div>
    {(adding || sources.length === 0) && <form className="portal-connect" onSubmit={e => { e.preventDefault(); void connect(); }}>
      <label htmlFor="portal-url">个人投递记录页链接</label>
      <div><input id="portal-url" type="url" value={url} required onChange={e => setUrl(e.target.value)} placeholder="https://mhr.ly.com/recruit/schoolPortal/#/personal" /><button type="submit" disabled={!!busy || !url.trim()}>保存链接</button></div>
      <small>目前支持同程校招个人页，其他官网逐步接入。</small>
    </form>}
    <div className="portal-connection"><span>{connected ? "浏览器已连接" : "浏览器尚未连接"}</span><button type="button" className="quiet-button" onClick={() => setSetup(!setup)} aria-expanded={setup}>{setup ? "收起连接说明" : "首次连接说明"}</button></div>
    {setup && <div className="portal-setup">
      <p>在 Chrome 或 Edge 中安装辅助组件，并在同一浏览器打开 JobFlow。</p>
      <ol><li><a href="/jobflow-portal-extension.zip" download>下载辅助组件</a>并解压。</li><li>打开浏览器的扩展管理，开启开发者模式，选择“加载已解压的扩展程序”，选中解压后的文件夹。</li><li>刷新 JobFlow，点击“一键同步”；若提示登录，在新打开的同程页面完成登录后再次同步。</li></ol>
      <p>只读取同程的申请表格，结果保存在本机。登录态留在浏览器中。手机和 Codex 内置浏览器暂不支持安装此组件。</p>
    </div>}
    {error && <p className="tracking-error" role="alert">{error}</p>}
    {notice && <p className="portal-notice" role="status">{notice}</p>}
    {sources.map(source => <article className="portal-source" key={source.id}>
      <div className="portal-source-heading"><div><strong>{source.company}</strong><small>上次成功：{time(source.succeeded_at)}</small></div><div><a href={source.url} target="_blank" rel="noreferrer">打开官网 ↗</a><button type="button" disabled={!!busy} onClick={() => void sync(source)}>{busy === source.id ? "正在读取官网…" : "一键同步"}</button></div></div>
      {source.error && <p role="status" className="tracking-error">{source.error}<small> 最近检查：{time(source.checked_at)}</small></p>}
      {source.records.length === 0 && <p className="tracking-note">{source.state === "READY" ? "官网当前没有申请记录。" : "链接已保存，尚未读取到申请记录。"}</p>}
      {source.records.map(record => <div className="portal-record" key={record.id}>
        <div className="portal-record-title"><h4>{record.title}</h4><span>{record.raw_status}</span></div>
        <p>{record.location} · {record.recruitment_type}</p>
        <p className="tracking-note">投递于 {record.submitted_at_text} · 最近看到 {time(record.last_seen_at)}</p>
        {record.missing && <p className="tracking-note">本次页面未找到这条记录，已保留上次状态。</p>}
        <details><summary>变化记录与关联申请</summary>
          <ul>{record.history.map((h, i) => <li key={i}><time>{time(h.at)}</time> {h.previous_status ? `${h.previous_status} → ${h.raw_status}` : `首次读取：${h.raw_status}`}</li>)}</ul>
          {applications.length > 0 ? <label>关联到申请进度<select aria-label={`关联申请 ${record.title}`} disabled={!!busy} value={record.application_id || ""} onChange={e => void link(record, e.target.value)}><option value="">暂不关联</option>{applications.map(application => <option value={application.id} key={application.id}>{application.job.company} · {application.job.title}</option>)}</select></label> : <p className="tracking-note">添加到申请进度后，可在这里关联已有申请。</p>}
          <small>关联后，官网变化会进入该申请的时间线。“进行中”等笼统状态不会推断为面试。</small>
        </details>
      </div>)}
    </article>)}
  </section>;
}
