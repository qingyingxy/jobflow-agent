"""Diagnose public campaign reads without model calls or user database access."""
import argparse
import asyncio
import json
from pathlib import Path

from src.config import get_settings
from src.services.campaign_reader import create_campaign_reader
from src.services.company_registry import enabled_company_sources


async def main(args):
    sources = enabled_company_sources(args.companies)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for source in sources:
        worker = create_campaign_reader(get_settings(), sources).pages
        try:
            page = await asyncio.wait_for(worker.read(source.career_url), timeout=45)
            result = {"company": source.company, "url": source.career_url, "readable": bool(page), **worker.snapshot()}
        except Exception as error:  # noqa: BLE001 - retain diagnostics from failed public reads
            result = {"company": source.company, "error": type(error).__name__, **worker.snapshot()}
        rows.append(result)
        output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"company": source.company, "attempts": result["read_attempts"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companies", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--live", required=True, action="store_true")
    asyncio.run(main(parser.parse_args()))
