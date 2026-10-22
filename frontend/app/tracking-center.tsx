"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiError } from "./api-error";
import { parseApiTimestamp } from "./api-time";
import FollowUpWorkspace from "./follow-up-workspace";
import PortalTracking from "./portal-tracking";
import type { SearchGoal } from "./search-goal-controls";

type TrackingTask = {
  id: string; application_id: string; title: string; company: string | null; job_title: string | null;
  scheduled_at: string; local_scheduled_at: string; reminder_at: string; all_day: boolean;
  is_overdue: boolean; next_action: string;
};
type SearchTracking = { goal: SearchGoal; latest_run: null | {
  id: string; status: string; started_at: string; finished_at: string | null; new_count: number;
} };
type Snapshot = {
  checked_at: string; scheduler_running: boolean; searches: SearchTracking[]; tasks: TrackingTask[];
  counts: { scheduled_goals: number; today: number; overdue: number; attention: number };
};
type JobUpdate = { kind: "new" | "changed" | "closed"; job_posting_id: string; title: string; company: string | null };

const timeText = (value?: string | null) => value ? parseApiTimestamp(value).toLocaleString("zh-CN", {
  timeZone: "Asia/Shanghai", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
}) : "尚未更新";

export default function TrackingCenter({ apiUrl, userId, onSelectGoal, onOpenBoard, onScheduleChange }: {
  apiUrl: string; userId: string; onSelectGoal: (goal: SearchGoal) => void;
  onOpenBoard: () => void; onScheduleChange: () => void;
}) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"jobs" | "tasks">("jobs");
  const [managedApplication, setManagedApplication] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [changes, setChanges] = useState<Record<string, JobUpdate[]>>({});
  const [expandedGoal, setExpandedGoal] = useState<string | null>(null);
  const [changeError, setChangeError] = useState("");
  const [notifications, setNotifications] = useState(false);
  const [notificationNote, setNotificationNote] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const inFlight = useRef(false);
  const notified = useRef<Record<string, number>>({});
  const notificationKey = `jobflow:tracking-notifications:${userId}`;
  const seenKey = `jobflow:tracking-notified:${userId}`;

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const response = await fetch(`${apiUrl}/api/tracking/summary`, { headers: { "X-User-ID": userId }, cache: "no-store" });
      if (!response.ok) throw new Error("追踪状态暂时无法更新，请检查本地服务。");
      const data = await response.json() as Snapshot;
      if (!Array.isArray(data.searches) || !Array.isArray(data.tasks) || !data.counts) throw new Error("追踪状态暂时无法更新，请刷新重试。");
      setSnapshot(data); setError("");
    } catch (e) { setError(e instanceof Error ? e.message : "追踪状态读取失败"); }
    finally { inFlight.current = false; }
  }, [apiUrl, userId]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 30_000);
    const refresh = () => void load();
    window.addEventListener("focus", refresh);
    window.addEventListener("jobflow:tracking-changed", refresh);
    try { setNotifications("Notification" in window && Notification.permission === "granted" && localStorage.getItem(notificationKey) === "on"); } catch { /* Optional storage. */ }
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      window.removeEventListener("jobflow:tracking-changed", refresh);
    };
  }, [load, notificationKey]);

  function open() { setManagedApplication(null); dialog.current?.showModal(); void load(); }

  useEffect(() => {
    if (!notifications || !snapshot || error || !("Notification" in window) || Notification.permission !== "granted") return;
    // Keys include the schedule: moving an interview allows a fresh reminder.
    let seen: Record<string, number> = { ...notified.current };
    try {
      const saved = JSON.parse(localStorage.getItem(seenKey) || "{}");
      if (saved && typeof saved === "object" && !Array.isArray(saved)) seen = { ...seen, ...saved };
    } catch { /* Optional storage. */ }
    const now = Date.now();
    seen = Object.fromEntries(Object.entries(seen).filter(([, at]) => typeof at === "number" && now - at < 35 * 86400000));
    const due = snapshot.tasks.filter(task => {
      const remindAt = parseApiTimestamp(task.reminder_at).getTime();
      const eventAt = parseApiTimestamp(task.scheduled_at).getTime();
      return now >= remindAt && now - eventAt < 86400000 && !seen[`${task.id}:${task.scheduled_at}`];
    });
    if (!due.length) return;
    try {
      const notice = new Notification(due.length === 1 ? due[0].title : `有 ${due.length} 项求职事项需要处理`, {
        body: due.length === 1 ? `${due[0].company || "待跟进申请"} · ${due[0].all_day ? "今天" : timeText(due[0].scheduled_at)}\n${due[0].next_action}` : "打开 JobFlow 查看面试、测评与跟进安排。",
        tag: "jobflow-follow-ups",
      });
      notice.onclick = () => { window.focus(); setTab("tasks"); open(); notice.close(); };
      due.forEach(task => { seen[`${task.id}:${task.scheduled_at}`] = now; });
      notified.current = seen;
      try { localStorage.setItem(seenKey, JSON.stringify(seen)); } catch { /* Keep deduplication for this page session. */ }
    } catch { setNotificationNote("桌面提醒暂不可用，事项仍保留在跟进列表。"); }
  }, [snapshot, notifications, error, seenKey]);

  async function toggleNotifications() {
    if (notifications) {
      setNotifications(false);
      try { localStorage.setItem(notificationKey, "off"); } catch { /* Optional storage. */ }
      return;
    }
    if (!("Notification" in window)) { setNotificationNote("当前浏览器不支持桌面提醒，可导出日历安排提醒。"); return; }
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") { setNotificationNote("浏览器未允许通知；可以在网站权限中开启，或使用日历提醒。"); return; }
      setNotifications(true); setNotificationNote("");
      localStorage.setItem(notificationKey, "on");
    } catch { setNotificationNote("无法开启桌面提醒，请检查浏览器的网站权限。"); }
  }

  async function saveSchedule(goal: SearchGoal, interval: number) {
    setSaving(goal.id); setError("");
    try {
      const response = await fetch(`${apiUrl}/api/discovery/goals/${goal.id}/schedule`, {
        method: "PUT", headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({ expected_version: goal.version, interval_minutes: interval }),
      });
      if (!response.ok) throw new Error(apiError(await response.json(), "更新频率保存失败"));
      await load(); onScheduleChange();
    } catch (e) { setError(e instanceof Error ? e.message : "更新频率保存失败"); }
    finally { setSaving(null); }
  }

  async function showChanges(goalId: string) {
    if (expandedGoal === goalId) { setExpandedGoal(null); return; }
    setExpandedGoal(goalId); setChangeError("");
    try {
      const response = await fetch(`${apiUrl}/api/discovery/goals/${goalId}/library?include_progress=false`, { headers: { "X-User-ID": userId }, cache: "no-store" });
      if (!response.ok) throw new Error("岗位变化读取失败，请重试。");
      const data = await response.json();
      setChanges(old => ({ ...old, [goalId]: data.updates || [] }));
    } catch (e) { setChangeError(e instanceof Error ? e.message : "岗位变化读取失败"); }
  }

  return <>
    <button type="button" className="tracking-trigger" onClick={open} aria-label={`追踪动态${snapshot?.counts.attention ? `，${snapshot.counts.attention} 项待处理` : ""}`}>
      追踪动态{Boolean(snapshot?.counts.attention) && <span>{snapshot!.counts.attention}</span>}
    </button>
    <dialog ref={dialog} className="tracking-dialog" aria-label="追踪动态" onClose={() => { setManagedApplication(null); void load(); }} onClick={e => { if (e.target === e.currentTarget) dialog.current?.close(); }}>
      <header><div><h2>{managedApplication !== null ? "安排后续跟进" : "追踪动态"}</h2><p>岗位更新、投递进度与待办事项</p></div><button type="button" onClick={() => dialog.current?.close()} aria-label="关闭追踪动态">关闭 ×</button></header>
      {managedApplication !== null ? <>
        <button type="button" className="quiet-button" onClick={() => { setManagedApplication(null); void load(); }}>← 返回追踪动态</button>
        <FollowUpWorkspace apiUrl={apiUrl} userId={userId} initialApplicationId={managedApplication || undefined} />
      </> : <>
        <div className="tracking-tabs" role="tablist" aria-label="追踪类型">
          {(["jobs", "tasks"] as const).map(id => <button key={id} type="button" role="tab" aria-selected={tab === id}
            id={`tracking-tab-${id}`} aria-controls={`tracking-panel-${id}`} tabIndex={tab === id ? 0 : -1}
            onKeyDown={event => {
              if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
              event.preventDefault();
              const next = event.key === "Home" ? "jobs" : event.key === "End" ? "tasks" : id === "jobs" ? "tasks" : "jobs";
              setTab(next); document.getElementById(`tracking-tab-${next}`)?.focus();
            }} onClick={() => setTab(id)}>{id === "jobs" ? "岗位追踪" : "投递跟进"}</button>)}
        </div>
        {error && <p role="alert" className="tracking-error">{error} <button type="button" onClick={() => void load()}>重试</button></p>}
        {!snapshot && !error && <p>正在读取追踪记录…</p>}
        {tab === "jobs" ? <section id="tracking-panel-jobs" role="tabpanel" aria-labelledby="tracking-tab-jobs">
          <p className="tracking-note">{snapshot?.scheduler_running ? "后台服务正在运行，关闭网页后仍会按计划搜索。" : "自动搜索需要保持后端服务运行。"} 电脑休眠或关机期间暂停。</p>
          {snapshot?.searches.length === 0 && <p className="tracking-empty">先保存一条求职需求，再设置更新频率。</p>}
          {snapshot?.searches.map(({ goal, latest_run: run }) => <article className="tracking-goal" key={goal.id}>
            <h3>{goal.input_text}</h3>
            <div className="tracking-goal-controls"><label>更新频率<select aria-label={`${goal.name}的更新频率`} value={goal.update_interval_minutes || 0} disabled={saving === goal.id} onChange={e => void saveSchedule(goal, Number(e.target.value))}>
              <option value={0}>手动更新</option><option value={30}>每 30 分钟</option><option value={60}>每小时</option>
            </select></label><button type="button" onClick={() => { dialog.current?.close(); onSelectGoal(goal); }}>查看岗位</button></div>
            <p className="tracking-note">{run ? run.status === "RUNNING" ? `正在搜索 · ${timeText(run.started_at)} 开始` : `最近搜索：${timeText(run.finished_at)} · ${{ SUCCEEDED: "已完成", PARTIAL: "部分完成", FAILED: "失败，等待重试" }[run.status] || run.status}` : "尚未按当前条件搜索"}</p>
            {!!goal.update_interval_minutes && <p className="tracking-note">下一次：{timeText(goal.next_update_at)}</p>}
            {goal.schedule_error && <p className="tracking-error">{goal.schedule_error}</p>}
            {run && <button className="quiet-button" type="button" aria-expanded={expandedGoal === goal.id} onClick={() => void showChanges(goal.id)}>查看本轮新增与变化</button>}
            {expandedGoal === goal.id && <div className="tracking-changes">{changeError ? <p role="alert">{changeError}</p> : !changes[goal.id] ? <p>正在读取…</p> : !changes[goal.id].length ? <p>本轮尚未发现新增、内容变更或关闭。</p> : changes[goal.id].map(update => <p key={`${update.kind}:${update.job_posting_id}`}><span>{{ new: "新增", changed: "变更", closed: "关闭" }[update.kind]}</span>{update.company} · {update.title}</p>)}</div>}
          </article>)}
        </section> : <section id="tracking-panel-tasks" role="tabpanel" aria-labelledby="tracking-tab-tasks">
          <PortalTracking apiUrl={apiUrl} userId={userId} />
          <div className="tracking-task-tools"><p>今日 {snapshot?.counts.today || 0} 项 · 逾期 {snapshot?.counts.overdue || 0} 项</p><button type="button" onClick={() => setManagedApplication("")}>安排跟进</button><button type="button" onClick={() => { dialog.current?.close(); onOpenBoard(); }}>查看申请进度</button></div>
          <div className="tracking-notifications"><button type="button" onClick={() => void toggleNotifications()}>{notifications ? "关闭桌面提醒" : "开启桌面提醒"}</button><small>网页保持打开时，提前 30 分钟提醒；全天事项当天 9 点提醒。也可在任务中导出带提醒的日历。</small></div>
          {notificationNote && <p role="status" className="tracking-note">{notificationNote}</p>}
          {snapshot?.tasks.length === 0 && <p className="tracking-empty">暂无待办。登记已投递申请后，可以安排面试、测评或主动跟进。</p>}
          {snapshot?.tasks.map(task => <article className="tracking-task" key={task.id}><div><span className={task.is_overdue ? "tracking-error" : "tracking-note"}>{task.is_overdue ? "已逾期 · " : ""}{timeText(task.scheduled_at)}{task.all_day ? " · 全天" : ""}</span><h3>{task.title}</h3><p>{task.company || "公司待确认"} · {task.job_title}</p><p className="tracking-note">{task.next_action}</p></div><button type="button" onClick={() => setManagedApplication(task.application_id)}>查看跟进</button></article>)}
        </section>}
      </>}
    </dialog>
  </>;
}
