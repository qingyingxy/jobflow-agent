"use client";

import { useEffect, useState } from "react";
import { parseApiTimestamp } from "./api-time";

export default function SearchProgress({ status, startedAt, finishedAt, verified,
  unread, reconnecting }: {
  status: string; startedAt: string; finishedAt?: string | null; verified: number;
  unread: number; reconnecting: boolean;
}) {
  const [now, setNow] = useState(() => Date.now());
  const running = status === "RUNNING";
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);
  const elapsed = Math.max(0, Math.floor(((finishedAt ? parseApiTimestamp(finishedAt).getTime() : now)
    - parseApiTimestamp(startedAt).getTime()) / 1000));
  const duration = Number.isFinite(elapsed) ? (elapsed < 60 ? `${elapsed} 秒` : `${Math.floor(elapsed / 60)} 分 ${elapsed % 60} 秒`) : "";
  return <div className="search-status" aria-label="本轮搜索统计" aria-busy={running}>
    <div className="search-status-line"><span className={`search-status-dot${running ? " is-running" : ""}`} aria-hidden="true" />
      <span>{running ? "正在搜索与核验" : status === "FAILED" ? "搜索未完成" : status === "PARTIAL" ? "搜索部分完成" : "本轮搜索完成"}{duration ? ` · ${duration}` : ""}</span>
      <span>{verified} 个岗位正文已核验{unread > 0 ? ` · ${unread} 个待核验` : ""}</span>
    </div>
    {reconnecting && <p role="status">进度连接暂时中断，正在自动重连。已有岗位仍可查看，请勿重复启动搜索。</p>}
  </div>;
}
