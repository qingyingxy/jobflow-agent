"use client";
import { apiError } from "./api-error";

import { useState } from "react";

export default function AccountPrivacy({ apiUrl, userId }: { apiUrl: string; userId: string }) {
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function request(remove: boolean) {
    if (busy || (remove && confirmation !== "删除我的数据")) return;
    setBusy(true); setMessage("");
    try {
      const response = await fetch(`${apiUrl}/api/account${remove ? "" : "/export"}`, {
        method: remove ? "DELETE" : "POST", headers: { "Content-Type": "application/json", "X-User-ID": userId },
        body: JSON.stringify(remove ? { confirmation: "DELETE_MY_DATA" } : { confirmed: true }),
      });
      if (!response.ok) { const body = await response.json(); throw new Error(apiError(body, "操作失败")); }
      if (remove) {
        for (const key of Object.keys(localStorage)) {
          if (key.startsWith(`jobflow-active-goal:${userId}`) || key.startsWith(`jobflow-goal-interval:${userId}:`)) localStorage.removeItem(key);
        }
        window.location.reload();
      } else {
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement("a"); link.href = url; link.download = "jobflow-data.zip"; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        setMessage("数据已导出，压缩包包含简历文件，请妥善保存。");
      }
    } catch (e) { setMessage(e instanceof Error ? e.message : "操作失败"); }
    finally { setBusy(false); }
  }
  return <details className="product-review"><summary>账户数据与隐私</summary>
    <p>导出当前用户的目标、岗位、经历、纠错和申请记录，以及本地简历文件。</p>
    <button type="button" disabled={busy} onClick={() => void request(false)}>导出我的数据</button>
    <h3>删除我的数据</h3>
    <p>这会永久删除当前用户的记录及简历文件。其他用户的数据保留。建议先导出备份。</p>
    <label>输入“删除我的数据”确认<input aria-label="删除数据确认" value={confirmation} onChange={e => setConfirmation(e.target.value)} /></label>
    <button type="button" disabled={busy || confirmation !== "删除我的数据"} onClick={() => void request(true)}>永久删除我的数据</button>
    {message && <p role="status">{message}</p>}
  </details>;
}
