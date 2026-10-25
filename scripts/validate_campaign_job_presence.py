"""Exercise real campus job discovery and persisted company cards in an isolated database."""
import argparse
import asyncio
import hashlib
import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import src.domain  # noqa: F401 - register database models
from src.config import get_settings
from src.domain.campaign import CampaignWatch, RecruitmentCampaign
from src.infrastructure.database import Base
from src.services.campaign_reader import create_campaign_reader
from src.services.campaign_service import campaign_payload, company_card, save_campaign
from src.services.company_registry import CompanySource, enabled_company_sources


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def hashes():
    paths = [*Path("src").rglob("*.py"), Path(__file__)]
    return {p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


async def main(args):
    folder = Path(args.output_dir)
    folder.mkdir(parents=True, exist_ok=False)
    sources = enabled_company_sources(args.companies) if args.companies else []
    if args.source_manifest:
        manifest_sources = json.loads(Path(args.source_manifest).read_text(encoding="utf-8"))["sources"]
        sources.extend(CompanySource(**{**item, "resource_hosts": tuple(item.get("resource_hosts", []))})
                       for item in manifest_sources
                       if not args.sample_companies or item["company"] in args.sample_companies)
    if args.source_db:
        uri = Path(args.source_db).resolve().as_uri() + "?mode=ro"
        previous = create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True))
        with Session(previous) as session:
            discovered = enabled_company_sources(session=session, user_id=args.source_user)
            sources.extend(s for s in discovered if s.entry_type == "discovered_official"
                           and (not args.discovered_companies or s.company in args.discovered_companies))
        previous.dispose()
    if len({s.id for s in sources}) != len(sources):
        raise ValueError("Duplicate sample companies")
    if not sources:
        raise ValueError("Provide companies or a source manifest with matching samples")
    initial_caches, cache_origin = {}, None
    if args.cache_from:
        cache_path = Path(args.cache_from)
        prior_manifest = json.loads((cache_path.parent / "manifest.json").read_text(encoding="utf-8"))
        if prior_manifest["year"] != args.year:
            raise ValueError("Recovery cache cohort does not match this trial")
        previous_round = json.loads(cache_path.read_text(encoding="utf-8"))
        initial_caches = {entry["source_id"]: entry["cache"] for entry in previous_round["results"]}
        cache_origin = {"path": cache_path.as_posix(), "sha256": hashlib.sha256(cache_path.read_bytes()).hexdigest(),
                        "source_ids": [s.id for s in sources if s.id in initial_caches]}
    settings = get_settings()
    frozen = hashes()
    manifest = {"started_at": datetime.now(UTC), "year": args.year, "rounds": args.rounds,
                "sources": [asdict(s) for s in sources], "source_hashes": frozen,
                "recovery_cache": cache_origin,
                "limits": "Fixed public sample; fresh web reads and Agent judgments with historical route hints; not global recall or multi-day stability."}
    save(folder / "manifest.json", manifest)
    engine = create_engine("sqlite:///" + (folder / "trial.db").as_posix())
    Base.metadata.create_all(engine)
    user_id = "campus-job-presence-trial"
    slots = asyncio.Semaphore(2)
    rounds = []
    for number in range(1, args.rounds + 1):
        if hashes() != frozen:
            raise RuntimeError("Source changed between rounds")
        results = []

        async def check(source, number, results):
            async with slots:
                with Session(engine) as session:
                    watch = session.scalar(select(CampaignWatch).where(CampaignWatch.company_id == source.id))
                    cache = watch.cache if watch else initial_caches.get(source.id, {})
                reader = create_campaign_reader(settings, sources)
                started = monotonic()
                try:
                    result = await asyncio.wait_for(reader.check(source, args.year, cache), timeout=reader.time_budget + 10)
                except Exception as error:  # noqa: BLE001 - retain diagnostics without raw provider errors
                    result = {"found": [], "cache": cache, "readable": False,
                              "error": type(error).__name__, "stats": {"stop_reason": "check_failed"}}
                now = datetime.now(UTC)
                with Session(engine) as session:
                    watch = session.scalar(select(CampaignWatch).where(CampaignWatch.company_id == source.id))
                    if watch is None:
                        watch = CampaignWatch(user_id=user_id, company_id=source.id, year=args.year)
                        session.add(watch)
                    watch.checked_at, watch.error, watch.cache = now, result["error"], result["cache"]
                    watch.status = "failed" if not result["readable"] else "partial" if result["error"] else "ready"
                    if result["readable"]:
                        watch.succeeded_at = now
                    for facts, url in result["found"]:
                        save_campaign(session, user_id, source, facts, url, now)
                    session.commit()
                    rows = session.scalars(select(RecruitmentCampaign).where(RecruitmentCampaign.company_id == source.id))
                    card = company_card(source, watch, [campaign_payload(r, now) for r in rows], args.year)
                pages = [{**p, "links": [{"url": link.url, "text": link.text} for link in p.get("links", [])]}
                         for p in getattr(reader, "page_history", []) or reader.pages.pages.values()]
                entry = {"company": source.company, "source_id": source.id,
                         "duration_seconds": round(monotonic() - started, 2), "card": card,
                         **result, "diagnostics": reader.diagnostics,
                         "pages": pages, "read_attempts": reader.pages.attempts}
                results.append(entry)
                results.sort(key=lambda r: next(i for i, s in enumerate(sources) if s.id == r["source_id"]))
                save(folder / f"round-{number}.json", {"round": number, "results": results})
                print(json.dumps({"round": number, "company": source.company,
                                  "status": card["recruitment_status"], "jobs": card["job_titles"],
                                  "seconds": entry["duration_seconds"], "error": entry["error"],
                                  "pages": result.get("stats", {}).get("pages_read")}, ensure_ascii=False), flush=True)

        await asyncio.gather(*(check(source, number, results) for source in sources))
        if hashes() != frozen:
            raise RuntimeError("Source changed during round")
        rounds.append(results)
    summary = {"finished_at": datetime.now(UTC), "source_hashes_unchanged": hashes() == frozen,
               "rounds": args.rounds, "companies": [{"company": s.company,
                   "statuses": [next(r["card"]["recruitment_status"] for r in rs if r["source_id"] == s.id) for rs in rounds],
                   "seconds": [next(r["duration_seconds"] for r in rs if r["source_id"] == s.id) for rs in rounds]}
                   for s in sources]}
    save(folder / "summary.json", summary)
    engine.dispose()
    print(json.dumps({"completed_rounds": len(rounds), "companies": len(sources)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companies", nargs="+", default=[])
    parser.add_argument("--source-manifest", help="Reuse the exact public company sources of an earlier trial")
    parser.add_argument("--cache-from", help="Resume route hints from a prior round JSON (same cohort; all page reads remain fresh)")
    parser.add_argument("--sample-companies", nargs="+", help="Company names to select from the manifest")
    parser.add_argument("--source-db")
    parser.add_argument("--source-user", default="campus-discovery-trial")
    parser.add_argument("--discovered-companies", nargs="+")
    parser.add_argument("--year", type=int, default=2027)
    parser.add_argument("--rounds", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--live", action="store_true", required=True)
    asyncio.run(main(parser.parse_args()))
