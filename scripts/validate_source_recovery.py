"""Bounded live entrance and staged company-discovery checks on a DB backup."""
import argparse
import asyncio
import json
import os
import sqlite3
import sys
from copy import deepcopy
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--seconds", type=int, default=420)
parser.add_argument("--entrance-states", type=Path)
parser.add_argument("--entrances-only", action="store_true")
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
database = (args.output / "trial.db").resolve()
with sqlite3.connect(args.source.resolve().as_uri() + "?mode=ro", uri=True) as origin, sqlite3.connect(database) as copy:
    origin.backup(copy)
os.environ["DATABASE_URL"] = "sqlite:///" + database.as_posix()
os.environ["APP_ENV"] = "testing"

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from src.config import get_settings
from src.domain.company_source import CompanyDiscoveryTask
from src.domain.search_goal import SearchGoal
from src.infrastructure.database import SessionLocal
from src.services.browser_job_reader import PlaywrightBrowserJobReader
from src.services.company_discovery_queue import (
    discovery_queue_summary,
    enqueue_company_discovery,
    run_company_discovery_step,
)
from src.services.company_registry import (
    enabled_company_source_hosts,
    enabled_company_sources,
)
from src.services.direct_recruitment_search import DirectRecruitmentSearch
from src.services.search_goal_service import utc_time
from src.services.url_reader import SafeHTTPReader

command.upgrade(Config(str(ROOT / "alembic.ini")), "head")


def save(name, data):
    (args.output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


async def main():
    settings = get_settings()
    with SessionLocal() as session:
        goal = session.scalar(select(SearchGoal).where(SearchGoal.user_id == "local-user").order_by(SearchGoal.updated_at.desc()))
        goal_id, query = goal.id, goal.query
        states = deepcopy(goal.company_search_state.get("sources", {}))
        if args.entrance_states:
            states = json.loads(args.entrance_states.read_text(encoding="utf-8"))["states"]
        if not args.entrances_only:
            enqueue_company_discovery(session, goal, retry=True)
    sources = enabled_company_sources(["jd", "xpeng", "alibaba", "bytedance"])
    reader = SafeHTTPReader(timeout_seconds=8, max_retries=0, proxy=settings.url_fetch_proxy,
        proxy_allowed_hosts=enabled_company_source_hosts(), proxy_allow_unlisted_hosts=settings.url_fetch_proxy_allow_unlisted_hosts)
    browser = PlaywrightBrowserJobReader(timeout_seconds=15)
    events, candidates = [], []
    direct = DirectRecruitmentSearch(sources=sources, query=query, reader=reader, browser=browser,
        states={s.id: states.get(s.id, {}) for s in sources}, company_seconds=30, company_concurrency=2,
        on_event=lambda kind, data: events.append({"kind": kind, **data}))
    async with browser.reuse():
        await direct.discover(candidates.extend)
    save("entrances.json", {"events": events, "candidates": [{"url": c.source_url, "company": c.company_hint,
        "title": c.title_hint} for c in candidates], "states": direct.states})
    print(json.dumps({"entrances": [e for e in events if e["kind"] == "direct_search"]}, ensure_ascii=False), flush=True)
    if args.entrances_only:
        return
    start, steps = monotonic(), []
    while monotonic() - start < args.seconds:
        worked = await run_company_discovery_step()
        with SessionLocal() as session:
            goal = session.get(SearchGoal, goal_id)
            summary = discovery_queue_summary(session, goal)
            task = session.get(CompanyDiscoveryTask, goal_id)
            state = deepcopy(task.state)
        steps.append({"seconds": round(monotonic()-start, 2), **summary})
        save("discovery-progress.json", {"steps": steps, "state": state})
        print(json.dumps(steps[-1], ensure_ascii=False, default=str), flush=True)
        if summary["status"] not in {"queued", "running"}:
            break
        if not worked:
            from datetime import UTC, datetime
            if summary["next_run_at"] and (utc_time(summary["next_run_at"]) - datetime.now(UTC)).total_seconds() > 10:
                break  # Pending ownership sources resume later; no unbounded live run.
            await asyncio.sleep(3)
    save("result.json", {"seconds": round(monotonic()-start, 2), "entrance_results": [e for e in events if e["kind"] == "direct_search"],
        "discovery": summary, "steps": len(steps)})


asyncio.run(main())
