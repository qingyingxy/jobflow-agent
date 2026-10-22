"use client";
import { parseApiTimestamp } from "./api-time";
import { apiError } from "./api-error";
import SearchConditionSummary from "./search-condition-summary";

import { useEffect, useRef, useState, type ReactNode } from "react";

export type GoalConditions = {
  locations: string[]; preferred_locations: string[]; excluded_locations: string[];
  roles: string[]; preferred_roles?: string[]; excluded_roles: string[]; job_types: string[]; excluded_job_types: string[];
  graduation_years: number[]; keywords: string[]; preferred_keywords?: string[]; pending_conditions: string[];
};
export type SearchGoal = {
  id: string; name: string; input_text: string; query: string; version: number;
  conditions: GoalConditions; condition_sources: Record<string, string>;
  company_ids: string[] | null;
  update_interval_minutes?: number; next_update_at?: string | null; schedule_error?: string | null;
};
type GoalOverview = {
  goal_id: string; goal_version: number; counts: { recommended?: number; needs_review?: number; excluded?: number };
  review_status?: string; search_status?: string | null; checked_at?: string;
};

const labels: Record<keyof GoalConditions, string> = {
  locations: "必须地点", preferred_locations: "优先地点", excluded_locations: "排除地点",
  roles: "岗位方向", preferred_roles: "优先方向", excluded_roles: "排除方向", job_types: "招聘类型", excluded_job_types: "排除类型",
  graduation_years: "届别", keywords: "关键词", preferred_keywords: "优先关键词", pending_conditions: "待确认要求",
};
const parts = (value: string) => value.split(/[、,，;；\n]+/).map(v => v.trim()).filter(Boolean);
const conditionSignature = (conditions: GoalConditions) => JSON.stringify(
  (Object.keys(labels) as (keyof GoalConditions)[]).map(key => [...(conditions[key] || [])].sort()),
);

async function responseBody(response: Response) {
  const body = await response.json();
  if (!response.ok) {
    throw new Error(apiError(body, "条件保存失败，请检查输入后重试"));
  }
  return body;
}

export default function SearchGoalControls({ requestedGoal, apiUrl, userId, query, selectedCompanyIds, searching,
  refreshToken = 0, currentLibrary, historyContent, historyDates = {}, extraTools, onReload, onQueryChange, onGoalChange, onSearch }: {
  requestedGoal?: SearchGoal | null;
  apiUrl: string; userId: string; query: string; selectedCompanyIds: string[]; searching: boolean;
  refreshToken?: number; onReload: () => void;
  currentLibrary?: GoalOverview | null;
  historyContent?: ReactNode; historyDates?: Record<string, string>; extraTools?: ReactNode;
  onQueryChange: (value: string) => void; onGoalChange: (goal: SearchGoal | null) => void;
  onSearch: (goal: SearchGoal) => void;
}) {
  const [goals, setGoals] = useState<SearchGoal[]>([]);
  const [active, setActive] = useState<SearchGoal | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [overviews, setOverviews] = useState<Record<string, GoalOverview>>({});
  const [overviewError, setOverviewError] = useState(false);
  const [draft, setDraft] = useState<GoalConditions | null>(null);
  const [origins, setOrigins] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [loadingGoals, setLoadingGoals] = useState(true);
  const [goalsLoaded, setGoalsLoaded] = useState(false);
  const [notice, setNotice] = useState("");
  const [intervalMinutes, setIntervalMinutes] = useState(0);
  const [editorOpen, setEditorOpen] = useState(false);
  const [fieldTexts, setFieldTexts] = useState<Partial<Record<keyof GoalConditions, string>>>({});
  const historyDialog = useRef<HTMLDialogElement>(null);
  const searchInput = useRef<HTMLTextAreaElement>(null);
  const edited = useRef(false);
  const lock = useRef(false);
  const inputRevision = useRef(0);
  const goalListRevision = useRef(0);
  const storageKey = `jobflow-active-goal:${userId}`;
  const headers = { "Content-Type": "application/json", "X-User-ID": userId };

  useEffect(() => {
    const resize = () => {
      const input = searchInput.current;
      if (!input) return;
      input.style.height = "auto";
      input.style.height = `${Math.min(184, Math.max(64, input.scrollHeight + 2))}px`;
    };
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, [query]);

  function selectGoal(goal: SearchGoal | null) {
    historyDialog.current?.close();
    inputRevision.current += 1;
    edited.current = false;
    setActive(goal); setEditingId(null); setDraft(goal?.conditions || null); setEditorOpen(false);
    setFieldTexts({});
    setOrigins(goal?.condition_sources || {}); setError(""); setNotice(goal?.condition_sources?._intent_notice || "");
    onQueryChange(goal?.input_text || ""); onGoalChange(goal);
    try {
      if (goal) localStorage.setItem(storageKey, goal.id);
      else localStorage.removeItem(storageKey);
      setIntervalMinutes(goal?.update_interval_minutes || 0);
    } catch { setIntervalMinutes(0); }
  }

  useEffect(() => {
    if (requestedGoal) {
      selectGoal(requestedGoal);
      setGoals(old => [requestedGoal, ...old.filter(goal => goal.id !== requestedGoal.id)]);
    }
  }, [requestedGoal]);

  useEffect(() => {
    if (!active) return;
    const latest = goals.find(goal => goal.id === active.id && goal.version === active.version);
    if (latest && (latest.update_interval_minutes !== active.update_interval_minutes || latest.next_update_at !== active.next_update_at || latest.schedule_error !== active.schedule_error)) {
      setActive(current => current && ({ ...current, update_interval_minutes: latest.update_interval_minutes, next_update_at: latest.next_update_at, schedule_error: latest.schedule_error }));
      setIntervalMinutes(latest.update_interval_minutes || 0);
    }
  }, [goals]);

  useEffect(() => {
    const controller = new AbortController();
    const revision = inputRevision.current;
    const listRevision = goalListRevision.current;
    setLoadingGoals(true);
    void (async () => {
      try {
        const response = await fetch(`${apiUrl}/api/discovery/goals`, { headers, signal: controller.signal, cache: "no-store" });
        const list = await responseBody(response) as SearchGoal[];
        if (controller.signal.aborted) return;
        if (!Array.isArray(list)) throw new Error("求职目标数据格式异常，请重试");
        setGoalsLoaded(true); setLoadError("");
        if (listRevision !== goalListRevision.current) return;
        setGoals(list);
        if (revision !== inputRevision.current) return;
        // Reconnect refreshes the choices without resetting the selected goal or draft.
        if (!goalsLoaded && !edited.current && list.length) {
          let saved: string | null = null;
          try { saved = localStorage.getItem(storageKey); } catch { /* Storage is optional. */ }
          selectGoal(list.find(g => g.id === saved) || list[0]);
        }
      } catch (e) {
        if (!controller.signal.aborted) setLoadError(e instanceof Error ? e.message : "求职目标读取失败");
      } finally {
        if (!controller.signal.aborted) setLoadingGoals(false);
      }
    })();
    return () => controller.abort();
  }, [apiUrl, userId, refreshToken]);

  useEffect(() => {
    if (!goals.length) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(`${apiUrl}/api/discovery/goals/overview`, { headers, signal: controller.signal, cache: "no-store" });
        const rows = await responseBody(response) as GoalOverview[];
        if (!controller.signal.aborted && Array.isArray(rows)) {
          setOverviews(old => ({ ...old, ...Object.fromEntries(rows.map(row => [row.goal_id, row])) }));
          setOverviewError(false);
        }
      } catch { if (!controller.signal.aborted) setOverviewError(true); }
    })();
    return () => controller.abort();
  }, [apiUrl, userId, goals, refreshToken]);

  useEffect(() => {
    if (!currentLibrary) return;
    setOverviews(old => ({ ...old, [currentLibrary.goal_id]: { ...old[currentLibrary.goal_id], ...currentLibrary } }));
  }, [currentLibrary]);

  function editGoal(goal: SearchGoal) {
    selectGoal(goal); setEditingId(goal.id); setEditorOpen(true);
  }

  const textChanged = Boolean(active && query !== active.input_text);
  const companyChanged = Boolean(active && JSON.stringify([...selectedCompanyIds].sort()) !== JSON.stringify([...(active.company_ids || [])].sort()));
  const conditionsChanged = Boolean(draft && (!active || conditionSignature(draft) !== conditionSignature(active.conditions)));
  const dirty = textChanged || conditionsChanged || companyChanged;
  async function saveSchedule(interval: number) {
    if (!active || busy) return;
    setBusy(true); setError("");
    try {
      const goal = await responseBody(await fetch(`${apiUrl}/api/discovery/goals/${active.id}/schedule`, {
        method: "PUT", headers, body: JSON.stringify({ interval_minutes: interval, expected_version: active.version }),
      })) as SearchGoal;
      goalListRevision.current += 1;
      setActive(goal); setIntervalMinutes(goal.update_interval_minutes || 0);
      setGoals(list => list.map(item => item.id === goal.id ? goal : item)); onGoalChange(goal);
      window.dispatchEvent(new Event("jobflow:tracking-changed"));
    } catch (e) { setError(e instanceof Error ? e.message : "更新频率保存失败"); }
    finally { setBusy(false); }
  }

  async function interpret() {
    if (lock.current) return;
    if (active && query === active.input_text) {
      setEditingId(active.id);
      setDraft(current => current || active.conditions);
      setOrigins(current => Object.keys(current).length ? current : active.condition_sources);
      setEditorOpen(true);
      return;
    }
    const revision = inputRevision.current;
    lock.current = true; setBusy(true); setError("");
    try {
      const body = await responseBody(await fetch(`${apiUrl}/api/discovery/goals/interpret`, {
        method: "POST", headers, body: JSON.stringify({ input_text: query }),
      }));
      if (revision !== inputRevision.current) return;
      setDraft(body.conditions); setOrigins(body.condition_sources); setNotice(body.notice || "");
      setFieldTexts({});
      setEditorOpen(true);
    } catch (e) { setError(e instanceof Error ? e.message : "需求整理失败"); }
    finally { lock.current = false; setBusy(false); }
  }

  async function apply(search: boolean) {
    if (!goalsLoaded) return;
    if (lock.current || query.trim().length < 2) {
      if (query.trim().length < 2) setError("请先描述你想找的岗位。");
      return;
    }
    lock.current = true; setBusy(true); setError("");
    try {
      // An unchanged target starts immediately with saved conditions.
      // A different request creates another workspace unless the user entered
      // the explicit edit flow. Typing alone must not overwrite a saved goal.
      let goal = active && (!dirty || editingId === active.id) ? active : null;
      if (!goal || dirty) {
        const response = await fetch(`${apiUrl}/api/discovery/goals${goal ? `/${goal.id}` : ""}`, {
          method: goal ? "PATCH" : "POST", headers,
          body: JSON.stringify({ input_text: query.trim(), conditions: draft,
            company_ids: selectedCompanyIds.length ? selectedCompanyIds : null,
            expected_version: goal?.version }),
        });
        goal = await responseBody(response) as SearchGoal;
        goalListRevision.current += 1;
        setGoals(old => [goal!, ...old.filter(g => g.id !== goal!.id)]);
        selectGoal(goal);
      } else onGoalChange(goal);
      if (search) onSearch(goal);
    } catch (e) { setError(e instanceof Error ? e.message : "目标保存失败"); }
    finally { lock.current = false; setBusy(false); }
  }

  function changeText(value: string) {
    edited.current = true; inputRevision.current += 1;
    onQueryChange(value); setDraft(null); setEditorOpen(false); setNotice("");
    setFieldTexts({});
  }
  function changeField(key: keyof GoalConditions, value: string) {
    if (!draft) return;
    edited.current = true; inputRevision.current += 1;
    const values = parts(value);
    setFieldTexts(old => ({ ...old, [key]: value }));
    setDraft({ ...draft, [key]: key === "graduation_years" ? values.map(v => Number(v.replace(/届$/, ""))) : values });
    setEditorOpen(true); setOrigins(old => ({ ...old, [key]: "用户修改" }));
  }

  const displayedConditions = draft || (!textChanged ? active?.conditions : null);
  const hasConditions = displayedConditions && Object.values(displayedConditions).some(values => values?.length);

  return <div className="search-composer">
    <div className="search-composer-heading">
      <h1><label htmlFor="job-search-request">求职需求</label></h1>
      <button type="button" className="quiet-button" onClick={() => historyDialog.current?.showModal()}>搜索记录</button>
    </div>
    {loadError && <p role="alert" className="goal-error">搜索记录读取失败：{loadError} {goalsLoaded && "已保留上次读取的记录。"}<button type="button" disabled={loadingGoals} onClick={onReload}>重新连接</button></p>}
    <div className="search-input-row">
      <textarea ref={searchInput} id="job-search-request" value={query} maxLength={500} rows={1} disabled={busy}
        onChange={e => changeText(e.target.value)} placeholder="例如：27届，想找上海或北京的 Agent / RAG 开发岗，实习和校招都看看。"
        onKeyDown={e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !e.nativeEvent.isComposing && !searching) { e.preventDefault(); void apply(true); } }} />
      <button className="search-submit" type="button" disabled={busy || searching || !goalsLoaded} onClick={() => void apply(true)}>
        {busy ? "整理需求…" : searching ? "搜索中…" : "查找岗位"}
      </button>
    </div>
    <div className="search-context-row">
      <div className="search-conditions" aria-label="当前求职目标">
        {hasConditions ? <SearchConditionSummary conditions={displayedConditions!} dirty={dirty} />
          : <span className="muted">{textChanged ? "需求已修改，下方仍为上次搜索结果。" : "描述岗位方向、地点或届别，支持自由输入。"}</span>}
        {hasConditions && dirty && !textChanged && <small>下方仍为已保存条件的结果。</small>}
      </div>
      <div className="search-secondary-actions">
        <button className="quiet-button" type="button" disabled={busy || searching || query.trim().length < 2} onClick={() => void interpret()}>修改条件</button>
        <details className="search-more">
          <summary>更多</summary>
          <div className="search-more-content">
            <button type="button" disabled={busy || searching || !goalsLoaded || query.trim().length < 2} onClick={() => void apply(false)}>保存并筛选已有岗位</button>
            {active && <label className="goal-auto-update">定期更新<select aria-label="定期更新" disabled={busy || dirty} value={intervalMinutes} onChange={e => void saveSchedule(Number(e.target.value))}>
              <option value={0}>手动更新</option><option value={30}>每30分钟</option><option value={60}>每小时</option></select>
              <small>后端运行时自动更新。</small>
              {active.next_update_at && <small>下次更新：{parseApiTimestamp(active.next_update_at).toLocaleString()}</small>}
              {active.schedule_error && <small role="alert">{active.schedule_error}</small>}
            </label>}
            {extraTools}
          </div>
        </details>
      </div>
    </div>
    {draft && editorOpen && <section className="goal-condition-editor" aria-label="修改搜索条件">
      <div className="condition-editor-heading"><strong>搜索条件</strong><button type="button" onClick={() => setEditorOpen(false)}>收起</button></div>
      <div className="goal-fields">{(Object.keys(labels) as (keyof GoalConditions)[]).map(key => <label key={key}>
        <span>{labels[key]}</span><input aria-label={labels[key]} disabled={busy} value={fieldTexts[key] ?? (draft[key] || []).join("、")} onChange={e => changeField(key, e.target.value)}
          placeholder={key === "job_types" ? "校招、实习或社招；留空不限" : key === "pending_conditions" ? "保留待核对的要求，可删除已澄清项" : key.startsWith("preferred_") ? "可选，多项用逗号分隔" : key.startsWith("excluded_") ? "可选，填写不考虑的条件" : "留空不限，多项用逗号分隔"} />
        {origins[key] === "用户修改" && <small>手动修改</small>}
        {origins[key]?.includes("个人资料") && <small>来自已确认的个人资料，可修改</small>}
      </label>)}</div>
      <p>必须条件用于筛选，优先条件用于排序；待确认要求尚未转成筛选限制，需要进一步核对。</p>
      <button type="button" disabled={busy || searching || !goalsLoaded} onClick={() => void apply(false)}>保存条件</button>
    </section>}
    {notice && <p role="status">{notice}</p>}
    {error && <p role="alert" className="goal-error">{error}</p>}
    <dialog ref={historyDialog} className="search-history-dialog" aria-label="搜索记录" onClick={e => { if (e.target === e.currentTarget) historyDialog.current?.close(); }}>
      <header><h2>搜索记录</h2><button type="button" aria-label="关闭搜索记录" onClick={() => historyDialog.current?.close()}>关闭 ×</button></header>
      <button className="history-new" type="button" disabled={busy || !goalsLoaded} onClick={() => { selectGoal(null); edited.current = true; }}>新建搜索</button>
      <div className="search-history-list">{goals.map(goal => {
        const summary = overviews[goal.id]?.goal_version === goal.version ? overviews[goal.id] : undefined;
        const selected = active?.id === goal.id;
        return <article key={goal.id} data-goal-id={goal.id}>
          <button type="button" className="history-request" aria-pressed={selected} disabled={busy} onClick={() => selectGoal(goal)}>
            <strong>{goal.input_text}</strong>
            <span>{selected ? "当前查看" : "查看结果"}{historyDates[goal.id] ? ` · ${parseApiTimestamp(historyDates[goal.id]).toLocaleString("zh-CN", { hour12: false })}` : ""}{summary?.search_status === "RUNNING" ? " · 搜索中" : ""}</span>
          </button>
          <button type="button" className="quiet-button" disabled={busy || (selected && searching)} onClick={() => editGoal(goal)}>编辑条件</button>
        </article>;
      })}</div>
      {!goals.length && <p>{loadingGoals ? "正在读取搜索记录…" : "暂无搜索记录。"}</p>}
      {overviewError && <small role="status">搜索状态暂未更新，仍可查看已保存结果。</small>}
      {historyContent}
    </dialog>
  </div>;
}
