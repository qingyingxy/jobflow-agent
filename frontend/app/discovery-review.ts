type ReviewMatch = {
  filter_status?: "matched" | "pending" | "excluded";
  review_status?: "recommended" | "pending" | "excluded" | null;
  preference_score?: number;
  personal_gate_conflict?: boolean;
  personal_requirements?: { status: string; label: string; reason: string }[];
  mismatch_labels?: string[];
  result_status?: {
    analysis: { state: string };
    personal: { state: string };
  };
  checks?: { field: string; status: string; reason: string; diagnosis?: string; role_relation?: string | null; review_required?: boolean }[];
};

type ReviewSummary = { label: string; reason: string; tone: "recommended" | "pending" | "conflict" | "muted" };

// Summarize existing evidence only; search relevance is not personal eligibility.
export function jobReviewSummary(match?: ReviewMatch, source: { closed?: boolean; pendingLeadStatus?: string; missingCompany?: boolean; missingLocation?: boolean } = {}): ReviewSummary {
  if (source.closed) return { label: "已关闭", reason: "岗位已停止招聘", tone: "muted" };
  const sourceConflict = match?.personal_requirements?.find(hint => hint.status === "source_conflict");
  if (sourceConflict || match?.result_status?.personal.state === "source_conflict") {
    return { label: "资格原文有冲突", reason: sourceConflict?.reason || "招聘项目与正文要求不一致，需核对", tone: "conflict" };
  }
  const conflict = match?.personal_requirements?.find(hint => hint.status === "attention");
  if (conflict || match?.personal_gate_conflict || match?.result_status?.personal.state === "conflict") {
    return { label: "存在门槛冲突", reason: conflict?.reason || conflict?.label || "个人条件与岗位要求冲突，查看详情", tone: "conflict" };
  }
  if (match?.filter_status === "excluded" || match?.review_status === "excluded") {
    return { label: "不符搜索条件", reason: match.checks?.find(check => check.status === "excluded")?.reason || match.mismatch_labels?.[0] || "与当前搜索需求存在冲突", tone: "muted" };
  }
  const analysis = match?.result_status?.analysis.state;
  if (source.pendingLeadStatus || analysis === "reading_required") {
    const action = source.pendingLeadStatus === "NEEDS_BROWSER" ? "，需浏览器验证"
      : source.pendingLeadStatus === "NEEDS_USER" ? "，可粘贴 JD 继续" : "";
    return { label: "待核验", reason: `正文待核验${action}`, tone: "pending" };
  }
  const checks = match?.checks ?? [];
  if (["waiting", "retrying", "blocked"].includes(analysis ?? "") || checks.some(check => check.diagnosis === "not_extracted")) {
    return { label: "待确认", reason: analysis === "blocked" ? "正文已保存，分析失败待重试"
      : analysis === "retrying" ? "正文已保存，分析待重试" : "正文已保存，等待分析", tone: "pending" };
  }
  if (checks.some(check => check.review_required)) return { label: "待确认", reason: "方向判断待复核", tone: "pending" };
  const pendingLabels: Record<string, string> = {
    graduation_year: "届别待确认", location: "地点待确认", job_type: "招聘类型待确认", role: "方向待确认",
  };
  const missingFields = [source.missingCompany ? "公司待确认" : "", source.missingLocation ? "地点待确认" : ""].filter(Boolean);
  const caveatPriority: Record<string, number> = { role: 0, graduation_year: 1, job_type: 2, location: 3, availability: 9 };
  const caveats = [...new Set([...missingFields, ...checks.filter(check => check.status === "pending")
    .sort((a, b) => (caveatPriority[a.field] ?? 4) - (caveatPriority[b.field] ?? 4)).map(check =>
    check.field === "role" && check.role_relation === "adjacent" ? "相邻方向，值得看看"
      : check.field === "availability" ? (check.reason.includes("待更新") ? "开放状态待更新" : "开放状态未知")
      : pendingLabels[check.field] || check.reason).filter(Boolean)])];
  const matched = new Set(checks.filter(check => check.status === "matched").map(check => check.field));
  const confirmed = matched.has("role") && matched.has("graduation_year") ? "方向、届别符合"
    : matched.has("role") && matched.has("location") ? "方向、地点符合"
    : matched.has("role") ? "方向符合" : matched.has("graduation_year") ? "届别符合" : matched.has("location") ? "地点符合" : "";
  if (missingFields.length) return { label: "信息待补全", reason: caveats.slice(0, 2).join(" · "), tone: "pending" };
  if (reviewStatus(match) === "recommended") {
    const reason = caveats.length > 1 ? caveats.slice(0, 2).join(" · ")
      : caveats.length ? [confirmed, caveats[0]].filter(Boolean).join(" · ")
      : confirmed || (match?.filter_status === "matched" ? "符合当前搜索条件" : "建议查看详情核对条件");
    return { label: "推荐查看", reason, tone: "recommended" };
  }
  return { label: "待确认", reason: caveats.slice(0, 2).join(" · ") || (match ? "搜索条件尚待确认" : "尚未按当前需求核对"), tone: "pending" };
}

export function reviewStatus(match?: ReviewMatch) {
  if (match?.filter_status === "excluded") return "excluded";
  // Old responses can confirm strict matches, but cannot promote pending jobs.
  return match?.review_status ?? (match?.filter_status === "matched" ? "recommended" : "pending");
}

export function reviewCounts(matches: ReviewMatch[]) {
  return {
    recommended: matches.filter(m => reviewStatus(m) === "recommended").length,
    confirmed: matches.filter(m => m.filter_status === "matched").length,
    pending: matches.filter(m => reviewStatus(m) === "pending").length,
    excluded: matches.filter(m => reviewStatus(m) === "excluded").length,
  };
}

export function reviewCaveats(match?: ReviewMatch) {
  if (match?.personal_gate_conflict) return ["个人门槛存在明确冲突"];
  if (match?.filter_status === "matched") return ["搜索条件已确认"];
  return [...new Set((match?.checks ?? []).filter(c => c.status === "pending").flatMap(c =>
    c.review_required ? ["方向待自动复核"]
      : c.diagnosis === "not_extracted" ? ["等待AI分析"]
      : c.field === "role" && c.role_relation === "adjacent" ? ["相邻方向，值得看看"]
      : c.field === "graduation_year" ? ["届别待确认"]
      : c.field === "availability" ? [c.reason.includes("待更新") ? "开放状态待更新" : "开放状态未知"]
      : c.field === "location" ? ["地点待确认"]
      : c.field === "job_type" ? ["招聘人群待确认"]
      : c.field === "role" ? ["方向相关性待确认"] : []))];
}

// Reading order only: missing facts never become negative eligibility evidence.
// Direction matters more than whether a page happens to spell out its cohort.
export function reviewRelevance(match?: ReviewMatch) {
  const weights: Record<string, number> = { role: 6, location: 3, job_type: 2, graduation_year: 1 };
  const matched = new Set((match?.checks ?? []).filter(c => c.status === "matched").map(c => c.field));
  return [...matched].reduce((sum, field) => sum + (weights[field] ?? 0), 0)
    + ((match?.checks ?? []).some(c => c.field === "role" && c.status === "pending" && c.role_relation === "adjacent") ? 2 : 0)
    + (match?.preference_score ?? 0);
}
