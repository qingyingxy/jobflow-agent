"""Evaluate fixed official jobs without confusing source replay with retrieval."""

import argparse
import hashlib
import html
import json
import sqlite3
import sys
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.domain.discovery import DiscoveryRun, JobLead
from src.domain.job import JobPosting
from src.services.discovery_matching import (
    apply_posting_availability,
    classify_discovery_job,
    search_filter_conditions,
)
from src.services.discovery_sources import JobStub
from src.services.job_role_review import load_role_review
from src.services.job_url import canonical_job_url
from src.services.search_goal_service import posting_stub
from src.services.source_understanding import checked_decisions


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def frozen_results(data, recorded, now):
    """Revalidate captured model citations against unchanged public source text."""
    interpretations = {r["id"]: r for r in recorded["results"]}
    results = []
    for sample in data["samples"]:
        digest = hashlib.sha256(sample["raw_content"].encode()).hexdigest()
        if digest != sample["source_sha256"]:
            raise ValueError(f"Frozen source changed: {sample['id']}")
        context = dict(sample.get("recruitment_context", {}))
        record = interpretations[sample["id"]].get("understanding")
        if record:
            context["source_understanding"] = record
        stub = JobStub(**{k: sample[k] for k in (
            "source_id", "source_job_id", "title", "company", "locations", "job_type", "raw_content",
        )}, detail_url=sample["source_url"], published_at=None, recruitment_context=context)
        # These are audited captured official pages, not a fresh network read.
        posting = SimpleNamespace(verification_status="VERIFIED_OFFICIAL",
                                  availability_status=sample["captured_availability_status"],
                                  last_verified_at=now, source_url=sample["source_url"],
                                  recruitment_context=context)
        # This is an explicit archival replay, not the current AI decision path.
        # Validate the original version/fingerprint and retain that version on
        # every citation; never relabel old output with today's prompt version.
        match = classify_discovery_job(stub, query=data["query"], primary=False)
        if record:
            decisions = checked_decisions(stub, search_filter_conditions(data["query"]), version=record["version"])
            if not decisions:
                raise ValueError(f"Invalid archived interpretation: {sample['id']}")
            checks = tuple(decisions.get(c["field"], c) if c["status"] == "pending" else c for c in match.checks)
            unresolved = [c for c in checks if c["status"] != "matched"]
            states = {c["status"] for c in checks}
            match = replace(match, checks=checks, match_tier="expanded" if unresolved else "strict",
                filter_status="excluded" if "excluded" in states else "pending" if "pending" in states else "matched",
                mismatch_reasons=tuple(c["field"] for c in unresolved),
                mismatch_labels=tuple(c["reason"] for c in unresolved),
                decision_policy="archived_hybrid", decision_version=record["version"])
        match = apply_posting_availability(match, posting, now=now)
        results.append({"id": sample["id"], "company": sample["company"], "title": sample["title"],
                        "url": sample["source_url"], "source_sha256": digest,
                        "expected_review_status": sample["expected_review_status"],
                        "expected_filter_status": sample["expected_filter_status"],
                        "expected_fields": sample["expected"],
                        "actual_fields": {c["field"]: c["status"] for c in match.checks},
                        "review_status": match.review_status, "filter_status": match.filter_status,
                        "checks": match.checks, "audit_note": sample["audit_note"]})
    return results


def observed_results(data, report, database):
    uri = database.resolve(strict=True).as_uri() + "?mode=ro"
    engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True))
    try:
        with Session(engine) as session:
            run = session.get(DiscoveryRun, report["run_id"])
            if not run or run.search_query != data["query"]:
                raise ValueError("Observed run is missing or has a different target")
            ids = [r["job_posting_id"] for r in report["matches"]]
            jobs = list(session.scalars(select(JobPosting).where(JobPosting.id.in_(ids))))
            if len(jobs) != len(set(ids)):
                raise ValueError("Observed run database is incomplete")
            now = run.finished_at or run.started_at
            classified = {}
            for job in jobs:
                stub = posting_stub(job)
                match = apply_posting_availability(classify_discovery_job(
                    stub, query=run.search_query, conditions=run.goal_conditions,
                    role_review=load_role_review(session, user_id=run.user_id, job=stub, query=run.search_query)
                ), job, now=now.replace(tzinfo=UTC) if now.tzinfo is None else now)
                classified[canonical_job_url(job.source_url)] = {
                    "title": job.title, "job_id": job.id, "url": job.source_url,
                    "review_status": match.review_status, "filter_status": match.filter_status,
                    "source_sha256": hashlib.sha256(job.raw_content.encode()).hexdigest(),
                    "new_to_run_baseline": job.id not in (run.library_baseline or {}),
                    "checks": match.checks,
                }
            leads = {canonical_job_url(lead["url"]) for lead in report["leads"]}
            # A verified redirect can change query parameters. The persisted
            # lead/posting relationship proves identity without dropping selectors.
            aliases = {}
            by_id = {item["job_id"]: item for item in classified.values()}
            for lead in session.scalars(select(JobLead).where(
                JobLead.discovery_run_id == run.id, JobLead.user_id == run.user_id,
                JobLead.status.in_(["VERIFIED", "DUPLICATE"]),
            )):
                if lead.job_posting_id in by_id:
                    aliases[canonical_job_url(lead.source_url)] = by_id[lead.job_posting_id]
            retrieval = []
            for sample in data["samples"]:
                key = canonical_job_url(sample["source_url"])
                match = classified.get(key) or aliases.get(key)
                retrieval.append({"id": sample["id"], "title": sample["title"],
                    "expected_review_status": sample["expected_review_status"],
                    "retrieval": "verified_detail" if match else "lead_only" if key in leads else "not_found",
                    "observed": match,
                    "same_source_text": bool(match and match["source_sha256"] == sample["source_sha256"])})
            counts = Counter(m["review_status"] for m in classified.values())
            return {"run_id": run.id, "total_jobs": len(jobs), "review_counts": dict(counts),
                    "fully_confirmed": sum(m["filter_status"] == "matched" for m in classified.values()),
                    "retrieval_counts": dict(Counter(r["retrieval"] for r in retrieval)),
                    "priority_sample_count": sum(s["expected_review_status"] == "recommended" for s in data["samples"]),
                    "priority_samples_retrieved": sum(r["expected_review_status"] == "recommended" and r["retrieval"] == "verified_detail" for r in retrieval),
                    "wrongly_excluded_priority_samples": sum(r["expected_review_status"] == "recommended" and r["observed"] is not None and r["observed"]["review_status"] == "excluded" for r in retrieval),
                    "retrieved_priority_samples_still_pending": sum(r["expected_review_status"] == "recommended" and r["observed"] is not None and r["observed"]["review_status"] == "pending" for r in retrieval),
                    "samples": retrieval, "jobs": list(classified.values()),
                    "original_metrics": report["metrics"]}
    finally:
        engine.dispose()


def evaluate(args):
    data, recorded = read_json(args.dataset), read_json(args.recorded)
    results = frozen_results(data, recorded, datetime(2026, 10, 18, tzinfo=UTC))
    fields = [(r["actual_fields"].get(k), v) for r in results for k, v in r["expected_fields"].items()]
    summary = {
        "sample_count": len(results),
        "correct_review_status": sum(r["review_status"] == r["expected_review_status"] for r in results),
        "correct_filter_status": sum(r["filter_status"] == r["expected_filter_status"] for r in results),
        "correct_fields": sum(a == b for a, b in fields), "field_count": len(fields),
        "review_counts": dict(Counter(r["review_status"] for r in results)),
        "fully_confirmed": sum(r["filter_status"] == "matched" for r in results),
        "wrongly_excluded": sum(r["expected_review_status"] != "excluded" and r["review_status"] == "excluded" for r in results),
        "incorrectly_recommended": sum(r["expected_review_status"] != "recommended" and r["review_status"] == "recommended" for r in results),
    }
    if bool(args.run_report) != bool(args.database):
        raise ValueError("Pass both --run-report and --database, or neither for frozen replay only")
    observed = observed_results(data, read_json(args.run_report), args.database) if args.database else None
    report = {"dataset": str(args.dataset), "recorded_semantics": str(args.recorded),
              "observed_database": str(args.database), "observed_report": str(args.run_report),
              "mode": "frozen_source_and_recorded_model_replay_plus_observed_run_audit" if observed else "frozen_source_and_recorded_model_replay",
              "model_calls": 0, "page_reads": 0, "summary": summary, "results": results, "observed": observed,
              "limitations": ["11条已见开发样本；助手核对原文、用户确认范围，不是独立人工金标或未见样本准确率。",
                              "复用此前真实模型输出，重新校验原文引用；本轮未调用模型或重新访问招聘网站。",
                              "找回率只针对这11条固定样本及所选历史搜索；完整页面读取不代表新增，缓存与新读按原运行指标另列。",
                              "全条件确认仅指当前搜索条件和开放状态，不代表简历匹配或保证可以投递。"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    labels = {"recommended": "优先查看", "pending": "待核实", "excluded": "明确不符",
              "verified_detail": "找到并读到正文", "lead_only": "仅找到线索", "not_found": "本轮未找到", "not_evaluated": "未评估实搜"}
    rows = []
    observations = observed["samples"] if observed else [{"observed": None, "retrieval": "not_evaluated"} for _ in results]
    for result, observation in zip(results, observations, strict=True):
        observed_match = observation["observed"]
        status = labels[observed_match["review_status"]] if observed_match else "—"
        rows.append(f'<tr><td><a href="{html.escape(result["url"], quote=True)}">{html.escape((result["company"] or "公司待确认") + " · " + result["title"])}</a></td>'
                    f'<td>{labels[result["expected_review_status"]]}</td><td>{labels[result["review_status"]]}</td>'
                    f'<td>{labels[observation["retrieval"]]}</td><td>{status}</td><td>{html.escape(result["audit_note"])}</td></tr>')
    observed_summary = (f"历史实搜重新分组：{observed['total_jobs']} 个岗位中 {observed['review_counts'].get('recommended', 0)} 个优先查看，全部条件确认 {observed['fully_confirmed']}。"
                        f"固定样本中的相关岗位读到正文 {observed['priority_samples_retrieved']}/{observed['priority_sample_count']}；读到后仍待核实 {observed['retrieved_priority_samples_still_pending']}。") if observed else "本报告仅做冻结正文回放，未评估实际搜索找回情况。"
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>岗位展示与找回验收</title>
<style>body{{max-width:1380px;margin:40px auto;padding:0 24px;font:16px/1.7 system-ui;color:#243348;background:#f8fafc}}h1{{font-size:28px}}table{{border-collapse:collapse;background:white;width:100%;font-size:14px}}td,th{{border:1px solid #dce2ea;padding:12px;text-align:left;vertical-align:top}}a{{color:#2758a5}}.scroll{{overflow:auto}}li{{margin:8px 0}}</style>
<h1>岗位展示与固定样本验收 · 2026-10-18</h1><p>目标：北京 / 上海 · AI Agent / RAG / AI 产品 · 2027 届校招。</p>
<p>固定正文回放：展示判断 {summary['correct_review_status']}/{len(results)}；字段判断 {summary['correct_fields']}/{len(fields)}。
优先查看 {summary['review_counts'].get('recommended', 0)}，待核实 {summary['review_counts'].get('pending', 0)}，明确不符 {summary['review_counts'].get('excluded', 0)}；全部条件确认 {summary['fully_confirmed']}。</p>
<p>{observed_summary}</p>
<div class="scroll"><table><tr><th>真实官网岗位</th><th>预期展示</th><th>冻结正文回放</th><th>历史实搜找回</th><th>实搜证据下展示</th><th>原文核对说明</th></tr>{''.join(rows)}</table></div>
<p>冻结正文与历史搜索可能读取到不同版本。完整证据、文本哈希和逐字段判断见同名 JSON。</p>
<ul>{''.join('<li>'+html.escape(s)+'</li>' for s in report['limitations'])}</ul></html>'''
    args.output.with_suffix(".html").write_text(page, encoding="utf-8")
    print(json.dumps({"report": str(args.output), "summary": summary,
                      "observed": {k:v for k,v in observed.items() if k not in {"samples", "jobs", "original_metrics"}} if observed else None}, ensure_ascii=False))
    return summary["correct_review_status"] == len(results) and summary["correct_filter_status"] == len(results) and summary["correct_fields"] == len(fields)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("datasets/real_job_understanding_acceptance_20261018.json"))
    parser.add_argument("--recorded", type=Path, default=Path("datasets/real_job_understanding_recorded_v3_20261018.json"))
    parser.add_argument("--run-report", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/job-review-acceptance-v3-20261018.json"))
    sys.exit(0 if evaluate(parser.parse_args()) else 1)
