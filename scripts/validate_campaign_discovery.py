"""Start or resume an isolated public discovery trial, then check company cards."""
import argparse
import asyncio
import hashlib
import json
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import src.domain  # noqa: F401 - register mapped models
from src.config import get_settings
from src.domain.campaign import CampaignDiscoveryTask, CampaignWatch
from src.domain.company_source import DiscoveredCompany
from src.infrastructure.database import Base
from src.services.campaign_discovery import enqueue_discovery, run_discovery_step
from src.services.campaign_scheduler import run_campaign_check
from src.services.campaign_service import campaign_snapshot
from src.services.company_identity_evidence import company_name_matches


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def hashes():
    return {p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted([*Path("src").rglob("*.py"), Path(__file__)])}


async def main(args):
    folder = Path(args.output_dir)
    folder.mkdir(parents=True, exist_ok=False)
    source = Path(args.source_db).resolve() if args.source_db else None
    if source:
        with (sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original,
              sqlite3.connect(folder / "trial.db") as copied):
            original.backup(copied)
    engine = create_engine("sqlite:///" + (folder / "trial.db").as_posix())
    if args.fresh_start:
        Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    settings = get_settings()
    frozen = hashes()
    manifest = {"started_at": datetime.now(UTC), "source_db": str(source) if source else None, "source_hashes": frozen,
                "fresh_start": args.fresh_start, "year": args.year,
                "fresh_reads": args.fresh_reads, "discovery_cycles": args.discovery_cycles,
                "recheck_companies": args.recheck_companies,
                "limits": "Public sample only; built-in registry retained, no supplied company shortlist in fresh mode. Same-session cycles, not multi-day stability or global recall."}
    save(folder / "manifest.json", manifest)
    with factory() as session:
        if args.fresh_start:
            enqueue_discovery(session, "campus-discovery-trial", args.year)
        task = session.scalar(select(CampaignDiscoveryTask))
        if not task or session.query(CampaignDiscoveryTask).count() != 1:
            raise ValueError("Expected exactly one public discovery trial task")
        user_id, year = task.user_id, task.year
        if source:
            # Explicitly retry this isolated copy through the production retry
            # entrypoint so stopped planner budgets are renewed as in the UI.
            task.status = "blocked"
            session.commit()
            task = enqueue_discovery(session, user_id, year)
        rows = list(session.scalars(select(DiscoveredCompany).where(DiscoveredCompany.user_id == user_id)))
        task.status, task.next_run_at = "queued", datetime.now(UTC)
        state = deepcopy(task.state)
        state["verification_attempts"] = {}
        if args.fresh_reads and state.get("planner"):
            state["planner"]["evidence"] = {}
        for row in rows:
            row.last_checked_at = None  # Explicit one-shot retry; production cooldown stays intact.
            if args.fresh_reads:
                evidence = deepcopy(row.evidence)
                evidence["corroboration_candidates"] = list(dict.fromkeys([
                    *evidence.get("corroboration_candidates", []),
                    *([evidence["corroboration"]["url"]] if evidence.get("corroboration") else []),
                    *(p["url"] for p in evidence.get("read_cache", []) if any(
                        domain in p["url"] for domain in (".edu.cn/", ".gov.cn/", ".ac.cn/"))
                        and company_name_matches(row.company, p["text"])),
                ]))
                evidence["discovered_urls"] = list(dict.fromkeys([
                    *evidence.get("discovered_urls", []), *(p["url"] for p in evidence.get("read_cache", []))]))
                evidence["read_cache"], evidence["read_attempts"] = [], []
                row.evidence = evidence
        task.state = state
        for company_id in args.recheck_companies:
            watch = session.scalar(select(CampaignWatch).where(CampaignWatch.user_id == user_id,
                CampaignWatch.year == year, CampaignWatch.company_id == company_id))
            if watch is None:
                raise ValueError("Recheck company must already exist in the isolated trial")
            watch.status, watch.next_check_at, watch.error = "queued", datetime.now(UTC), None
        session.commit()

    def snapshot(name):
        with factory() as session:
            data = campaign_snapshot(session, user_id, year)
            rows = list(session.scalars(select(DiscoveredCompany).where(DiscoveredCompany.user_id == user_id)))
            ids = {r.id for r in rows}
            data["company_cards"] = [c for c in data["company_cards"] if c["company_id"] in ids]
            data["companies"] = [{"id": r.id, "company": r.company, "status": r.status, "reason": r.reason,
                                  "homepage_url": r.homepage_url, "career_url": r.career_url,
                                  "evidence": r.evidence} for r in rows]
            data["discovery_state"] = session.scalar(select(CampaignDiscoveryTask)).state
            data["watch_diagnostics"] = [{"company_id": w.company_id, "status": w.status, "error": w.error,
                                           "cache": w.cache} for w in session.scalars(select(CampaignWatch))]
            data["source_hashes_unchanged"] = hashes() == frozen
            save(folder / name, data)
            return data

    snapshot("baseline.json")
    for cycle in range(args.discovery_cycles + 1):
        if cycle:
            with factory() as session:
                enqueue_discovery(session, user_id, year)
        started = monotonic()
        for step in range(64):
            await run_discovery_step(factory, settings=settings, now=datetime.now(UTC) + timedelta(seconds=5))
            data = snapshot("progress.json")
            print(json.dumps({"cycle": cycle, "step": step + 1,
                              **{k: data["discovery"][k] for k in ("status", "queries_completed", "companies_found", "companies_verified")}},
                             ensure_ascii=False), flush=True)
            with factory() as session:
                current = session.scalar(select(CampaignDiscoveryTask))
                unattempted = any(r.status == "pending" and not current.state["verification_attempts"].get(r.id)
                                  and r.last_checked_at is None for r in session.scalars(select(DiscoveredCompany)))
            if data["discovery"]["status"] in {"waiting", "blocked", "completed"} and not unattempted:
                break
        for _ in range(30):
            with factory() as session:
                pending = session.scalar(select(CampaignWatch.id).where(
                    CampaignWatch.user_id == user_id, CampaignWatch.status == "queued"))
            if not pending:
                break
            await run_campaign_check(factory, settings=settings)
            snapshot("progress.json")
            print(json.dumps({"cycle": cycle, "checked_watch": pending}, ensure_ascii=False), flush=True)
        data = snapshot(f"cycle-{cycle}.json")
        print(json.dumps({"cycle_finished": cycle, "elapsed_seconds": round(monotonic() - started, 1),
                          "companies": [{k: r[k] for k in ("company", "status", "reason")} for r in data["companies"]],
                          "cards": [{k: c[k] for k in ("company", "recruitment_status", "status_note")} for c in data["company_cards"]]},
                         ensure_ascii=False), flush=True)
    snapshot("result.json")
    engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    start = parser.add_mutually_exclusive_group(required=True)
    start.add_argument("--source-db", help="Resume a copy of an existing public test database")
    start.add_argument("--fresh-start", action="store_true", help="Discover from an empty test database without a company shortlist")
    parser.add_argument("--year", type=int, default=2027)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--fresh-reads", action="store_true")
    parser.add_argument("--recheck-companies", nargs="*", default=[],
                        help="Retry existing company checks in the isolated copy; does not constrain discovery")
    parser.add_argument("--discovery-cycles", type=int, default=0, choices=range(3))
    parser.add_argument("--live", action="store_true", required=True)
    asyncio.run(main(parser.parse_args()))
