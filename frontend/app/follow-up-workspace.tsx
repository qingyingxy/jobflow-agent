"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

type FollowUpView = "today" | "overdue" | "next_7_days" | "next_30_days" | "all";
type FollowUpEventType = "ASSESSMENT" | "WRITTEN_TEST" | "INTERVIEW" | "MATERIAL_DEADLINE" | "OUTREACH" | "CUSTOM";
type FollowUpStatus = "PENDING" | "OVERDUE" | "COMPLETED" | "CANCELLED";

type ApplicationItem = {
  id: string;
  status: "PREPARING" | "SUBMITTED" | "ASSESSMENT" | "INTERVIEW" | "OFFER" | "REJECTED" | "WITHDRAWN";
  job: {
    company: string | null;
    title: string | null;
  };
};

type FollowUpTask = {
  id: string;
  application_id: string;
  job_posting_id: string;
  event_type: FollowUpEventType;
  title: string;
  scheduled_at: string;
  local_scheduled_at: string;
  timezone: string;
  duration_minutes: number | null;
  all_day: boolean;
  contact_name: string | null;
  contact_detail: string | null;
  channel: string | null;
  next_action: string;
  notes: string | null;
  status: FollowUpStatus;
  base_status: "PENDING" | "COMPLETED" | "CANCELLED";
  is_overdue: boolean;
  available_actions: Array<"edit" | "complete" | "cancel">;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  cancelled_at: string | null;
};

type FollowUpSummary = {
  timezone: string;
  generated_at: string;
  total_pending: number;
  today: number;
  overdue: number;
  next_7_days: number;
  next_30_days: number;
};

type FollowUpDraft = {
  application_id: string;
  event_type: FollowUpEventType;
  title: string;
  scheduled_at: string;
  timezone: string;
  duration_minutes: string;
  all_day: boolean;
  contact_name: string;
  contact_detail: string;
  channel: string;
  next_action: string;
  notes: string;
};

const followableStatuses = new Set(["SUBMITTED", "ASSESSMENT", "INTERVIEW", "OFFER"]);

const viewOptions: Array<{ id: FollowUpView; label: string; metric: keyof FollowUpSummary | null }> = [
  { id: "today", label: "今日", metric: "today" },
  { id: "overdue", label: "逾期", metric: "overdue" },
  { id: "next_7_days", label: "未来 7 天", metric: "next_7_days" },
  { id: "next_30_days", label: "未来 30 天", metric: "next_30_days" },
  { id: "all", label: "全部记录", metric: null },
];

const eventTypeLabel: Record<FollowUpEventType, string> = {
  ASSESSMENT: "在线测评",
  WRITTEN_TEST: "笔试",
  INTERVIEW: "面试",
  MATERIAL_DEADLINE: "材料截止",
  OUTREACH: "主动跟进",
  CUSTOM: "自定义",
};

const statusLabel: Record<FollowUpStatus, string> = {
  PENDING: "待处理",
  OVERDUE: "已逾期",
  COMPLETED: "已完成",
  CANCELLED: "已取消",
};

const eventOptions = Object.entries(eventTypeLabel) as Array<[FollowUpEventType, string]>;

function defaultTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Shanghai";
  } catch {
    return "Asia/Shanghai";
  }
}

function defaultSchedule(): string {
  const next = new Date();
  next.setDate(next.getDate() + 1);
  next.setHours(10, 0, 0, 0);
  const year = next.getFullYear();
  const month = String(next.getMonth() + 1).padStart(2, "0");
  const day = String(next.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}T10:00`;
}

function emptyDraft(applicationId = ""): FollowUpDraft {
  return {
    application_id: applicationId,
    event_type: "INTERVIEW",
    title: "",
    scheduled_at: defaultSchedule(),
    timezone: defaultTimezone(),
    duration_minutes: "60",
    all_day: false,
    contact_name: "",
    contact_detail: "",
    channel: "",
    next_action: "",
    notes: "",
  };
}

async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { error?: { message?: string } };
    return payload.error?.message ?? `请求失败（${response.status}）`;
  } catch {
    return `请求失败（${response.status}）`;
  }
}

function dateKey(value: string): string {
  return value.slice(0, 10);
}

function formatLocalDate(value: string): string {
  const [year, month, day] = dateKey(value).split("-");
  return `${year} 年 ${Number(month)} 月 ${Number(day)} 日`;
}

function formatLocalTime(task: FollowUpTask): string {
  if (task.all_day) return "全天";
  return task.local_scheduled_at.slice(11, 16);
}

function applicationName(application: ApplicationItem | undefined): string {
  if (!application) return "未知申请";
  return `${application.job.company ?? "未命名公司"} / ${application.job.title ?? "未命名岗位"}`;
}

export default function FollowUpWorkspace({ apiUrl, userId }: { apiUrl: string; userId: string }) {
  const [view, setView] = useState<FollowUpView>("today");
  const [applications, setApplications] = useState<ApplicationItem[]>([]);
  const [tasks, setTasks] = useState<FollowUpTask[]>([]);
  const [calendarTasks, setCalendarTasks] = useState<FollowUpTask[]>([]);
  const [summary, setSummary] = useState<FollowUpSummary | null>(null);
  const [applicationFilter, setApplicationFilter] = useState("all");
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [draft, setDraft] = useState<FollowUpDraft>(() => emptyDraft());
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");

  const timezone = draft.timezone || "Asia/Shanghai";

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const headers = { "X-User-ID": userId };
      const queryTimezone = encodeURIComponent(timezone);
      const [applicationResponse, taskResponse, calendarResponse, summaryResponse] = await Promise.all([
        fetch(`${apiUrl}/api/applications`, { headers, cache: "no-store" }),
        fetch(`${apiUrl}/api/follow-ups?view=${view}&timezone=${queryTimezone}`, { headers, cache: "no-store" }),
        fetch(`${apiUrl}/api/follow-ups?view=all&timezone=${queryTimezone}`, { headers, cache: "no-store" }),
        fetch(`${apiUrl}/api/follow-ups/summary?timezone=${queryTimezone}`, { headers, cache: "no-store" }),
      ]);
      if (!applicationResponse.ok) throw new Error(await readError(applicationResponse));
      if (!taskResponse.ok) throw new Error(await readError(taskResponse));
      if (!calendarResponse.ok) throw new Error(await readError(calendarResponse));
      if (!summaryResponse.ok) throw new Error(await readError(summaryResponse));
      const nextApplications = (await applicationResponse.json()) as ApplicationItem[];
      const nextTasks = (await taskResponse.json()) as FollowUpTask[];
      const nextCalendarTasks = (await calendarResponse.json()) as FollowUpTask[];
      const nextSummary = (await summaryResponse.json()) as FollowUpSummary;
      setApplications(nextApplications);
      setTasks(nextTasks);
      setCalendarTasks(nextCalendarTasks);
      setSummary(nextSummary);
      const firstFollowable = nextApplications.find((item) => followableStatuses.has(item.status));
      setDraft((current) => current.application_id || !firstFollowable ? current : { ...current, application_id: firstFollowable.id });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "跟进任务加载失败。");
    } finally {
      setLoading(false);
    }
  }, [apiUrl, timezone, userId, view]);

  useEffect(() => {
    void load();
  }, [load]);

  const applicationMap = useMemo(() => new Map(applications.map((item) => [item.id, item])), [applications]);
  const followableApplications = applications.filter((item) => followableStatuses.has(item.status));
  const visibleTasks = tasks.filter((task) => {
    if (applicationFilter !== "all" && task.application_id !== applicationFilter) return false;
    if (selectedDate && dateKey(task.local_scheduled_at) !== selectedDate) return false;
    return true;
  });
  const groupedTasks = useMemo(() => {
    const groups = new Map<string, FollowUpTask[]>();
    for (const task of visibleTasks) {
      const key = dateKey(task.local_scheduled_at);
      groups.set(key, [...(groups.get(key) ?? []), task]);
    }
    return [...groups.entries()];
  }, [visibleTasks]);

  const calendarDays = useMemo(() => {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    return Array.from({ length: 30 }, (_, index) => {
      const date = new Date(start);
      date.setDate(start.getDate() + index);
      const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
      const dayTasks = calendarTasks.filter((task) => dateKey(task.local_scheduled_at) === key && task.base_status === "PENDING");
      return { key, date, tasks: dayTasks };
    });
  }, [calendarTasks]);

  async function mutate(path: string, init: RequestInit, successMessage: string) {
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
      return true;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "操作失败，请重试。");
      return false;
    } finally {
      setWorking(false);
    }
  }

  function taskPayload() {
    return {
      event_type: draft.event_type,
      title: draft.title.trim(),
      scheduled_at: draft.scheduled_at,
      timezone: draft.timezone.trim(),
      duration_minutes: draft.all_day || !draft.duration_minutes ? null : Number(draft.duration_minutes),
      all_day: draft.all_day,
      contact_name: draft.contact_name.trim() || null,
      contact_detail: draft.contact_detail.trim() || null,
      channel: draft.channel.trim() || null,
      next_action: draft.next_action.trim(),
      notes: draft.notes.trim() || null,
    };
  }

  async function saveTask() {
    if (!draft.application_id || !draft.title.trim() || !draft.next_action.trim() || !draft.scheduled_at) {
      setMessage("请选择申请，并填写标题、时间和下一步动作。");
      return;
    }
    const success = editingTaskId
      ? await mutate(`/api/follow-ups/${editingTaskId}`, { method: "PATCH", body: JSON.stringify(taskPayload()) }, "跟进任务已更新，申请状态保持不变。")
      : await mutate(`/api/applications/${draft.application_id}/follow-ups`, { method: "POST", body: JSON.stringify(taskPayload()) }, "跟进任务已创建，并写入申请时间线。 ");
    if (success) {
      setEditingTaskId(null);
      setDraft(emptyDraft(draft.application_id));
    }
  }

  function startEdit(task: FollowUpTask) {
    setEditingTaskId(task.id);
    setDraft({
      application_id: task.application_id,
      event_type: task.event_type,
      title: task.title,
      scheduled_at: task.local_scheduled_at.slice(0, 16),
      timezone: task.timezone,
      duration_minutes: task.duration_minutes?.toString() ?? "",
      all_day: task.all_day,
      contact_name: task.contact_name ?? "",
      contact_detail: task.contact_detail ?? "",
      channel: task.channel ?? "",
      next_action: task.next_action,
      notes: task.notes ?? "",
    });
    document.querySelector(".follow-up-editor")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function stopEdit() {
    setEditingTaskId(null);
    setDraft(emptyDraft(draft.application_id));
  }

  async function completeTask(taskId: string) {
    await mutate(`/api/follow-ups/${taskId}/complete`, { method: "POST", body: "{}" }, "任务已完成；这不会自动改变申请阶段。 ");
  }

  async function cancelTask(taskId: string) {
    await mutate(`/api/follow-ups/${taskId}/cancel`, { method: "POST", body: "{}" }, "任务已取消，历史记录仍保留在时间线。 ");
  }

  return (
    <section className="follow-up-workspace">
      <header className="follow-up-command">
        <div><span>FOLLOW-UP CONTROL</span><strong>{summary?.total_pending ?? 0} 项待处理</strong></div>
        <div className="follow-up-view-tabs" role="tablist" aria-label="跟进时间范围">
          {viewOptions.map((option) => (
            <button className={view === option.id ? "follow-up-view-active" : ""} key={option.id} onClick={() => { setView(option.id); setSelectedDate(null); }} role="tab" aria-selected={view === option.id} type="button">
              <span>{option.label}</span><strong>{option.metric && summary ? summary[option.metric] : calendarTasks.length}</strong>
            </button>
          ))}
        </div>
        <button className="follow-up-refresh" onClick={() => void load()} disabled={working} title="刷新跟进中心" aria-label="刷新跟进中心" type="button">↻</button>
      </header>

      {message ? <div className="follow-up-message" role="status">{message}</div> : null}

      <div className="follow-up-calendar-band">
        <div className="follow-up-band-heading"><span>01 / 30 DAYS</span><strong>日期矩阵</strong><p>选择一天收窄当前任务列表。</p></div>
        <div className="follow-up-calendar" aria-label="未来三十天跟进日历">
          {calendarDays.map((day, index) => (
            <button className={`${selectedDate === day.key ? "follow-up-day follow-up-day-active" : "follow-up-day"} ${day.tasks.some((task) => task.is_overdue) ? "follow-up-day-overdue" : ""}`} key={day.key} onClick={() => setSelectedDate((current) => current === day.key ? null : day.key)} type="button" aria-label={`${day.key}，${day.tasks.length} 项任务`}>
              <span>{index === 0 ? "TODAY" : day.date.toLocaleDateString("zh-CN", { weekday: "short" })}</span>
              <strong>{day.date.getDate()}</strong>
              <small>{day.tasks.length ? `${day.tasks.length} TASK` : "—"}</small>
            </button>
          ))}
        </div>
      </div>

      <div className="follow-up-layout">
        <section className="follow-up-agenda">
          <header className="follow-up-section-heading">
            <div><span>02 / AGENDA</span><h2>{viewOptions.find((item) => item.id === view)?.label}任务</h2></div>
            <label><span>申请筛选</span><select value={applicationFilter} onChange={(event) => setApplicationFilter(event.target.value)}><option value="all">全部申请</option>{applications.map((application) => <option key={application.id} value={application.id}>{applicationName(application)}</option>)}</select></label>
          </header>

          {loading ? <div className="follow-up-empty">正在加载跟进任务…</div> : null}
          {!loading && groupedTasks.length === 0 ? (
            <div className="follow-up-empty"><span>NO TASK IN VIEW</span><strong>当前范围没有待处理事项。</strong><p>可以从右侧为已提交申请创建测评、面试、截止日期或主动跟进任务。</p></div>
          ) : null}
          <div className="follow-up-groups">
            {groupedTasks.map(([date, dateTasks]) => (
              <section className="follow-up-date-group" key={date}>
                <header><time>{formatLocalDate(date)}</time><span>{dateTasks.length.toString().padStart(2, "0")}</span></header>
                {dateTasks.map((task) => (
                  <article className={`follow-up-task follow-up-task-${task.status.toLowerCase()}`} key={task.id}>
                    <div className="follow-up-task-time"><strong>{formatLocalTime(task)}</strong><span>{task.duration_minutes ? `${task.duration_minutes} MIN` : task.all_day ? "ALL DAY" : "OPEN"}</span></div>
                    <div className="follow-up-task-main">
                      <div className="follow-up-task-topline"><span>{eventTypeLabel[task.event_type]}</span><span className={`follow-up-status follow-up-status-${task.status.toLowerCase()}`}>{statusLabel[task.status]}</span></div>
                      <h3>{task.title}</h3>
                      <p>{applicationName(applicationMap.get(task.application_id))}</p>
                      <div className="follow-up-next"><span>下一步</span><strong>{task.next_action}</strong></div>
                      {task.contact_name || task.channel ? <div className="follow-up-contact"><span>{task.contact_name ?? "未记录联系人"}</span><span>{task.channel ?? "未记录渠道"}</span>{task.contact_detail ? <span>{task.contact_detail}</span> : null}</div> : null}
                    </div>
                    <div className="follow-up-task-actions">
                      {task.available_actions.includes("edit") ? <button onClick={() => startEdit(task)} disabled={working} title="编辑任务" aria-label={`编辑 ${task.title}`} type="button">✎</button> : null}
                      {task.available_actions.includes("complete") ? <button onClick={() => void completeTask(task.id)} disabled={working} title="完成任务" aria-label={`完成 ${task.title}`} type="button">✓</button> : null}
                      {task.available_actions.includes("cancel") ? <button onClick={() => void cancelTask(task.id)} disabled={working} title="取消任务" aria-label={`取消 ${task.title}`} type="button">×</button> : null}
                    </div>
                  </article>
                ))}
              </section>
            ))}
          </div>
        </section>

        <aside className="follow-up-editor">
          <header><span>03 / {editingTaskId ? "EDIT" : "NEW TASK"}</span><h2>{editingTaskId ? "修改跟进任务" : "安排下一步"}</h2><p>外部邮件和短信不会被自动采信；只记录你已经确认的时间与动作。</p></header>
          {followableApplications.length === 0 && !editingTaskId ? <div className="follow-up-editor-blocked">当前没有已提交且仍可跟进的申请。</div> : null}
          <label><span>关联申请</span><select value={draft.application_id} disabled={Boolean(editingTaskId)} onChange={(event) => setDraft((current) => ({ ...current, application_id: event.target.value }))}><option value="">选择申请</option>{followableApplications.map((application) => <option key={application.id} value={application.id}>{applicationName(application)}</option>)}</select></label>
          <div className="follow-up-editor-pair">
            <label><span>事件类型</span><select value={draft.event_type} onChange={(event) => setDraft((current) => ({ ...current, event_type: event.target.value as FollowUpEventType }))}>{eventOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
            <label><span>标题</span><input value={draft.title} onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))} placeholder="例如：技术二面" /></label>
          </div>
          <div className="follow-up-editor-pair">
            <label><span>日期与时间</span><input type="datetime-local" value={draft.scheduled_at} onChange={(event) => setDraft((current) => ({ ...current, scheduled_at: event.target.value }))} /></label>
            <label><span>时区</span><input value={draft.timezone} onChange={(event) => setDraft((current) => ({ ...current, timezone: event.target.value }))} placeholder="Asia/Shanghai" /></label>
          </div>
          <div className="follow-up-editor-pair follow-up-duration-row">
            <label><span>时长 / 分钟</span><input type="number" min="5" max="1440" step="5" disabled={draft.all_day} value={draft.duration_minutes} onChange={(event) => setDraft((current) => ({ ...current, duration_minutes: event.target.value }))} /></label>
            <label className="follow-up-check"><input type="checkbox" checked={draft.all_day} onChange={(event) => setDraft((current) => ({ ...current, all_day: event.target.checked }))} /><span>全天事项</span></label>
          </div>
          <div className="follow-up-editor-pair">
            <label><span>联系人</span><input value={draft.contact_name} onChange={(event) => setDraft((current) => ({ ...current, contact_name: event.target.value }))} placeholder="可选" /></label>
            <label><span>渠道</span><input value={draft.channel} onChange={(event) => setDraft((current) => ({ ...current, channel: event.target.value }))} placeholder="电话 / 会议 / 邮件" /></label>
          </div>
          <label><span>联系方式或会议号</span><input value={draft.contact_detail} onChange={(event) => setDraft((current) => ({ ...current, contact_detail: event.target.value }))} placeholder="仅保存在任务详情" /></label>
          <label><span>下一步动作</span><textarea value={draft.next_action} onChange={(event) => setDraft((current) => ({ ...current, next_action: event.target.value }))} rows={3} placeholder="写成一个可以执行的动作" /></label>
          <label><span>备注</span><textarea value={draft.notes} onChange={(event) => setDraft((current) => ({ ...current, notes: event.target.value }))} rows={4} placeholder="可选，不会写入普通事件日志" /></label>
          <div className="follow-up-editor-actions">
            {editingTaskId ? <button className="follow-up-editor-cancel" onClick={stopEdit} type="button">退出编辑</button> : null}
            <button className="follow-up-editor-save" onClick={() => void saveTask()} disabled={working || (!editingTaskId && followableApplications.length === 0)} type="button">{working ? "保存中…" : editingTaskId ? "保存修改" : "创建跟进任务"}</button>
          </div>
        </aside>
      </div>
    </section>
  );
}

