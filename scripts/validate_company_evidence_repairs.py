"""Recheck existing company candidates on a copy, then read verified listings."""
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
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--skip-listings", action="store_true")
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
database = (args.output / "trial.db").resolve()
with sqlite3.connect(args.source.resolve().as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(database) as copy:
    source.backup(copy)
os.environ["DATABASE_URL"] = "sqlite:///" + database.as_posix()
os.environ["APP_ENV"] = "testing"

from sqlalchemy import select

from src.config import get_settings
from src.domain.company_source import DiscoveredCompany
from src.domain.search_goal import SearchGoal
from src.infrastructure.database import SessionLocal
from src.services.browser_job_reader import PlaywrightBrowserJobReader
from src.services.company_discovery import CompanyDiscoveryAgent
from src.services.company_registry import (
    enabled_company_source_hosts,
    enabled_company_sources,
)
from src.services.direct_recruitment_search import DirectRecruitmentSearch
from src.services.url_reader import SafeHTTPReader


def save(name, data):
    (args.output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


class SavedEvidenceOnly:
    async def discover(self):
        return []


async def main():
    settings = get_settings()
    events, results = [], []
    with SessionLocal() as session:
        goal = session.scalar(select(SearchGoal).where(SearchGoal.user_id == "local-user").order_by(SearchGoal.updated_at.desc()))
        reader = SafeHTTPReader(timeout_seconds=8, max_retries=0, proxy=settings.url_fetch_proxy,
            proxy_allowed_hosts=enabled_company_source_hosts(), proxy_allow_unlisted_hosts=settings.url_fetch_proxy_allow_unlisted_hosts)
        browser = PlaywrightBrowserJobReader(timeout_seconds=12)
        rows = list(session.scalars(select(DiscoveredCompany).where(DiscoveredCompany.user_id == goal.user_id)))
        async with browser.reuse():
            for row in rows:
                before = {"status": row.status, "reason": row.reason, "homepage_url": row.homepage_url}
                agent = CompanyDiscoveryAgent(session, user_id=goal.user_id, run_id="evidence-recheck", query=goal.query,
                    reader=reader, browser=browser, provider_factory=lambda _: SavedEvidenceOnly(), client_factory=lambda: None,
                    on_event=lambda kind, data: events.append({"kind": kind, **data}), verification_timeout=40)
                started = monotonic()
                await agent.verify(row)
                results.append({"company": row.company, "id": row.id, "before": before, "status": row.status,
                    "reason": row.reason, "homepage_url": row.homepage_url, "career_url": row.career_url,
                    "seconds": round(monotonic() - started, 2), "evidence": row.evidence})
                save("companies.json", {"results": results, "events": events})
                print(json.dumps({k: v for k, v in results[-1].items() if k != "evidence"}, ensure_ascii=False), flush=True)
            if not args.skip_listings:
                sources = [s for s in enabled_company_sources(session=session, user_id=goal.user_id) if s.id in {r.id for r in rows if r.status == "verified"}]
                found = []
                direct = DirectRecruitmentSearch(sources=sources, query=goal.query, reader=reader, browser=browser,
                    company_seconds=30, company_concurrency=2, on_event=lambda kind, data: events.append({"kind": kind, **data}))
                await direct.discover(found.extend)
                save("listings.json", {"candidates": [{"url": c.source_url, "company": c.company_hint, "title": c.title_hint} for c in found], "events": events, "states": direct.states})
                print(json.dumps([e for e in events if e["kind"] == "direct_search"], ensure_ascii=False), flush=True)


asyncio.run(main())
