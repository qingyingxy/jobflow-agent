"use client";

import { FactDifferences, type FactProvenance } from "./fact-differences";

export type EducationRecord = {
  id: string;
  level: "secondary" | "associate" | "bachelor" | "master" | "doctor" | "unknown";
  major_raw: string | null;
  school: string | null;
  enrollment_year?: number | null;
  enrollment_source_text?: string | null;
  graduation_year: number | null;
  graduation_source_text: string | null;
  graduation_year_kind?: "actual" | "expected" | "unknown";
  graduation_year_confirmed?: boolean;
  status: "enrolled" | "graduated" | "unknown";
  source_text: string;
  source: string;
  reviewed?: boolean;
  provenance?: FactProvenance;
};

export const educationLabels = { unknown: "未确认", secondary: "高中 / 中专", associate: "专科", bachelor: "本科", master: "硕士", doctor: "博士" };

export function EducationEditor({ records, complete, disabled, onChange, onCompleteChange }: {
  records: EducationRecord[];
  complete: boolean;
  disabled: boolean;
  onChange: (records: EducationRecord[]) => void;
  onCompleteChange: (complete: boolean) => void;
}) {
  function update(id: string, patch: Partial<EducationRecord>) {
    onChange(records.map(record => record.id === id ? { ...record, ...patch, reviewed: true } : record));
  }
  return <div className="education-editor">
    <h3>教育经历</h3>
    <p className="profile-panel-note">系统自动提取每段教育经历。你修改过的值会在更新简历时保留；缺失信息可留空，需要时再补充。</p>
    {records.map((record, index) => <fieldset disabled={disabled} key={record.id} className="education-record">
      <legend>教育经历 {index + 1}</legend>
      <div className="profile-form-grid">
        <label><span>学历层级</span><select value={record.level} onChange={e => update(record.id, { level: e.target.value as EducationRecord["level"] })}>
          {Object.entries(educationLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        <label><span>专业原名</span><input value={record.major_raw ?? ""} onChange={e => update(record.id, { major_raw: e.target.value || null })} placeholder="例如：机械工程" /></label>
        <label><span>学校</span><input value={record.school ?? ""} onChange={e => update(record.id, { school: e.target.value || null })} /></label>
        <label><span>入学年份</span><input type="number" min="1900" max="2200" value={record.enrollment_year ?? ""} onChange={e => update(record.id, { enrollment_year: e.target.value ? Number(e.target.value) : null, enrollment_source_text: null })} /></label>
        <label><span>毕业 / 预计毕业年份</span><input type="number" min="1900" max="2200" value={record.graduation_year ?? ""} onChange={e => update(record.id, { graduation_year: e.target.value ? Number(e.target.value) : null, graduation_source_text: null, graduation_year_confirmed: Boolean(e.target.value), graduation_year_kind: e.target.value ? record.graduation_year_kind ?? "unknown" : "unknown" })} /></label>
        <label><span>毕业年份类型</span><select disabled={record.graduation_year == null} value={record.graduation_year_kind ?? "unknown"} onChange={e => update(record.id, { graduation_year_kind: e.target.value as EducationRecord["graduation_year_kind"] })}>
          <option value="unknown">未确认</option><option value="actual">实际毕业</option><option value="expected">预计毕业</option>
        </select></label>
        <label><span>就读状态</span><select value={record.status} onChange={e => update(record.id, { status: e.target.value as EducationRecord["status"] })}>
          <option value="unknown">未确认</option><option value="enrolled">在读</option><option value="graduated">已毕业</option>
        </select></label>
        <label><span>{record.source.startsWith("resume_asset:") ? "简历原文" : "确认依据"}</span><textarea rows={3} readOnly={record.source.startsWith("resume_asset:")} value={record.source_text} onChange={e => update(record.id, { source_text: e.target.value })} placeholder="填写这段教育经历的原文或已确认事实" /></label>
      </div>
      <FactDifferences provenance={record.provenance} current={record} disabled={disabled}
        onKeep={() => record.provenance && update(record.id, { provenance: { ...record.provenance, keep_current: true } })} />
      {record.source.startsWith("resume_asset:") && <label className="education-completeness"><input type="checkbox" disabled={record.graduation_year == null} checked={record.graduation_year_confirmed ?? false} onChange={e => update(record.id, { graduation_year_confirmed: e.target.checked })} />我已核对这段经历的毕业年份</label>}
      <button type="button" onClick={() => onChange(records.filter(item => item.id !== record.id))}>移除这段教育经历</button>
    </fieldset>)}
    <button type="button" disabled={disabled || records.length >= 20} onClick={() => onChange([...records, {
      id: `edu_${crypto.randomUUID().replaceAll("-", "").slice(0, 20)}`, level: "unknown", major_raw: null,
      school: null, enrollment_year: null, enrollment_source_text: null, graduation_year: null, graduation_source_text: null, graduation_year_kind: "unknown", graduation_year_confirmed: false, status: "unknown", source_text: "", source: "manual",
    }])}>＋ 添加教育经历</button>
    <label className="education-completeness"><input type="checkbox" disabled={disabled} checked={complete} onChange={e => onCompleteChange(e.target.checked)} />我已核对，并已列出全部教育经历</label>
    <p className="profile-panel-note">未确认完整时，找不到符合条件的经历会提示信息不足。</p>
  </div>;
}
