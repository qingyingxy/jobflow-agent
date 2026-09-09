"use client";

import { useEffect, useRef, useState } from "react";

type FieldState = "missing" | "provided" | "not_applicable" | "declined_to_store";
type MaterialStep = "profile" | "resumes" | "answers";
type StringFieldName =
  | "contact_email"
  | "contact_phone"
  | "current_status"
  | "work_authorization"
  | "salary_strategy";
type BooleanFieldName = "sponsorship_required" | "relocation_willing";

type PrivateField<T> = { state: FieldState; value: T | null };

type PrivateProfile = {
  user_id: string;
  revision: number;
  contact_email: PrivateField<string>;
  contact_phone: PrivateField<string>;
  current_status: PrivateField<string>;
  availability_date: PrivateField<string>;
  work_authorization: PrivateField<string>;
  sponsorship_required: PrivateField<boolean>;
  salary_strategy: PrivateField<string>;
  relocation_willing: PrivateField<boolean>;
  voluntary_disclosure_policy: "ask_each_time" | "prefer_not_to_answer" | "allow_user_entry";
  readiness: "ready" | "needs_confirmation";
  needs_confirmation: Array<{ field: string; state: FieldState; reason: string }>;
  created_at: string;
  updated_at: string;
};

type ResumeAsset = {
  id: string;
  user_id: string;
  original_filename: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  created_at: string;
};

type ResumeVersion = {
  id: string;
  user_id: string;
  asset_id: string;
  version_number: number;
  label: string;
  job_family: string | null;
  source_version_id: string | null;
  generation_reason: string;
  is_default: boolean;
  asset: ResumeAsset;
  created_at: string;
  updated_at: string;
};

type AnswerEntry = {
  id: string;
  user_id: string;
  question_pattern: string;
  answer: string;
  scope_type: "general" | "job_family" | "company" | "role";
  scope_value: string;
  sensitivity: "standard" | "personal" | "high_impact";
  confirmed_at: string;
  created_at: string;
  updated_at: string;
};

type ProfileDraft = {
  contact_email: PrivateField<string>;
  contact_phone: PrivateField<string>;
  current_status: PrivateField<string>;
  availability_date: PrivateField<string>;
  work_authorization: PrivateField<string>;
  sponsorship_required: PrivateField<boolean>;
  salary_strategy: PrivateField<string>;
  relocation_willing: PrivateField<boolean>;
  voluntary_disclosure_policy: PrivateProfile["voluntary_disclosure_policy"];
};

type AnswerDraft = {
  question_pattern: string;
  answer: string;
  scope_type: AnswerEntry["scope_type"];
  scope_value: string;
  sensitivity: AnswerEntry["sensitivity"];
  confirmed: boolean;
};

const fieldStateLabel: Record<FieldState, string> = {
  missing: "缺失",
  provided: "已提供",
  not_applicable: "不适用",
  declined_to_store: "拒绝保存",
};

const fieldLabel: Record<string, string> = {
  contact_email: "联系邮箱",
  contact_phone: "联系电话",
  current_status: "当前状态",
  availability_date: "可到岗日期",
  work_authorization: "工作资格",
  sponsorship_required: "签证 / 赞助需求",
  salary_strategy: "薪资策略",
  relocation_willing: "搬迁意愿",
};

const scopeLabel: Record<AnswerEntry["scope_type"], string> = {
  general: "通用",
  job_family: "岗位族",
  company: "公司",
  role: "具体岗位",
};

const sensitivityLabel: Record<AnswerEntry["sensitivity"], string> = {
  standard: "普通",
  personal: "个人信息",
  high_impact: "高影响",
};

const emptyProfileDraft: ProfileDraft = {
  contact_email: { state: "missing", value: "" },
  contact_phone: { state: "missing", value: "" },
  current_status: { state: "missing", value: "" },
  availability_date: { state: "missing", value: "" },
  work_authorization: { state: "missing", value: "" },
  sponsorship_required: { state: "missing", value: false },
  salary_strategy: { state: "missing", value: "" },
  relocation_willing: { state: "missing", value: false },
  voluntary_disclosure_policy: "ask_each_time",
};

const emptyAnswerDraft: AnswerDraft = {
  question_pattern: "",
  answer: "",
  scope_type: "general",
  scope_value: "",
  sensitivity: "standard",
  confirmed: false,
};

async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { error?: { message?: string } };
    return payload.error?.message ?? `请求失败（${response.status}）`;
  } catch {
    return `请求失败（${response.status}）`;
  }
}

function toProfileDraft(profile: PrivateProfile): ProfileDraft {
  return {
    contact_email: { ...profile.contact_email, value: profile.contact_email.value ?? "" },
    contact_phone: { ...profile.contact_phone, value: profile.contact_phone.value ?? "" },
    current_status: { ...profile.current_status, value: profile.current_status.value ?? "" },
    availability_date: { ...profile.availability_date, value: profile.availability_date.value ?? "" },
    work_authorization: { ...profile.work_authorization, value: profile.work_authorization.value ?? "" },
    sponsorship_required: { ...profile.sponsorship_required, value: profile.sponsorship_required.value ?? false },
    salary_strategy: { ...profile.salary_strategy, value: profile.salary_strategy.value ?? "" },
    relocation_willing: { ...profile.relocation_willing, value: profile.relocation_willing.value ?? false },
    voluntary_disclosure_policy: profile.voluntary_disclosure_policy,
  };
}

function fieldPayload<T>(field: PrivateField<T>): PrivateField<T> {
  return {
    state: field.state,
    value: field.state === "provided" ? field.value : null,
  };
}

export default function MaterialsWorkspace({
  apiUrl,
  userId,
  onResumeChange,
  variant = "full",
}: {
  apiUrl: string;
  userId: string;
  onResumeChange?: () => void;
  variant?: "full" | "resume-only";
}) {
  const [step, setStep] = useState<MaterialStep>(variant === "resume-only" ? "resumes" : "profile");
  const [state, setState] = useState<"loading" | "ready" | "saving" | "error">("loading");
  const [message, setMessage] = useState("");
  const [profile, setProfile] = useState<PrivateProfile | null>(null);
  const [profileDraft, setProfileDraft] = useState<ProfileDraft>(emptyProfileDraft);
  const [assets, setAssets] = useState<ResumeAsset[]>([]);
  const [versions, setVersions] = useState<ResumeVersion[]>([]);
  const [answers, setAnswers] = useState<AnswerEntry[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [selectedAssetId, setSelectedAssetId] = useState("");
  const [versionLabel, setVersionLabel] = useState("");
  const [jobFamily, setJobFamily] = useState("");
  const [generationReason, setGenerationReason] = useState("用户上传基线");
  const [makeDefault, setMakeDefault] = useState(true);
  const [answerDraft, setAnswerDraft] = useState<AnswerDraft>(emptyAnswerDraft);
  const [editingAnswerId, setEditingAnswerId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const loadSequence = useRef(0);
  const initialLoadStarted = useRef(false);

  async function loadMaterials() {
    const loadId = loadSequence.current + 1;
    loadSequence.current = loadId;
    setState("loading");
    setMessage("");
    try {
      const headers = { "X-User-ID": userId };
      const [profileResponse, assetResponse, versionResponse, answerResponse] = await Promise.all([
        fetch(`${apiUrl}/api/private-profile`, { headers, cache: "no-store" }),
        fetch(`${apiUrl}/api/resumes/assets`, { headers, cache: "no-store" }),
        fetch(`${apiUrl}/api/resumes/versions`, { headers, cache: "no-store" }),
        fetch(`${apiUrl}/api/answer-bank`, { headers, cache: "no-store" }),
      ]);
      for (const response of [profileResponse, assetResponse, versionResponse, answerResponse]) {
        if (!response.ok) throw new Error(await readError(response));
      }
      const [nextProfile, nextAssets, nextVersions, nextAnswers] = await Promise.all([
        profileResponse.json() as Promise<PrivateProfile>,
        assetResponse.json() as Promise<ResumeAsset[]>,
        versionResponse.json() as Promise<ResumeVersion[]>,
        answerResponse.json() as Promise<AnswerEntry[]>,
      ]);
      if (loadId !== loadSequence.current) return;
      setProfile(nextProfile);
      setProfileDraft(toProfileDraft(nextProfile));
      setAssets(nextAssets);
      setVersions(nextVersions);
      setAnswers(nextAnswers);
      setSelectedAssetId((current) => current || nextAssets[0]?.id || "");
      setMessage("");
      setState("ready");
    } catch (error) {
      if (loadId !== loadSequence.current) return;
      setState("error");
      setMessage(error instanceof Error ? error.message : "投递资料加载失败。");
    }
  }

  useEffect(() => {
    if (initialLoadStarted.current) return;
    initialLoadStarted.current = true;
    void loadMaterials();
  }, []);

  function updateStringField(field: StringFieldName, patch: Partial<PrivateField<string>>) {
    setProfileDraft((current) => ({
      ...current,
      [field]: { ...current[field], ...patch },
    }));
  }

  function updateBooleanField(field: BooleanFieldName, patch: Partial<PrivateField<boolean>>) {
    setProfileDraft((current) => ({
      ...current,
      [field]: { ...current[field], ...patch },
    }));
  }

  async function saveProfile() {
    setState("saving");
    setMessage("");
    try {
      const response = await fetch(`${apiUrl}/api/private-profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({
          contact_email: fieldPayload(profileDraft.contact_email),
          contact_phone: fieldPayload(profileDraft.contact_phone),
          current_status: fieldPayload(profileDraft.current_status),
          availability_date: fieldPayload(profileDraft.availability_date),
          work_authorization: fieldPayload(profileDraft.work_authorization),
          sponsorship_required: fieldPayload(profileDraft.sponsorship_required),
          salary_strategy: fieldPayload(profileDraft.salary_strategy),
          relocation_willing: fieldPayload(profileDraft.relocation_willing),
          voluntary_disclosure_policy: profileDraft.voluntary_disclosure_policy,
        }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const updated = (await response.json()) as PrivateProfile;
      setProfile(updated);
      setProfileDraft(toProfileDraft(updated));
      setState("ready");
      setMessage(updated.readiness === "ready" ? "私密档案已完整确认。" : `已保存，仍有 ${updated.needs_confirmation.length} 项需要确认。`);
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "私密档案保存失败。");
    }
  }

  async function createResumeVersion() {
    if (!selectedFile && !selectedAssetId) {
      setMessage("请选择 PDF / DOCX 文件，或使用已上传文件。");
      return;
    }
    if (!versionLabel.trim()) {
      setMessage("请填写简历版本名称。");
      return;
    }
    setState("saving");
    setMessage("");
    try {
      let assetId = selectedAssetId;
      if (selectedFile) {
        const form = new FormData();
        form.append("file", selectedFile);
        const uploadResponse = await fetch(`${apiUrl}/api/resumes/assets`, {
          method: "POST",
          headers: { "X-User-ID": userId },
          body: form,
        });
        if (!uploadResponse.ok) throw new Error(await readError(uploadResponse));
        const asset = (await uploadResponse.json()) as ResumeAsset;
        assetId = asset.id;
        setAssets((current) => [asset, ...current]);
      }
      const versionResponse = await fetch(`${apiUrl}/api/resumes/versions`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({
          asset_id: assetId,
          label: versionLabel.trim(),
          job_family: jobFamily.trim() || null,
          source_version_id: null,
          generation_reason: generationReason.trim() || "用户上传基线",
          is_default: makeDefault,
        }),
      });
      if (!versionResponse.ok) throw new Error(await readError(versionResponse));
      const created = (await versionResponse.json()) as ResumeVersion;
      setVersions((current) => [created, ...current.map((item) => ({ ...item, is_default: created.is_default ? false : item.is_default }))]);
      setSelectedFile(null);
      setSelectedAssetId(assetId);
      setVersionLabel("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      setState("ready");
      setMessage(`简历 v${created.version_number} 已入库${created.is_default ? "并设为默认" : ""}。`);
      onResumeChange?.();
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "简历版本创建失败。");
    }
  }

  async function setDefaultVersion(versionId: string) {
    setState("saving");
    setMessage("");
    try {
      const response = await fetch(`${apiUrl}/api/resumes/versions/${versionId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({ is_default: true }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const updated = (await response.json()) as ResumeVersion;
      setVersions((current) => current.map((item) => ({ ...item, is_default: item.id === updated.id })));
      setState("ready");
      setMessage(`v${updated.version_number} 已设为默认投递简历。`);
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "默认版本更新失败。");
    }
  }

  async function downloadAsset(asset: ResumeAsset) {
    setMessage("");
    try {
      const response = await fetch(`${apiUrl}/api/resumes/assets/${asset.id}/download`, {
        headers: { "X-User-ID": userId },
      });
      if (!response.ok) throw new Error(await readError(response));
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = asset.original_filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "简历下载失败。");
    }
  }

  async function saveAnswer() {
    if (!answerDraft.confirmed) {
      setMessage("请先确认答案内容准确且允许保存。");
      return;
    }
    if (!answerDraft.question_pattern.trim() || !answerDraft.answer.trim()) {
      setMessage("问题模式和答案都不能为空。");
      return;
    }
    setState("saving");
    setMessage("");
    const url = editingAnswerId ? `${apiUrl}/api/answer-bank/${editingAnswerId}` : `${apiUrl}/api/answer-bank`;
    try {
      const response = await fetch(url, {
        method: editingAnswerId ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify({
          ...answerDraft,
          question_pattern: answerDraft.question_pattern.trim(),
          answer: answerDraft.answer.trim(),
          scope_value: answerDraft.scope_type === "general" ? "" : answerDraft.scope_value.trim(),
        }),
      });
      if (!response.ok) throw new Error(await readError(response));
      const saved = (await response.json()) as AnswerEntry;
      setAnswers((current) => editingAnswerId ? current.map((item) => item.id === saved.id ? saved : item) : [saved, ...current]);
      setAnswerDraft(emptyAnswerDraft);
      setEditingAnswerId(null);
      setState("ready");
      setMessage("已确认答案已保存到私密答案库。");
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "答案保存失败。");
    }
  }

  function editAnswer(answer: AnswerEntry) {
    setEditingAnswerId(answer.id);
    setAnswerDraft({
      question_pattern: answer.question_pattern,
      answer: answer.answer,
      scope_type: answer.scope_type,
      scope_value: answer.scope_value,
      sensitivity: answer.sensitivity,
      confirmed: false,
    });
    window.scrollTo({ top: 420, behavior: "smooth" });
  }

  async function deleteAnswer(answerId: string) {
    setState("saving");
    setMessage("");
    try {
      const response = await fetch(`${apiUrl}/api/answer-bank/${answerId}`, {
        method: "DELETE",
        headers: { "X-User-ID": userId },
      });
      if (!response.ok) throw new Error(await readError(response));
      setAnswers((current) => current.filter((item) => item.id !== answerId));
      if (editingAnswerId === answerId) {
        setEditingAnswerId(null);
        setAnswerDraft(emptyAnswerDraft);
      }
      setState("ready");
      setMessage("答案已从私密库删除。");
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "答案删除失败。");
    }
  }

  const stringFields: Array<{ key: StringFieldName; label: string; placeholder: string; type?: string }> = [
    { key: "contact_email", label: "联系邮箱", placeholder: "name@example.com", type: "email" },
    { key: "contact_phone", label: "联系电话", placeholder: "+86 138 0000 0000", type: "tel" },
    { key: "current_status", label: "当前状态", placeholder: "例如：2027 届在读硕士" },
    { key: "work_authorization", label: "工作资格", placeholder: "例如：可在中国大陆全职工作" },
    { key: "salary_strategy", label: "薪资策略", placeholder: "例如：按岗位预算协商" },
  ];

  const resumeWorkspace = state !== "loading" ? (
    <div className={`resume-workspace ${variant === "resume-only" ? "resume-workspace-compact" : ""}`}>
      <section className="resume-composer">
        <div className="materials-subheading">
          <span>{variant === "resume-only" ? "上传简历" : "新建版本"}</span>
          <strong>{variant === "resume-only" ? "添加一份 PDF 或 DOCX 简历" : "登记一份可追踪简历"}</strong>
        </div>
        <div className="resume-form-grid">
          <label className="resume-file-field">
            <span>选择简历文件</span>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              onChange={(event) => {
                const file = event.target.files?.[0] ?? null;
                setSelectedFile(file);
                if (file) {
                  setVersionLabel((current) => current.trim() || file.name.replace(/\.(pdf|docx)$/i, ""));
                }
              }}
            />
            <small>{selectedFile ? `${selectedFile.name} · ${formatBytes(selectedFile.size)}` : "PDF / DOCX · 最大 5 MB"}</small>
          </label>
          {variant === "full" ? (
            <label>
              <span>或使用已上传文件</span>
              <select value={selectedAssetId} disabled={Boolean(selectedFile)} onChange={(event) => setSelectedAssetId(event.target.value)}>
                <option value="">选择文件</option>
                {assets.map((asset) => <option value={asset.id} key={asset.id}>{asset.original_filename} · {asset.sha256.slice(0, 8)}</option>)}
              </select>
            </label>
          ) : null}
          <label>
            <span>版本名称</span>
            <input value={versionLabel} onChange={(event) => setVersionLabel(event.target.value)} placeholder="例如：AI Agent 中文简历" />
          </label>
          {variant === "full" ? (
            <>
              <label><span>适用岗位族</span><input value={jobFamily} onChange={(event) => setJobFamily(event.target.value)} placeholder="例如：AI Agent / LLM 应用" /></label>
              <label className="resume-reason-field"><span>生成原因</span><input value={generationReason} onChange={(event) => setGenerationReason(event.target.value)} placeholder="例如：针对 Agent 工程岗位调整" /></label>
            </>
          ) : null}
          <label className="resume-default-check"><input type="checkbox" checked={makeDefault} onChange={(event) => setMakeDefault(event.target.checked)} /><span>设为默认投递版本</span></label>
        </div>
        <div className="materials-action-row">
          <span>{variant === "resume-only" ? "上传后会自动解析经历，你可以在“我的经历”中逐条核对。" : "文件内容保存在非公开目录；界面和 API 只暴露受控元数据。"}</span>
          <button className="materials-primary" disabled={state === "saving"} onClick={() => void createResumeVersion()} type="button">
            {state === "saving" ? "处理中…" : variant === "resume-only" ? "上传并解析" : "创建简历版本"}
          </button>
        </div>
      </section>
      <section className="version-library">
        <div className="materials-subheading"><span>已有简历</span><strong>{versions.length} 个版本</strong></div>
        {versions.length === 0 ? <div className="materials-empty">还没有上传简历。</div> : (
          <div className="version-list">{versions.map((version) => (
            <article className={`version-row ${version.is_default ? "is-default" : ""}`} key={version.id}>
              <div className="version-number">V{version.version_number.toString().padStart(2, "0")}</div>
              <div className="version-main"><div><h3>{version.label}</h3>{version.is_default ? <span>默认</span> : null}</div><p>{version.job_family || "通用岗位"} · {version.generation_reason}</p><small>{version.asset.original_filename} · {formatBytes(version.asset.size_bytes)}</small></div>
              <div className="version-actions"><button onClick={() => void downloadAsset(version.asset)} type="button" aria-label={`下载 ${version.label}`}>↓</button>{!version.is_default ? <button onClick={() => void setDefaultVersion(version.id)} disabled={state === "saving"} type="button">设为默认</button> : <span>当前默认</span>}</div>
            </article>
          ))}</div>
        )}
      </section>
    </div>
  ) : null;

  if (variant === "resume-only") {
    return (
      <section className="materials-resume-only" aria-live="polite">
        {message ? <div className={`materials-message ${state === "error" ? "materials-message-error" : ""}`}>{message}</div> : null}
        {state === "loading" ? <div className="materials-loading"><span />正在读取简历…</div> : null}
        {resumeWorkspace}
      </section>
    );
  }

  return (
    <section className="materials-layout">
      <aside className="materials-rail">
        <div className="section-kicker">高级申请资料</div>
        <h2>只使用你确认过的资料</h2>
        <div className="materials-steps" role="tablist" aria-label="投递资料步骤">
          <StepButton index="01" label="私密档案" detail={profile?.readiness === "ready" ? "已确认" : `${profile?.needs_confirmation.length ?? 8} 项待确认`} active={step === "profile"} complete={profile?.readiness === "ready"} onClick={() => setStep("profile")} />
          <StepButton index="02" label="简历版本" detail={`${versions.length} 个版本`} active={step === "resumes"} complete={versions.length > 0} onClick={() => setStep("resumes")} />
          <StepButton index="03" label="答案库" detail={`${answers.length} 条确认答案`} active={step === "answers"} complete={answers.length > 0} onClick={() => setStep("answers")} />
        </div>
        <div className="materials-privacy-note">
          <span>隐私保护</span>
          <p>联系方式、简历正文和敏感答案不会写入普通日志或申请事件。身份披露这里只保存处理策略。</p>
        </div>
      </aside>

      <section className="materials-surface" aria-live="polite">
        <header className="materials-heading">
          <div>
            <span className="materials-step-index">{step === "profile" ? "私密档案" : step === "resumes" ? "简历版本" : "答案库"}</span>
            <h2>{step === "profile" ? "确认申请事实" : step === "resumes" ? "管理简历身份与版本" : "只复用你确认过的答案"}</h2>
          </div>
          <button className="materials-refresh" onClick={() => void loadMaterials()} disabled={state === "loading" || state === "saving"} type="button" aria-label="刷新投递资料">↻</button>
        </header>

        {message ? <div className={`materials-message ${state === "error" ? "materials-message-error" : ""}`}>{message}</div> : null}
        {state === "loading" ? <div className="materials-loading"><span />正在读取私密资料…</div> : null}

        {state !== "loading" && step === "profile" ? (
          <div className="private-profile-workspace">
            <div className="profile-readiness-strip">
              <div>
                <span className={`readiness-light ${profile?.readiness === "ready" ? "is-ready" : ""}`} />
                <strong>{profile?.readiness === "ready" ? "申请事实已确认" : "仍需人工确认"}</strong>
              </div>
              <span>PROFILE REVISION {profile?.revision ?? 1}</span>
            </div>
            {profile && profile.needs_confirmation.length > 0 ? (
              <div className="confirmation-register">
                {profile.needs_confirmation.map((item) => (
                  <span className={`confirmation-chip state-${item.state}`} key={item.field}>{fieldLabel[item.field]} · {fieldStateLabel[item.state]}</span>
                ))}
              </div>
            ) : null}
            <div className="private-fields-grid">
              {stringFields.map((item) => {
                const field = profileDraft[item.key];
                return (
                  <PrivateFieldControl key={item.key} label={item.label} state={field.state} onStateChange={(nextState) => updateStringField(item.key, { state: nextState, value: nextState === "provided" ? field.value : "" })}>
                    {field.state === "provided" ? <input aria-label={`${item.label}内容`} type={item.type ?? "text"} value={field.value ?? ""} onChange={(event) => updateStringField(item.key, { value: event.target.value })} placeholder={item.placeholder} /> : <FieldStateNotice state={field.state} />}
                  </PrivateFieldControl>
                );
              })}
              <PrivateFieldControl label="可到岗日期" state={profileDraft.availability_date.state} onStateChange={(nextState) => setProfileDraft((current) => ({ ...current, availability_date: { state: nextState, value: nextState === "provided" ? current.availability_date.value : "" } }))}>
                {profileDraft.availability_date.state === "provided" ? <input aria-label="可到岗日期内容" type="date" value={profileDraft.availability_date.value ?? ""} onChange={(event) => setProfileDraft((current) => ({ ...current, availability_date: { ...current.availability_date, value: event.target.value } }))} /> : <FieldStateNotice state={profileDraft.availability_date.state} />}
              </PrivateFieldControl>
              {(["sponsorship_required", "relocation_willing"] as BooleanFieldName[]).map((key) => {
                const field = profileDraft[key];
                return (
                  <PrivateFieldControl key={key} label={fieldLabel[key]} state={field.state} onStateChange={(nextState) => updateBooleanField(key, { state: nextState, value: nextState === "provided" ? field.value : false })}>
                    {field.state === "provided" ? (
                      <div className="boolean-segment" role="group" aria-label={fieldLabel[key]}>
                        <button className={field.value === true ? "is-selected" : ""} onClick={() => updateBooleanField(key, { value: true })} type="button">是</button>
                        <button className={field.value === false ? "is-selected" : ""} onClick={() => updateBooleanField(key, { value: false })} type="button">否</button>
                      </div>
                    ) : <FieldStateNotice state={field.state} />}
                  </PrivateFieldControl>
                );
              })}
            </div>
            <section className="disclosure-policy">
              <div><span>自愿身份披露</span><strong>只保存处理策略，不保存具体答案</strong></div>
              <div className="policy-segment" role="group" aria-label="自愿身份披露策略">
                {([
                  ["ask_each_time", "每次询问"],
                  ["prefer_not_to_answer", "默认不回答"],
                  ["allow_user_entry", "允许当次录入"],
                ] as const).map(([value, label]) => <button className={profileDraft.voluntary_disclosure_policy === value ? "is-selected" : ""} key={value} onClick={() => setProfileDraft((current) => ({ ...current, voluntary_disclosure_policy: value }))} type="button">{label}</button>)}
              </div>
            </section>
            <div className="materials-action-row">
              <span>未填写或拒绝保存的高影响字段会保留为 needs_confirmation。</span>
              <button className="materials-primary" disabled={state === "saving"} onClick={() => void saveProfile()} type="button">{state === "saving" ? "保存中…" : "保存私密档案 ↗"}</button>
            </div>
          </div>
        ) : null}

        {step === "resumes" ? resumeWorkspace : null}

        {state !== "loading" && step === "answers" ? (
          <div className="answer-workspace">
            <section className="answer-composer">
              <div className="materials-subheading"><span>{editingAnswerId ? "EDIT CONFIRMED ANSWER" : "NEW CONFIRMED ANSWER"}</span><strong>{editingAnswerId ? "重新确认后保存" : "建立可复用答案"}</strong></div>
              <div className="answer-form-grid">
                <label className="answer-question-field"><span>问题模式</span><input value={answerDraft.question_pattern} onChange={(event) => setAnswerDraft((current) => ({ ...current, question_pattern: event.target.value, confirmed: false }))} placeholder="例如：Why do you want to join us?" /></label>
                <label><span>适用范围</span><select value={answerDraft.scope_type} onChange={(event) => setAnswerDraft((current) => ({ ...current, scope_type: event.target.value as AnswerEntry["scope_type"], scope_value: event.target.value === "general" ? "" : current.scope_value, confirmed: false }))}>{Object.entries(scopeLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
                <label><span>敏感级别</span><select value={answerDraft.sensitivity} onChange={(event) => setAnswerDraft((current) => ({ ...current, sensitivity: event.target.value as AnswerEntry["sensitivity"], confirmed: false }))}>{Object.entries(sensitivityLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
                {answerDraft.scope_type !== "general" ? <label className="answer-scope-value"><span>范围值</span><input value={answerDraft.scope_value} onChange={(event) => setAnswerDraft((current) => ({ ...current, scope_value: event.target.value, confirmed: false }))} placeholder={answerDraft.scope_type === "company" ? "公司名称" : answerDraft.scope_type === "job_family" ? "岗位族" : "岗位名称"} /></label> : null}
                <label className="answer-content-field"><span>已确认答案</span><textarea value={answerDraft.answer} onChange={(event) => setAnswerDraft((current) => ({ ...current, answer: event.target.value, confirmed: false }))} rows={5} placeholder="仅保存真实、可复用且由你确认的答案。" /></label>
              </div>
              <div className="answer-confirm-row"><label><input type="checkbox" checked={answerDraft.confirmed} onChange={(event) => setAnswerDraft((current) => ({ ...current, confirmed: event.target.checked }))} /><span>我确认答案准确，并允许保存到私密答案库</span></label><div>{editingAnswerId ? <button className="materials-secondary" onClick={() => { setEditingAnswerId(null); setAnswerDraft(emptyAnswerDraft); }} type="button">取消编辑</button> : null}<button className="materials-primary" disabled={state === "saving" || !answerDraft.confirmed} onClick={() => void saveAnswer()} type="button">{state === "saving" ? "保存中…" : editingAnswerId ? "确认更新 ↗" : "保存确认答案 ↗"}</button></div></div>
            </section>
            <section className="answer-library">
              <div className="materials-subheading"><span>ANSWER REGISTER</span><strong>{answers.length.toString().padStart(2, "0")} 条</strong></div>
              {answers.length === 0 ? <div className="materials-empty">还没有已确认答案。</div> : <div className="answer-list">{answers.map((answer) => <article className="answer-row" key={answer.id}><div className="answer-meta"><span>{scopeLabel[answer.scope_type]}{answer.scope_value ? ` / ${answer.scope_value}` : ""}</span><span className={`sensitivity-${answer.sensitivity}`}>{sensitivityLabel[answer.sensitivity]}</span></div><h3>{answer.question_pattern}</h3><p>{answer.answer}</p><footer><time>确认于 {formatDate(answer.confirmed_at)}</time><div><button onClick={() => editAnswer(answer)} type="button">编辑</button><button onClick={() => void deleteAnswer(answer.id)} disabled={state === "saving"} type="button">删除</button></div></footer></article>)}</div>}
            </section>
          </div>
        ) : null}
      </section>
    </section>
  );
}

function StepButton({ index, label, detail, active, complete, onClick }: { index: string; label: string; detail: string; active: boolean; complete: boolean; onClick: () => void }) {
  return <button className={`${active ? "is-active" : ""} ${complete ? "is-complete" : ""}`} onClick={onClick} type="button" role="tab" aria-selected={active}><span>{complete ? "✓" : index}</span><div><strong>{label}</strong><small>{detail}</small></div><i>→</i></button>;
}

function PrivateFieldControl({ label, state, onStateChange, children }: { label: string; state: FieldState; onStateChange: (state: FieldState) => void; children: React.ReactNode }) {
  return <label className={`private-field-control state-${state}`}><div><span>{label}</span><select aria-label={`${label}保存状态`} value={state} onChange={(event) => onStateChange(event.target.value as FieldState)}>{Object.entries(fieldStateLabel).map(([value, copy]) => <option value={value} key={value}>{copy}</option>)}</select></div>{children}</label>;
}

function FieldStateNotice({ state }: { state: FieldState }) {
  const copy = state === "declined_to_store" ? "不保存具体内容，使用时再次询问" : state === "not_applicable" ? "已明确标记为不适用" : "没有值，系统不会推断";
  return <p className="field-state-notice">{copy}</p>;
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "刚刚";
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "short", day: "numeric" }).format(parsed);
}
