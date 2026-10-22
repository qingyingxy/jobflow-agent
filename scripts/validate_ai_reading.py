"""Replay saved official pages through production verification using the real model.

Only a new database copy is written. Website reads use captured HTML; --live
authorizes bounded requests containing public job text to the configured model.
"""
import argparse
import asyncio
import html
import json
import sqlite3
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main(args):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.config import get_settings
    from src.domain.discovery import LeadProvider
    from src.services.discovery_matching import (
        apply_posting_availability,
        classify_discovery_job,
    )
    from src.services.job_lead_service import JobLeadService
    from src.services.search_goal_service import posting_stub
    from src.services.source_understanding import SourceUnderstanding
    from src.services.url_reader import FetchedResponse

    folder = ROOT / "artifacts" / ("ai-reading-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S"))
    folder.mkdir()
    report = json.loads(args.database.with_name("report.json").read_text(encoding="utf-8"))
    query = report["query"]
    with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as source:
        source.row_factory = sqlite3.Row
        rows = source.execute(
            "select v.source_url,v.field_evidence from lead_verifications v "
            "join job_leads l on l.id=v.lead_id where l.discovery_run_id=? "
            "and l.failure_code='browser_navigation_unavailable' and v.result='SNAPSHOT'",
            (report["run_id"],)).fetchall()
        with sqlite3.connect(folder / "trial.db") as target:
            source.backup(target)
    settings = get_settings().model_copy(update={"web_search_understanding_mode": "ai"})
    events = []
    runtime = SourceUnderstanding(settings, query=query, on_event=lambda kind, data: events.append({"kind": kind, **data}))
    if not runtime.primary:
        raise RuntimeError("A real configured model and semantic mode are required")
    engine = create_engine("sqlite:///" + (folder / "trial.db").as_posix())
    results = []
    # Separate sessions prevent interleaved model requests from sharing ORM state.
    async def check(row):
        url = row["source_url"]
        raw = json.loads(row["field_evidence"])["raw_html"]

        class SnapshotReader:
            async def fetch(self, target):
                if target != url:
                    raise ValueError("Snapshot replay never fetches new website pages")
                return FetchedResponse(requested_url=url, final_url=url, status_code=200,
                                       content_type="text/html", body=raw.encode())

        started = monotonic()
        result = {"url": url}
        with Session(engine, expire_on_commit=False) as session:
            service = JobLeadService(session, understanding=runtime)
            lead = service.create_lead(user_id="ai-reading-validation", provider=LeadProvider.EXTERNAL_AGENT, source_url=url)
            try:
                verified = await service.verify_url(user_id=lead.user_id, lead_id=lead.id,
                    reader=SnapshotReader(), official_hosts={urlsplit(url).hostname}, official_only=True)
                stub = posting_stub(verified.posting)
                stub = await runtime.review(stub, query=query)
                verified.posting.recruitment_context = stub.recruitment_context
                session.commit()
                match = apply_posting_availability(classify_discovery_job(stub, query=query), verified.posting)
                result.update(recovered=True, title=stub.title, checks=match.checks,
                              review_status=match.review_status, filter_status=match.filter_status,
                              understanding=stub.recruitment_context.get("source_understanding"))
            except Exception as error:  # noqa: BLE001 - isolate each saved page's outcome
                result.update(recovered=False, error_code=getattr(error, "code", type(error).__name__))
        result["elapsed_seconds"] = round(monotonic() - started, 3)
        results.append(result)
        print(json.dumps({k: v for k, v in result.items() if k in {"title", "recovered", "error_code", "review_status", "elapsed_seconds"}}, ensure_ascii=False), flush=True)

    started = monotonic()
    await asyncio.gather(*(check(row) for row in rows))
    output = {"query": query, "mode": "real_model_saved_public_html_production_verification",
        "limitation": "Development snapshots, not independent recall or live website coverage. Personal database unchanged.",
        "elapsed_seconds": round(monotonic() - started, 3), "model_calls": runtime.calls,
        "samples": len(rows), "recovered": sum(r["recovered"] for r in results),
        "statuses": dict(Counter(r.get("review_status", "failed") for r in results)),
        "results": results, "events": events}
    (folder / "report.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    cells = []
    for result in results:
        evidence = "<br>".join(html.escape(f'{c["field"]}: {c["status"]} — {c["reason"]}') for c in result.get("checks", []))
        cells.append(f'<tr><td>{html.escape(result.get("title", result["url"]))}</td><td>{html.escape(result.get("review_status", result.get("error_code", "")))}</td><td>{evidence}</td></tr>')
    page = '<!doctype html><meta charset="utf-8"><title>AI岗位理解验收</title><style>body{max-width:1100px;margin:36px auto;font:16px/1.7 system-ui;color:#243348}td,th{padding:12px;border:1px solid #ddd;vertical-align:top}table{border-collapse:collapse}</style>'
    page += f'<h1>AI岗位理解验收</h1><p>使用真实模型处理已保存官网原文，恢复 {output["recovered"]}/{len(rows)} 个岗位。模型调用 {runtime.calls} 次，总耗时 {output["elapsed_seconds"]} 秒。</p><p>未重新访问招聘网站；使用独立数据库副本。样本属于已见开发样本，不能代表全网找回率或独立准确率。</p><table><tr><th>岗位</th><th>查看建议</th><th>条件与依据</th></tr>'+''.join(cells)+'</table>'
    (folder / "report.html").write_text(page, encoding="utf-8")
    engine.dispose()
    print(json.dumps({"folder": str(folder), "summary": {k: output[k] for k in ("samples", "recovered", "statuses", "model_calls", "elapsed_seconds")}}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--live", action="store_true", required=True)
    asyncio.run(main(parser.parse_args()))
