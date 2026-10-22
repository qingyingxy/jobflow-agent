"""Audit captured live results and recovery trials without network or DB writes."""

import argparse
import hashlib
import html
import json
import sqlite3
import sys
from collections import Counter
from datetime import UTC
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.domain.discovery import DiscoveryRun
from src.domain.job import JobPosting
from src.services.discovery_matching import (
    apply_posting_availability,
    classify_discovery_job,
)
from src.services.job_header_facts import effective_job_locations
from src.services.job_role_review import load_role_review
from src.services.search_goal_service import posting_stub


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(args):
    live = read_json(args.run_dir / "report.json")
    labels = read_json(args.audit_dir / "live-sample-labels.json")
    uri = (args.run_dir / "trial.db").resolve(strict=True).as_uri() + "?mode=ro"
    engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True))
    rows = []
    try:
        with Session(engine) as session:
            run = session.get(DiscoveryRun, live["run_id"])
            if run is None or run.search_query != live["query"]:
                raise ValueError("Live report and database do not agree")
            now = run.finished_at or run.started_at
            if now.tzinfo is None:
                now = now.replace(tzinfo=UTC)
            observed = {m["job_posting_id"]: m for m in live["matches"]}
            for sample in labels["samples"]:
                job = session.get(JobPosting, sample["job_id"])
                if job is None or job.id not in observed:
                    raise ValueError(f"Sample absent from live run: {sample['job_id']}")
                digest = hashlib.sha256(job.raw_content.encode()).hexdigest()
                if digest != sample["source_sha256"]:
                    raise ValueError(f"Audited source changed: {sample['job_id']}")
                stub = posting_stub(job)
                match = apply_posting_availability(
                    classify_discovery_job(
                        stub,
                        query=run.search_query,
                        conditions=run.goal_conditions,
                        role_review=load_role_review(
                            session, user_id=run.user_id, job=stub,
                            query=run.search_query,
                        ),
                    ),
                    job, now=now,
                )
                locations = effective_job_locations(job)
                rows.append({
                    **sample,
                    "stored_locations": job.locations,
                    "effective_locations": locations,
                    "locations_correct": locations == sample["expected_locations"],
                    "stored_locations_correct": job.locations == sample["expected_locations"],
                    "original_review_status": observed[job.id]["review_status"],
                    "review_status": match.review_status,
                    "review_correct": match.review_status == sample["expected_review_status"],
                    "checks": match.checks,
                })
    finally:
        engine.dispose()

    queue = [read_json(p) for p in args.queue_report]
    recovery = read_json(args.recovery_report)
    frozen = read_json(args.frozen_report)
    failures = Counter(lead["failure_code"] for lead in live["leads"] if lead["failure_code"])
    summary = {
        "sample_count": len(rows),
        "review_correct": sum(r["review_correct"] for r in rows),
        "stored_locations_correct": sum(r["stored_locations_correct"] for r in rows),
        "effective_locations_correct": sum(r["locations_correct"] for r in rows),
        "live_metrics": live["metrics"],
        "live_status": live["status"],
        "live_elapsed_seconds": live["elapsed_seconds"],
        "live_review_counts": dict(Counter(m["review_status"] for m in live["matches"])),
        "live_lead_failure_counts": dict(failures),
        "queue_batches": sum(len(r["batches"]) for r in queue),
        "queue_page_attempts": sum(r["page_attempts"] for r in queue),
        "queue_checks": queue[-1]["checks"],
        "recovery_attempts": len(recovery["results"]),
        "recovery_successes": sum(r["success"] for r in recovery["results"]),
        "recovery_checks": recovery["checks"],
        "frozen_summary": frozen["summary"],
    }
    report = {
        "mode": "captured_live_trial_plus_offline_header_repair_audit",
        "query": live["query"],
        "summary": summary,
        "samples": rows,
        "evidence": {
            "live": str(args.run_dir / "report.json"),
            "labels": str(args.audit_dir / "live-sample-labels.json"),
            "queue": [str(p) for p in args.queue_report],
            "recovery": str(args.recovery_report),
            "frozen": str(args.frozen_report),
        },
        "limitations": [
            "12条额外岗位由助手核对原文，修补使用了这些样本；不是独立人工金标或未见测试集。",
            "联网搜索使用已有岗位库的副本及8家公司范围，180秒到期为PARTIAL；不是全网或冷启动测试。",
            "17.047秒与31.701秒为服务端记录；新读正文不等于新发现岗位，新增推荐数为0。",
            "16/37为详情读取指标；官网来源读取另计2/6。关闭岗位、读取失败、入口和预算延后不能混为一类。",
            "历史失败2/2恢复来自独立重读试验；本轮完整搜索的自动重试指标为0，不能混算。",
            "模型续查前4批仍剩1条目标，第5批完成；本次汇总及页头修复验证只读取保存原文，没有重新联网或调用模型。",
            "优先查看允许届别或开放状态缺失并保留提示，不代表个人资格全部通过。",
        ],
    }
    output = args.audit_dir / "final-report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    status = {"recommended": "优先查看", "pending": "待核实", "excluded": "明确不符"}
    table = "".join(
        '<tr><td><a href="' + html.escape(r["source_url"], quote=True) + '">'
        + html.escape(r["title"]) + "</a></td><td>"
        + status[r["expected_review_status"]] + " → " + status[r["review_status"]]
        + "</td><td>" + html.escape("、".join(r["stored_locations"]) or "未提取")
        + "</td><td>" + html.escape("、".join(r["effective_locations"]))
        + "</td><td>" + html.escape(r["audit_note"]) + "</td></tr>"
        for r in rows
    )
    limitations = "".join("<li>" + html.escape(s) + "</li>" for s in report["limitations"])
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>搜索与恢复验收 · 2026-10-18</title><style>
body{{max-width:1300px;margin:36px auto;padding:0 24px;font:16px/1.7 system-ui;color:#243348;background:#f8fafc}}
h1{{font-size:28px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}}
.card,table{{background:white}}.card{{padding:18px;border:1px solid #dce2ea;border-radius:10px}}b{{font-size:24px}}
table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{border:1px solid #dce2ea;padding:10px;text-align:left;vertical-align:top}}
.scroll{{overflow:auto}}a{{color:#2758a5}}li{{margin:8px 0}}</style>
<h1>搜索与恢复验收 · 2026-10-18</h1>
<p>目标：北京 / 上海 · AI Agent / RAG / AI 产品 · 2027 届校招。</p>
<div class="cards"><div class="card">首次优先查看<br><b>17.047 秒</b><br>首次新读正文推荐：31.701 秒</div>
<div class="card">详情读取成功<br><b>16 / 37</b><br>43.24%，来源读取另计 2 / 6</div>
<div class="card">本轮优先查看<br><b>8 条</b><br>新增推荐：0 条</div>
<div class="card">额外样本城市完整度<br><b>{summary['stored_locations_correct']} → {summary['effective_locations_correct']} / 12</b><br>展示判断：{summary['review_correct']} / 12</div></div>
<h2>已完成与剩余问题</h2>
<p>通用页头识别支持标题同行城市、紧凑元数据行及国家前缀；导航动作文字不再充当地点。已有记录刷新时从原文补取，保留原始字段与证据。</p>
<p>独立试验中的两条历史失败官网页均重新读到正文。两条曾受语义预算影响的目标岗位在总计5批续查后均完成理解，页面读取0次。原有11条固定样本回放：展示11/11、字段44/44。</p>
<p>当前主要缺口仍是有效新增与读取覆盖：180秒实搜产生19条结果（8条优先查看、3条待核实、8条明确不符），详情读取16/37，且新增推荐0条。应优先定位动态页面与正文识别失败，并减少重复与明确不符线索占用预算。</p>
<h2>额外12条原文审计与修复回放</h2><div class="scroll"><table>
<thead><tr><th>官网岗位</th><th>审计预期 → 当前分组</th><th>原存地点</th><th>刷新后地点</th><th>原文判断</th></tr></thead><tbody>{table}</tbody></table></div>
<h2>验收口径</h2><ul>{limitations}</ul><p>逐项证据与复现输入：<a href="final-report.json">完整 JSON 报告</a>。</p></html>'''
    output.with_suffix(".html").write_text(page, encoding="utf-8")
    print(json.dumps({"report": str(output), "summary": summary}, ensure_ascii=False))
    return (
        all(r["review_correct"] and r["locations_correct"] for r in rows)
        and all(summary["queue_checks"].values())
        and all(summary["recovery_checks"].values())
        and frozen["summary"]["correct_review_status"] == frozen["summary"]["sample_count"]
        and frozen["summary"]["correct_filter_status"] == frozen["summary"]["sample_count"]
        and frozen["summary"]["correct_fields"] == frozen["summary"]["field_count"]
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    parser.add_argument("--queue-report", type=Path, action="append", required=True)
    parser.add_argument("--recovery-report", type=Path, required=True)
    parser.add_argument("--frozen-report", type=Path, required=True)
    sys.exit(0 if evaluate(parser.parse_args()) else 1)
