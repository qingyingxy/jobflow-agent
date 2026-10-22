"use client";

import { useId, useRef, useState, type ReactNode } from "react";

export default function SearchActivity({ summary, continuation, children }: {
  summary: ReactNode; continuation?: ReactNode; children: ReactNode;
}) {
  const [panel, setPanel] = useState<"continue" | "details" | null>(null);
  const id = useId();
  const continueButton = useRef<HTMLButtonElement>(null);
  const detailsButton = useRef<HTMLButtonElement>(null);
  return <div className="search-activity" onKeyDown={event => {
    if (event.key !== "Escape" || !panel) return;
    event.stopPropagation();
    (panel === "continue" ? continueButton : detailsButton).current?.focus();
    setPanel(null);
  }}>
    <div className="search-activity-bar">
      {summary}
      <div className="search-activity-actions" aria-label="搜索操作">
        {continuation && <button ref={continueButton} type="button" aria-expanded={panel === "continue"} aria-controls={`${id}-continue`}
          onClick={() => setPanel(panel === "continue" ? null : "continue")}>继续查找<span aria-hidden="true">⌄</span></button>}
        <button ref={detailsButton} type="button" aria-expanded={panel === "details"} aria-controls={`${id}-details`}
          onClick={() => setPanel(panel === "details" ? null : "details")}>搜索详情<span aria-hidden="true">⌄</span></button>
      </div>
    </div>
    {continuation && <section id={`${id}-continue`} className="company-continue" aria-label="选择公司继续查找" hidden={panel !== "continue"}>
      <p>选择尚未查完的公司，接着查找岗位。</p>
      <div>{continuation}</div>
    </section>}
    <section id={`${id}-details`} className="search-details" aria-label="搜索详情" hidden={panel !== "details"}>
      <div className="search-process-content">{children}</div>
    </section>
  </div>;
}
