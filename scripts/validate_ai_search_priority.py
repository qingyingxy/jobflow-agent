"""Replay the observed cohort/product/timeout failures with the real configured model."""
import argparse
import asyncio
import hashlib
import html
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.config import get_settings
from src.domain.job import JobPosting
from src.domain.search_goal import SearchGoal
from src.services.discovery_matching import (
    apply_posting_availability,
    classify_discovery_job,
)
from src.services.search_goal_service import posting_stub
from src.services.source_understanding import VERSION, SourceUnderstanding

CASES = [
    ("【27届校招】Agent全栈开发工程师-大装置", {"job_type": "matched", "graduation_year": "matched", "role": "matched"}),
    ("【27届校招】大模型 Agent 算法研究员-大装置", {"job_type": "matched", "graduation_year": "matched", "role": "matched"}),
    ("【27届校招】AI 产品经理-大装置", {"job_type": "matched", "graduation_year": "matched", "role": "matched"}),
    ("2027AIDU-智能体算法工程师(J99969)", {"job_type": "pending", "graduation_year": "pending"}),
    ("高性能服务研发实习生-2027 届", {"job_type": "excluded"}),
    # The captured subject says 2027 while the title says 2028: retain that
    # contradiction, but the explicit internship type already excludes the job.
    ("大模型算法工程师-2028届实习", {"job_type": "excluded", "graduation_year": "pending"}),
]


async def main(args):
    settings = get_settings()
    if not args.live or settings.structured_model_provider == "fake":
        raise SystemExit("Use --live with a real configured model. This sends saved public job text only.")
    folder = ROOT / "artifacts" / ("ai-priority-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S"))
    folder.mkdir()
    baseline = args.database.resolve(strict=True)
    with sqlite3.connect(baseline.as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(folder / "trial.db") as target:
        source.backup(target)
    engine = create_engine("sqlite:///" + (folder / "trial.db").as_posix())
    events, rows = [], []
    started = monotonic()
    with Session(engine) as session:
        goal = session.get(SearchGoal, args.goal_id)
        if not goal:
            raise ValueError("Goal missing from supplied validation database")
        runtime = SourceUnderstanding(settings, query=goal.query, conditions=goal.conditions,
            on_event=lambda kind, data: events.append({"kind": kind, **data}))
        for title, expected in CASES:
            posting = session.scalar(select(JobPosting).where(JobPosting.title == title))
            if not posting:
                raise ValueError(f"Missing validation case: {title}")
            stub = posting_stub(posting)
            original_attempt = (stub.recruitment_context or {}).get("source_review_attempt", {})
            before = apply_posting_availability(classify_discovery_job(stub, query=goal.query, conditions=goal.conditions), posting)
            updated = await runtime.review(stub, query=goal.query, conditions=goal.conditions)
            attempt = updated.recruitment_context.get("source_review_attempt", {})
            retries = []
            if attempt.get("error_code") == "semantic_timeout":
                # Isolated acceptance of the next due retry, without waiting a
                # minute. Production cooldown and original database stay intact.
                retries.append({**attempt, "controlled_cooldown_expiry": True})
                updated.recruitment_context["source_review_attempt"] = {**attempt, "next_retry_at": None}
                retry = SourceUnderstanding(settings, query=goal.query, conditions=goal.conditions,
                    on_event=lambda kind, data: events.append({"kind": kind, **data}))
                updated = await retry.review(updated, query=goal.query, conditions=goal.conditions)
            posting.recruitment_context = updated.recruitment_context
            session.commit()
            after = apply_posting_availability(classify_discovery_job(updated, query=goal.query, conditions=goal.conditions), posting)
            actual = {check["field"]: check["status"] for check in after.checks}
            row = {"title": title, "url": stub.detail_url, "raw_content": stub.raw_content,
                "source_sha256": hashlib.sha256(stub.raw_content.encode()).hexdigest(),
                "unchanged_body": stub.raw_content == updated.raw_content,
                "before": before.as_dict(job_posting_id=posting.id), "after": after.as_dict(job_posting_id=posting.id),
                "expected_fields": expected, "passed": all(actual.get(k) == v for k, v in expected.items()),
                "original_attempt": original_attempt, "attempt": updated.recruitment_context.get("source_review_attempt"),
                "controlled_retries": retries}
            rows.append(row)
            print(json.dumps({"title": title, "passed": row["passed"], "actual": actual,
                              "error": (row["attempt"] or {}).get("error_code")}, ensure_ascii=False), flush=True)
    report = {"scope": "known_failure_cases_real_model_saved_body_replay_not_independent_accuracy_or_live_recall",
        "version": VERSION, "page_reads": 0, "passed": sum(row["passed"] for row in rows), "total": len(rows),
        "elapsed_seconds": round(monotonic() - started, 3), "model_calls": len([e for e in events if "duration_ms" in e]),
        "rows": rows, "events": events}
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    cards = []
    for row in rows:
        checks = "".join(f'<tr><td>{html.escape(c["field"])}</td><td>{html.escape(c["status"])}</td>'
                         f'<td>{html.escape(c["reason"])}</td><td>{html.escape(chr(10).join(c["evidence"]))}</td></tr>'
                         for c in row["after"]["checks"])
        cards.append(f'<article><h2>{html.escape(row["title"])}</h2><p>{"通过" if row["passed"] else "未通过"} · '
                     f'<a href="{html.escape(row["url"], quote=True)}">官网来源</a></p><table>{checks}</table>'
                     f'<details><summary>原始正文（未修改）</summary><pre>{html.escape(row["raw_content"])}</pre></details></article>')
    (folder / "report.html").write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<title>AI 判断升级回放验收</title><style>body{font:16px/1.6 system-ui;max-width:1200px;margin:40px auto;padding:0 24px;background:#f5f7fa;color:#172331}article{background:white;padding:24px;margin:20px 0;border:1px solid #dce1e8;border-radius:12px}table{border-collapse:collapse;width:100%;font-size:14px}td{padding:10px;border:1px solid #ddd;vertical-align:top}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
        f'<h1>AI 判断升级回放验收：{report["passed"]}/{report["total"]}</h1>'
        f'<p>仅回放已知失败样本，不代表独立准确率或全网找回率。官网读取0次；模型调用{report["model_calls"]}次；'
        f'耗时{report["elapsed_seconds"]}秒。写入独立数据库副本。</p>' + "".join(cards) + '</html>', encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"rows", "events"}} | {"report": str(folder / "report.html")}, ensure_ascii=False))
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--database", type=Path, default=ROOT / "artifacts/personal-trial-20261018-224735/trial.db")
    parser.add_argument("--goal-id", default="goal_510142e137774f3ea1f7")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
