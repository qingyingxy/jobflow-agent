"""Read two bounded rounds of selected sources, using an existing trial DB."""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--database", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--sources", nargs="*", default=["jd", "xpeng", "bytedance"])
parser.add_argument("--rounds", type=int, choices=range(1, 5), default=2)
parser.add_argument("--ai-ranking", action="store_true", help="Use production AI listing ordering")
parser.add_argument("--resume-state", type=Path, help="Continue the states from a saved validation round")
parser.add_argument("--recheck-companies", action="store_true", help="Reverify saved candidates only in a DB under artifacts/")
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
if args.recheck_companies and not args.database.resolve().is_relative_to(ROOT / "artifacts"):
    parser.error("Company rechecks require an isolated database under artifacts/")
os.environ["APP_ENV"] = "testing"
os.environ["DATABASE_URL"] = "sqlite:///" + args.database.resolve().as_posix()
from sqlalchemy import select

from src.config import get_settings
from src.domain.search_goal import SearchGoal
from src.infrastructure.database import SessionLocal
from src.services.browser_job_reader import PlaywrightBrowserJobReader
from src.services.company_registry import (
    enabled_company_source_hosts,
    enabled_company_sources,
)
from src.services.direct_recruitment_search import DirectRecruitmentSearch
from src.services.url_reader import SafeHTTPReader


async def main():
    settings = get_settings()
    with SessionLocal() as session:
        goal = session.scalar(select(SearchGoal).where(SearchGoal.user_id == "local-user").order_by(SearchGoal.updated_at.desc()))
        query = goal.query
        if args.recheck_companies:
            from src.domain.company_source import DiscoveredCompany
            from src.services.company_discovery import CompanyDiscoveryAgent

            class SavedOnly:
                async def discover(self):
                    return []

            results = []
            async with PlaywrightBrowserJobReader(timeout_seconds=12).reuse() as recheck_browser:
                for row in session.scalars(select(DiscoveredCompany).where(DiscoveredCompany.user_id == goal.user_id)):
                    worker = CompanyDiscoveryAgent(session, user_id=goal.user_id, run_id="final-evidence-recheck", query=query,
                        reader=SafeHTTPReader(timeout_seconds=8, max_retries=0, proxy=settings.url_fetch_proxy,
                            proxy_allowed_hosts=enabled_company_source_hosts(), proxy_allow_unlisted_hosts=settings.url_fetch_proxy_allow_unlisted_hosts),
                        browser=recheck_browser, provider_factory=lambda _: SavedOnly(), client_factory=lambda: None,
                        on_event=lambda *_: None, verification_timeout=40)
                    await worker.verify(row)
                    results.append({"company": row.company, "status": row.status, "reason": row.reason,
                        "homepage_url": row.homepage_url, "career_url": row.career_url, "evidence": row.evidence})
            (args.output / "companies.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(json.dumps([{k: v for k, v in row.items() if k != "evidence"} for row in results], ensure_ascii=False), flush=True)
        sources = [s for s in enabled_company_sources(session=session, user_id=goal.user_id)
                   if s.id in args.sources or s.company in args.sources]
        hosts = enabled_company_source_hosts(session=session, user_id=goal.user_id)
    reader = SafeHTTPReader(timeout_seconds=8, max_retries=0, proxy=settings.url_fetch_proxy,
        proxy_allowed_hosts=hosts, proxy_allow_unlisted_hosts=settings.url_fetch_proxy_allow_unlisted_hosts)
    browser = PlaywrightBrowserJobReader(timeout_seconds=12)
    states = json.loads(args.resume_state.read_text(encoding="utf-8"))["states"] if args.resume_state else {}
    async with browser.reuse():
        for number in range(1, args.rounds + 1):
            events, found = [], []
            from src.services.source_understanding import SourceUnderstanding
            runtime = SourceUnderstanding(settings, query=query,
                on_event=lambda kind, data, events=events: events.append({"kind": kind, **data})) if args.ai_ranking else None
            direct = DirectRecruitmentSearch(sources=sources, query=query, reader=reader, browser=browser,
                states=states, company_seconds=30, company_concurrency=2,
                understanding=runtime,
                on_event=lambda kind, data, events=events: events.append({"kind": kind, **data}))
            await direct.discover(found.extend)
            states = direct.states
            report = {"events": events, "candidates": [{"url": c.source_url, "company": c.company_hint, "title": c.title_hint} for c in found], "states": states}
            (args.output / f"round-{number}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(json.dumps({"round": number, "results": [e for e in events if e["kind"] == "direct_search"]}, ensure_ascii=False), flush=True)


asyncio.run(main())
