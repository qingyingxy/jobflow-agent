"""Read public announcement sources without writing the user's database."""
import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from src.config import get_settings
from src.services.campaign_reader import create_campaign_reader
from src.services.campaign_service import effective_status
from src.services.company_registry import enabled_company_sources


async def main(args):
    sources = enabled_company_sources(args.companies)
    results = [None] * len(sources)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    slots = asyncio.Semaphore(args.concurrency)
    caches = {}
    if args.cache_from:
        previous = json.loads(Path(args.cache_from).read_text(encoding="utf-8"))
        if previous["year"] != args.year:
            raise ValueError("Cache cohort must match the requested cohort")
        caches = {r["source_id"]: r.get("cache", {}) for r in previous["results"]}
    async def check(index, source):
        started = monotonic()
        reader = create_campaign_reader(get_settings(), sources)
        try:
            result = await asyncio.wait_for(reader.check(source, args.year, caches.get(source.id, {})),
                                            timeout=reader.time_budget + 10)
            entry = {"company": source.company, "source_id": source.id,
                     "duration_seconds": round(monotonic() - started, 2), **result,
                     "diagnostics": reader.diagnostics, "pages": reader.pages.snapshot()}
        except TimeoutError:
            entry = {"company": source.company, "source_id": source.id, "duration_seconds": round(monotonic() - started, 2),
                     "error": "check_timeout", "found": [], "diagnostics": reader.diagnostics, "pages": reader.pages.snapshot()}
        if args.all_pages:
            # Evaluation keeps the complete bounded trace; production cache limits stay independent.
            pages = {p['url']: p for p in reader.pages.pages.values()}
            entry['pages']['read_cache'] = [{**p, 'links': [{'url': link.url, 'text': link.text} for link in p['links']]}
                                            for p in pages.values()]
            entry['pages']['read_attempts'] = reader.pages.attempts
        now = datetime.now(UTC)
        entry["currently_open"] = sum(effective_status(fact, now, now) == "open" for fact, _ in entry["found"])
        entry["verified_entries"] = sum(effective_status(fact, now, now) == "open" and (fact.get("entry") or {}).get("status") == "open" for fact, _ in entry["found"])
        results[index] = entry
        output.write_text(json.dumps({"year": args.year, "mode": "warm" if args.cache_from else "cold",
                                     "results": [r for r in results if r is not None]}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: entry.get(k) for k in ("company", "duration_seconds", "error", "readable")}
                         | {"announcements": len(entry["found"]), "currently_open": entry["currently_open"], "verified_entries": entry["verified_entries"]}, ensure_ascii=False), flush=True)
    async def limited(index, source):
        async with slots:
            await check(index, source)
    await asyncio.gather(*(limited(i, source) for i, source in enumerate(sources)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companies", nargs="+", required=True)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--output", default="artifacts/campaigns-20261022/live-check.json")
    parser.add_argument("--live", action="store_true", required=True, help="Authorize public web and configured model calls")
    parser.add_argument("--concurrency", type=int, choices=[1, 2], default=1)
    parser.add_argument("--cache-from", help="Reuse public parse cache from an earlier check; web pages are still reread")
    parser.add_argument("--all-pages", action="store_true", help="Save all bounded page evidence for manual coverage auditing")
    asyncio.run(main(parser.parse_args()))
