"use client";

export type FactProvenance = {
  extracted: Record<string, unknown>;
  overrides: string[];
  conflicts: Record<string, { incoming: unknown; source_text?: string; reason?: string }>;
  keep_current?: boolean;
  acknowledged?: Record<string, string>;
};

const labels: Record<string, string> = {
  level: "学历", major_raw: "专业", school: "学校", enrollment_year: "入学年份",
  graduation_year: "毕业年份", graduation_year_kind: "毕业年份类型", status: "就读状态",
  title: "经历名称", claim: "经历内容", skills: "技能", type: "经历类型", record: "经历内容",
};
const values: Record<string, string> = {
  master: "硕士", bachelor: "本科", doctor: "博士", enrolled: "在读", graduated: "已毕业",
  actual: "实际毕业", expected: "预计毕业", unknown: "未确认",
};

function display(value: unknown): string {
  if (value == null) return "未填写";
  if (Array.isArray(value)) return value.map(display).join("、");
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    return display(record.source_text ?? record.claim ?? record.title ?? "经历对应关系尚不明确");
  }
  return values[String(value)] ?? String(value);
}

export function FactDifferences({ provenance, current, disabled, onKeep }: {
  provenance?: FactProvenance; current: Record<string, unknown>; disabled?: boolean; onKeep: () => void;
}) {
  const conflicts = Object.entries(provenance?.conflicts ?? {});
  if (!conflicts.length) return null;
  return <details className="fact-differences">
    <summary>已保留你的修改；新简历有 {conflicts.length} 处差异</summary>
    <p>当前分析继续使用已保存的值。可查看差异后编辑资料，或保留当前值。</p>
    {conflicts.map(([field, conflict]) => <div key={field}>
      <strong>{labels[field] ?? "经历对应关系"}</strong>
      <p>当前：{display(field.startsWith("identity:") || field === "record" ? current : current[field])}</p>
      <p>新简历：{display(conflict.incoming)}</p>
      {conflict.source_text && <blockquote>{conflict.source_text}</blockquote>}
    </div>)}
    <button type="button" disabled={disabled || provenance?.keep_current} onClick={onKeep}>
      {provenance?.keep_current ? "已选择保留，保存资料后生效" : "保留当前值"}
    </button>
  </details>;
}
