"""Run the real continuation pipeline/model on a DB copy, with page reads disabled."""

import argparse
import asyncio
import html
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def write_html_report(report, path):
    labels = {"recommended": "优先查看", "pending": "待核实", "excluded": "明确不符"}
    fields = {"role": "岗位方向", "job_type": "招聘类型", "location": "工作地点", "graduation_year": "届别"}
    cards = []
    for row in report["results"]:
        checks = [c for c in row["after"]["checks"] if c["field"] in row["fields"]]
        evidence = "".join(
            '<p><strong>' + html.escape(fields.get(c["field"], c["field"])) + '：</strong>'
            + html.escape(c["reason"]) + '</p>'
            + ''.join('<blockquote>' + html.escape(q) + '</blockquote>' for q in c.get("evidence", []))
            for c in checks)
        unresolved = "；".join(c["reason"] for c in row["after"]["checks"] if c["status"] == "pending")
        cards.append(
            '<article><h2><a href="' + html.escape(row["url"], quote=True) + '">'
            + html.escape(row["title"]) + '</a></h2><p class="status">'
            + labels[row["before"]["review_status"]] + ' → ' + labels[row["after"]["review_status"]]
            + '</p>' + evidence + '<p class="note">仍需确认：' + html.escape(unresolved or "无") + '</p></article>')
    passed = sum(c["after"]["review_status"] == "recommended" for c in report["results"])
    checks = {"targets_present": "存在待恢复样本", "no_page_reads": "未读取招聘页面",
              "all_priority": "目标样本均进入优先查看", "source_unchanged": "原文与核验时间保持不变",
              "run_and_library_agree": "搜索记录、接口与岗位库结果一致", "availability_not_invented": "未补造开放状态",
              "deferred_preserved": "未入本批的样本仍可续查"}
    check_items = ''.join('<li>' + ('✓ ' if value else '✗ ') + checks[key] + '</li>' for key, value in report["checks"].items())
    deferred = report.get("deferred_targets", [])
    waiting = '<p>受每家公司最多 3 条、每批最多 8 条限制，另有 ' + str(len(deferred)) + ' 条样本留在后续批次：' + html.escape('、'.join(r["title"] for r in deferred)) + '。</p>' if deferred else ''
    page = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>岗位语义续查验收</title>
<style>body{{max-width:1080px;margin:40px auto;padding:0 22px;font:16px/1.7 system-ui;color:#203246;background:#f5f7fa}}
h1{{font-size:28px}}h2{{font-size:19px;margin:0}}a{{color:#20598c}}article,.summary{{background:white;border:1px solid #dce4ec;border-radius:10px;padding:22px;margin:18px 0}}
.status{{font-weight:600;color:#246b54}}.note{{color:#60512e;background:#fff8e4;padding:12px}}blockquote{{margin:12px 0;padding:12px 18px;border-left:3px solid #8aa8c3;background:#f7f9fc}}
li{{margin:5px 0}}.muted{{color:#596b7b}}@media(max-width:600px){{body{{margin:18px auto}}article,.summary{{padding:16px}}}}</style></head><body>
<h1>岗位语义续查验收</h1><p>{html.escape(report['query'])}</p>
<div class="summary"><strong>本次待恢复样本：{passed}/{report['target_count']} 进入优先查看</strong>
<p>正式续查链路耗时 {report['elapsed_seconds']} 秒；招聘页面读取 {report['page_reads']} 次；模型字段调用 {report['model_calls']} 次（含同批其他岗位）。</p>
<p>已保存正文按正常批次选择，再调用真实模型理解。开放状态与严格匹配条件仍单独标注。</p>{waiting}<ul>{check_items}</ul></div>
{''.join(cards)}<div class="summary"><h2>验收范围</h2><ul>{''.join('<li>' + html.escape(s) + '</li>' for s in report['limitations'])}</ul>
<p class="muted">理解版本：{html.escape(report['semantic_version'])}。<a href="{html.escape(path.with_suffix('.json').name)}">查看完整 JSON 证据</a></p></div></body></html>'''
    path.write_text(page, encoding="utf-8")


async def validate(args, folder):
    from src.config import get_settings
    from src.domain.discovery import DiscoveryRun
    from src.domain.search_goal import SearchGoal
    from src.infrastructure.database import SessionLocal
    from src.services import multiround_search, web_search_service
    from src.services.discovery_matching import (
        apply_posting_availability,
        classify_discovery_job,
    )
    from src.services.discovery_results import current_run_matches
    from src.services.job_lead_service import JobLeadService
    from src.services.job_role_review import load_role_review
    from src.services.job_url import canonical_job_url
    from src.services.search_goal_service import SearchGoalService, posting_stub
    from src.services.source_understanding import VERSION, pending_review_fields
    from src.services.url_reader import SafeHTTPReader

    settings = get_settings().model_copy(update={
        "web_search_semantic_enabled": True, "web_search_semantic_max_calls": 8,
        "web_search_direct_sources_enabled": False, "company_discovery_enabled": False,
        "web_search_role_review_enabled": False, "web_search_max_rounds": 1,
        "web_search_budget_seconds": 60, "web_search_verification_budget_seconds": 60,
    })
    if settings.structured_model_provider == "fake":
        raise ValueError("This validation requires the configured real model")
    dataset = json.loads((ROOT / "datasets/real_job_understanding_acceptance_20261018.json").read_text(encoding="utf-8"))
    expected = {canonical_job_url(s["source_url"]): s for s in dataset["samples"] if s["expected_review_status"] == "recommended"}
    with SessionLocal() as session:
        goal = session.get(SearchGoal, args.goal_id)
        if not goal:
            raise ValueError("Goal is not present in the supplied database")
        goals = SearchGoalService(session)
        before, targeted = {}, {}
        for posting in goals.postings(goal.user_id):
            stub = posting_stub(posting)
            role = load_role_review(session, user_id=goal.user_id, job=stub, query=goal.query)
            match = apply_posting_availability(classify_discovery_job(stub, query=goal.query, conditions=goal.conditions, role_review=role), posting)
            before[posting.id] = {"title": posting.title, "url": posting.source_url,
                "raw_content": posting.raw_content, "last_verified_at": posting.last_verified_at,
                "availability_status": posting.availability_status, "checks": match.checks,
                "review_status": match.review_status, "filter_status": match.filter_status}
            needed = pending_review_fields(stub, query=goal.query, conditions=goal.conditions, role_review=role)
            if canonical_job_url(posting.source_url or "") in expected and needed:
                targeted[posting.id] = needed
        selected = [c.source_url for c in goals.refresh_candidates(goal.user_id, query=goal.query, conditions=goal.conditions)]
        selected_keys = {canonical_job_url(url) for url in selected}
        deferred = {k: v for k, v in targeted.items() if canonical_job_url(before[k]["url"]) not in selected_keys}
        targeted = {k: v for k, v in targeted.items() if k not in deferred}
        run = DiscoveryRun(id="semantic-resume-" + folder.name.removeprefix("semantic-resume-"),
            user_id=goal.user_id, source="web_search", source_url="https://example.com/controlled-empty-search",
            search_query=goal.query, search_goal_id=goal.id, search_goal_version=goal.version,
            goal_conditions=goal.conditions, library_baseline=goals.snapshot(goal.user_id, goal.query),
            started_at=datetime.now(UTC), status="RUNNING")
        session.add(run)
        session.commit()
        run_id, user_id, query = run.id, goal.user_id, goal.query
    print(json.dumps({"folder": str(folder), "targeted": [before[k]["title"] for k in targeted], "selected_count": len(selected)}, ensure_ascii=False), flush=True)

    class EmptySearch:
        source_id = "controlled-empty-search"

        async def discover(self):
            return []

    page_attempts = []

    async def forbid_page(*_args, **kwargs):
        page_attempts.append(kwargs.get("lead_id"))
        raise AssertionError("Cached continuation must not read a recruitment page")

    start = monotonic()
    with (
        patch.object(multiround_search, "get_settings", lambda: settings),
        patch.object(web_search_service, "create_web_search_provider", lambda *_a, **_k: EmptySearch()),
        # Isolate cached field continuation from unrelated unfinished listing
        # pages. All standard refresh selection and pipeline scheduling remain.
        patch.object(SearchGoalService, "resume_candidates", lambda *_a, **_k: []),
        patch.object(SafeHTTPReader, "fetch", forbid_page),
        patch.object(JobLeadService, "verify_url", forbid_page),
        patch.object(JobLeadService, "verify_browser", forbid_page),
    ):
        await multiround_search.execute_multiround_search(run_id=run_id, user_id=user_id, query=query,
                                                         company_ids=[], analysis_limit=0)

    with SessionLocal() as session:
        goals = SearchGoalService(session)
        run = session.get(DiscoveryRun, run_id)
        library = {m["job_posting_id"]: m for m in goals.library(user_id, args.goal_id)["result_matches"]}
        current = {m["job_posting_id"]: m for m in current_run_matches(session, [run])[run_id]}
        published = {m["job_posting_id"]: m for m in run.result_matches}
        jobs = {p.id:p for p in goals.postings(user_id)}
        next_batch = {canonical_job_url(c.source_url) for c in goals.refresh_candidates(user_id, query=query, conditions=run.goal_conditions)}
        deferred_results = [{"job_id": k, "title": before[k]["title"], "url": before[k]["url"],
                             "in_next_batch": canonical_job_url(before[k]["url"]) in next_batch}
                            for k in deferred]
        results = []
        for job_id, fields in targeted.items():
            posting, old = jobs[job_id], before[job_id]
            results.append({"job_id": job_id, "title": old["title"], "url": old["url"], "fields": fields,
                "before": {k:old[k] for k in ("review_status", "filter_status", "checks")},
                "after": library[job_id], "published": published.get(job_id), "run_api": current.get(job_id),
                "attempt": (posting.recruitment_context or {}).get("source_review_attempt"),
                "source_unchanged": posting.raw_content == old["raw_content"] and posting.last_verified_at == old["last_verified_at"] and posting.availability_status == old["availability_status"]})
        checks = {"targets_present": bool(results), "no_page_reads": not page_attempts,
            "all_priority": all(r["after"]["review_status"] == "recommended" for r in results),
            "source_unchanged": all(r["source_unchanged"] for r in results),
            "run_and_library_agree": all(r["published"] and r["run_api"] and r["published"]["review_status"] == r["run_api"]["review_status"] == r["after"]["review_status"] for r in results),
            "availability_not_invented": all(r["after"]["filter_status"] == "pending" for r in results),
            "deferred_preserved": all(pending_review_fields(posting_stub(jobs[k]), query=query, conditions=run.goal_conditions)
                                      for k in deferred)}
        model_calls = sum(1 for e in run.agent_trace if e.get("tool") == "source_understanding"
                          and e.get("details", {}).get("stage") == "job_source_understanding"
                          and e.get("duration_ms") is not None)
        report = {"mode": "real_model_and_search_pipeline_cached_continuation", "input_database": str(args.database),
            "query": query, "semantic_version": VERSION,
            "run_id": run_id, "elapsed_seconds": round(monotonic() - start, 2), "page_reads": len(page_attempts),
            "model_calls": model_calls,
            "selected_urls": selected, "target_count": len(results), "checks": checks,
            "deferred_targets": deferred_results,
            "metrics": run.usage_metrics, "results": results, "trace": run.agent_trace,
            "limitations": ["只修改数据库副本；真实模型经过正式搜索续查、持久化和展示重算链路。",
                "网络检索替换为空结果，跳过历史入口与线索续查并禁止页面读取；独立旧方向复核关闭，使用通用字段理解。",
                "这是已知开发样本的受控续查验收，不是全网检索或未见样本准确率。"]}
    path = folder / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_html_report(report, path.with_suffix(".html"))
    print(json.dumps({"report": str(path), "elapsed_seconds": report["elapsed_seconds"], "checks": checks, "metrics": report["metrics"]}, ensure_ascii=False), flush=True)
    return all(checks.values())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--goal-id", default="goal_510142e137774f3ea1f7")
    args = parser.parse_args()
    args.database = args.database.resolve(strict=True)
    folder = ROOT / "artifacts" / ("semantic-resume-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S"))
    folder.mkdir()
    with sqlite3.connect(args.database.as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(folder / "trial.db") as target:
        source.backup(target)
    os.environ["DATABASE_URL"] = "sqlite:///" + (folder / "trial.db").as_posix()
    sys.exit(0 if asyncio.run(validate(args, folder)) else 1)
