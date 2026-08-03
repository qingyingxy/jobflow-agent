"use client";

import { useState } from "react";

type BackendStatus = "idle" | "checking" | "online" | "offline";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const statusCopy: Record<BackendStatus, string> = {
  idle: "等待检查",
  checking: "正在连接",
  online: "后端在线",
  offline: "暂时离线",
};

export default function Home() {
  const [backendStatus, setBackendStatus] = useState<BackendStatus>("idle");

  async function checkBackend() {
    setBackendStatus("checking");
    try {
      const response = await fetch(`${apiUrl}/health`, { cache: "no-store" });
      setBackendStatus(response.ok ? "online" : "offline");
    } catch {
      setBackendStatus("offline");
    }
  }

  return (
    <main className="page-shell">
      <div className="ambient-glow ambient-glow-one" />
      <div className="ambient-glow ambient-glow-two" />

      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark">JF</span>
          <span className="brand-name">JobFlow Agent</span>
        </div>
        <div className="build-label">
          <span className="status-dot" />
          M01 · SQLite-first
        </div>
      </header>

      <section className="hero-grid">
        <div className="hero-copy">
          <p className="eyebrow">CAREER OPERATING SYSTEM / 01</p>
          <h1>
            把求职判断，
            <em>变成一条</em>
            可追踪的路径。
          </h1>
          <p className="hero-description">
            从岗位发现到申请状态，JobFlow 用真实经历作为证据，让每一次推荐都能被解释、被确认、被回看。
          </p>
          <div className="hero-actions">
            <button className="primary-button" onClick={checkBackend} type="button">
              {backendStatus === "checking" ? "连接中…" : "检查后端连接"}
              <span aria-hidden="true">↗</span>
            </button>
            <span className={`connection-state state-${backendStatus}`} aria-live="polite">
              <span className="state-pip" />
              {statusCopy[backendStatus]}
            </span>
          </div>
        </div>

        <div className="signal-board" aria-label="JobFlow 核心能力">
          <div className="board-caption">
            <span>THE SIGNAL BOARD</span>
            <span>LOCAL BUILD 0.1</span>
          </div>
          <div className="board-line" />
          <div className="signal-row signal-row-featured">
            <span className="signal-index">01</span>
            <div>
              <strong>岗位要求</strong>
              <p>解析非结构化 JD</p>
            </div>
            <span className="signal-arrow">↗</span>
          </div>
          <div className="signal-row">
            <span className="signal-index">02</span>
            <div>
              <strong>经历证据</strong>
              <p>拒绝无依据的匹配</p>
            </div>
            <span className="signal-arrow">↗</span>
          </div>
          <div className="signal-row">
            <span className="signal-index">03</span>
            <div>
              <strong>申请流程</strong>
              <p>由状态机持续记录</p>
            </div>
            <span className="signal-arrow">↗</span>
          </div>
          <div className="board-footnote">AGENT SUGGESTS · HUMAN DECIDES</div>
        </div>
      </section>

      <section className="principles-grid">
        <article className="principle-card principle-card-accent">
          <span className="card-number">A / 01</span>
          <h2>有依据的推荐</h2>
          <p>每条匹配结论，都回到用户真实完成过的项目与事实。</p>
        </article>
        <article className="principle-card">
          <span className="card-number">B / 02</span>
          <h2>用户掌握确认权</h2>
          <p>Agent 提出材料建议，用户决定哪些内容最终进入申请。</p>
        </article>
        <article className="principle-card principle-card-dark">
          <span className="card-number">C / 03</span>
          <h2>过程可以回看</h2>
          <p>申请状态和关键事件被保存，下一步行动不再依赖记忆。</p>
        </article>
      </section>

      <footer className="footer-line">
        <span>JobFlow Agent / 求职岗位分析与申请管理</span>
        <span>FastAPI · Next.js · SQLite</span>
      </footer>
    </main>
  );
}
