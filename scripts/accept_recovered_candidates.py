"""Audit the fixed 26-candidate recovery cohort using public pages and a DB copy."""
import argparse
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


async def main(args):
    from sqlalchemy.orm import Session

    from src.config import get_settings
    from src.domain.discovery import LeadProvider
    from src.domain.search_goal import SearchGoal
    from src.infrastructure.database import engine
    from src.services.browser_job_reader import PlaywrightBrowserJobReader
    from src.services.company_registry import (
        enabled_company_source_hosts,
        enabled_company_sources,
    )
    from src.services.discovery_matching import (
        apply_posting_availability,
        classify_discovery_job,
    )
    from src.services.job_lead_service import JobLeadService
    from src.services.search_goal_service import posting_stub
    from src.services.source_understanding import SourceUnderstanding

    inputs = ROOT / "artifacts/company-evidence-repairs-20261019"
    candidates = {}
    paths = args.candidates or [inputs / name for name in (
        "final-validation/round-1.json", "final-validation/round-2.json",
        "fragment-recovery/round-1.json", "fragment-recovery/round-2.json")]
    for path in paths:
        for row in json.loads(path.read_text(encoding="utf-8"))["candidates"]:
            candidates.setdefault(row["url"], {**row, "cohort_file": str(path)})
    with Session(engine) as session:
        goal = session.get(SearchGoal, "goal_510142e137774f3ea1f7")
        query, conditions = goal.query, goal.conditions
        sources = enabled_company_sources(session=session, user_id=goal.user_id)
        hosts = enabled_company_source_hosts(session=session, user_id=goal.user_id)
    events, results = [], []
    settings = get_settings().model_copy(update={"web_search_understanding_mode": "ai",
                                                "web_search_semantic_max_calls": 30})
    runtime = SourceUnderstanding(settings, query=query, conditions=conditions,
        on_event=lambda kind, data: events.append({"kind": kind, **data}))
    if not runtime.primary:
        raise RuntimeError("Real model required for this acceptance run")
    slots = asyncio.Semaphore(2)
    browser = PlaywrightBrowserJobReader(timeout_seconds=20)

    async def check(index, candidate):
        async with slots:
            folder = args.output / f"{index:02d}"
            folder.mkdir()
            started = monotonic()
            row = {"index": index, **candidate}

            class CapturingReader:
                safety_checker = browser.safety_checker

                async def read(self, url):
                    page = await browser.read(url)
                    (folder / "page.html").write_text(page.raw_html, encoding="utf-8")
                    (folder / "page.txt").write_text(page.visible_text, encoding="utf-8")
                    row.update(page_read=True, final_url=page.final_url, page_title=page.title,
                               redirect_chain=page.redirect_chain, text_chars=len(page.visible_text))
                    save(folder / "result.json", row)
                    return page

            with Session(engine, expire_on_commit=False) as session:
                service = JobLeadService(session, understanding=runtime)
                lead = service.create_lead(user_id="recovered-candidate-acceptance", provider=LeadProvider.EXTERNAL_AGENT,
                    source_url=row["url"], company_hint=row["company"], title_hint=row["title"][:200])
                row["lead_id"] = lead.id
                source = next(s for s in sources if s.company == row["company"])
                # This cohort consists exclusively of observed official outbound links.
                # Carry the company's proof, without trusting the shared ATS host.
                entry = source.official_homepage_url or source.career_url
                service.record_official_link(user_id=lead.user_id, lead_id=lead.id, source_url=row["url"],
                    entry_url=entry, from_url=source.hiring_evidence_url or source.career_url, company=source.company)
                try:
                    async with asyncio.timeout(100):
                        verified = await service.verify_browser(user_id=lead.user_id, lead_id=lead.id,
                            reader=CapturingReader(), official_hosts=set(hosts), official_only=True)
                        posting = verified.posting
                        stub = await runtime.review(posting_stub(posting), query=query, conditions=conditions)
                        posting.recruitment_context = stub.recruitment_context
                        session.commit()
                        match = apply_posting_availability(classify_discovery_job(stub, query=query, conditions=conditions), posting)
                        (folder / "scoped.txt").write_text(posting.raw_content, encoding="utf-8")
                        row.update(verified=True, job_id=posting.id, parsed_title=posting.title,
                            match=match.as_dict(job_posting_id=posting.id), context=stub.recruitment_context)
                except Exception as error:  # noqa: BLE001 - save every candidate's outcome
                    row.update(verified=False, error_code=getattr(error, "code", type(error).__name__), error=str(error))
            row["seconds"] = round(monotonic() - started, 2)
            save(folder / "result.json", row)
            results.append(row)
            save(args.output / "results.json", {"query": query, "conditions": conditions,
                "cohort_size": len(candidates), "results": sorted(results, key=lambda r: r["index"]),
                "model_calls": runtime.calls, "events": events})
            print(json.dumps({"index": index, "company": row["company"], "title": row.get("parsed_title", ""),
                "read": row.get("page_read", False), "verified": row["verified"],
                "review": row.get("match", {}).get("review_status"), "error": row.get("error_code"),
                "seconds": row["seconds"]}, ensure_ascii=False), flush=True)

    async with browser.reuse():
        await asyncio.gather(*(check(i, c) for i, c in enumerate(candidates.values(), 1)))
    engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, nargs="+", help="Explicit supplemental cohort; never merged with the original denominator")
    args = parser.parse_args()
    args.output = args.output.resolve()
    if not args.output.is_relative_to(ROOT / "artifacts"):
        parser.error("Acceptance writes must remain under artifacts/")
    args.output.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(args.output / "trial.db") as target:
        source.backup(target)
    os.environ["DATABASE_URL"] = "sqlite:///" + (args.output / "trial.db").as_posix()
    os.environ["APP_ENV"] = "testing"
    asyncio.run(main(args))
