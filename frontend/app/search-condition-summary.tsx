import type { GoalConditions } from "./search-goal-controls";

const displayNames: Record<string, string> = { agent: "Agent", rag: "RAG", ai: "AI", llm: "LLM", nlp: "NLP" };
const display = (values: string[] = []) => values.map(value => displayNames[value.toLowerCase()] || value).join("、");

export default function SearchConditionSummary({ conditions, dirty }: { conditions: GoalConditions; dirty: boolean }) {
  const basic = [
    display(conditions.roles),
    (conditions.graduation_years || []).map(year => `${year}届`).join("、"),
    (conditions.job_types || []).join(" / "),
    conditions.locations?.length ? `地点：${display(conditions.locations)}` : "地点不限",
    conditions.keywords?.length ? `关键词：${display(conditions.keywords)}` : "",
  ].filter(Boolean);
  const preferred = [display(conditions.preferred_locations), display(conditions.preferred_roles), display(conditions.preferred_keywords)].filter(Boolean);
  const excluded = [display(conditions.excluded_locations), display(conditions.excluded_roles), display(conditions.excluded_job_types)].filter(Boolean);
  return <>
    <div className="condition-summary-main"><span className="condition-summary-label">{dirty ? "待保存条件" : "搜索条件"}</span>
      <span>{basic.join(" · ") || "按下方偏好和要求查找"}</span></div>
    {(preferred.length > 0 || excluded.length > 0) && <div className="condition-summary-secondary">
      {preferred.length > 0 && <span>优先：{preferred.join("、")}</span>}
      {excluded.length > 0 && <span>排除：{excluded.join("、")}</span>}
    </div>}
    {!!conditions.pending_conditions?.length && <div className="condition-summary-pending" title="这些要求尚未用于筛选，需要进一步核对"><span>待确认：</span>{conditions.pending_conditions.join("；")}</div>}
  </>;
}
