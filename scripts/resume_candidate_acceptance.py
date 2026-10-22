"""Finish unresolved acceptance interpretations from already saved page bodies."""
import asyncio
import json
import os
import sys
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "artifacts/job-acceptance-20261019"
os.environ["DATABASE_URL"] = "sqlite:///" + (OUT / "trial.db").as_posix()
os.environ["APP_ENV"] = "testing"


async def main():
    from sqlalchemy.orm import Session

    from src.config import get_settings
    from src.infrastructure.database import engine
    from src.services.company_registry import enabled_company_source_hosts
    from src.services.discovery_matching import (
        apply_posting_availability,
        classify_discovery_job,
    )
    from src.services.job_lead_service import JobLeadService
    from src.services.search_goal_service import posting_stub
    from src.services.source_understanding import SourceUnderstanding

    report = json.loads((OUT / "results.json").read_text(encoding="utf-8"))
    selected = [r for r in report["results"] if not r["verified"] or any(
        c.get("diagnosis") == "not_extracted" for c in r["match"]["checks"])]
    settings = get_settings()
    events, results = [], []
    runtime = SourceUnderstanding(settings.model_copy(update={"web_search_understanding_mode": "ai",
        "web_search_semantic_timeout_seconds": settings.web_search_semantic_retry_timeout_seconds,
        "web_search_semantic_max_calls": 30}), query=report["query"], conditions=report["conditions"],
        on_event=lambda kind, data: events.append({"kind": kind, **data}))
    with Session(engine) as session:
        hosts = enabled_company_source_hosts(session=session, user_id="local-user")

    class NoDetailRefetch:
        async def fetch(self, url):
            raise AssertionError("Saved-body continuation must not fetch a detail page")

    slots = asyncio.Semaphore(2)

    async def check(original):
        async with slots:
            row = {"index": original["index"], "url": original["url"]}
            start = monotonic()
            with Session(engine, expire_on_commit=False) as session:
                service = JobLeadService(session, understanding=runtime)
                try:
                    verified = await service.verify_url(user_id="recovered-candidate-acceptance",
                        lead_id=original["lead_id"], reader=NoDetailRefetch(), official_hosts=set(hosts), official_only=True)
                    posting = verified.posting
                    stub = await runtime.review(posting_stub(posting), query=report["query"], conditions=report["conditions"])
                    posting.recruitment_context = stub.recruitment_context
                    session.commit()
                    match = apply_posting_availability(classify_discovery_job(stub, query=report["query"], conditions=report["conditions"]), posting)
                    row.update(verified=True, parsed_title=posting.title, match=match.as_dict(job_posting_id=posting.id),
                               context=stub.recruitment_context)
                    (OUT / f'{row["index"]:02d}' / "recovered-scoped.txt").write_text(posting.raw_content, encoding="utf-8")
                except Exception as error:  # noqa: BLE001 - independent bounded outcomes
                    row.update(verified=False, error_code=getattr(error, "code", type(error).__name__), error=str(error))
            row["seconds"] = round(monotonic() - start, 2)
            results.append(row)
            (OUT / "recovery.json").write_text(json.dumps({"results": sorted(results, key=lambda r: r["index"]),
                "model_calls": runtime.calls, "events": events, "detail_refetches": 0}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(json.dumps({"index": row["index"], "verified": row["verified"],
                "review": row.get("match", {}).get("review_status"), "error": row.get("error_code"),
                "seconds": row["seconds"]}, ensure_ascii=False), flush=True)

    await asyncio.gather(*(check(r) for r in selected))
    engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
