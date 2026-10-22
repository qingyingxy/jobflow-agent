"""Collect public official pages for an externally seeded retrieval audit.

This collector does not judge jobs or change the personal database. Labels must
be reviewed against saved source text before evaluating the normal search run.
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.services.browser_job_reader import PlaywrightBrowserJobReader


async def collect(manifest, output):
    output.mkdir(parents=True, exist_ok=True)
    rows = json.loads(manifest.read_text(encoding="utf-8"))
    reader = PlaywrightBrowserJobReader(timeout_seconds=25)
    semaphore = asyncio.Semaphore(3)

    async def read(row):
        destination = output / (row["id"] + ".json")
        if destination.exists():
            return
        async with semaphore:
            result = {**row, "observed_at": datetime.now().astimezone().isoformat()}
            try:
                async with asyncio.timeout(45):
                    snapshot = await reader.read(row["url"])
                result["snapshot"] = asdict(snapshot)
                result["status"] = "read"
            except Exception as error:  # noqa: BLE001 - isolate and record each audit page failure
                result.update(status="failed", error=str(error), error_code=getattr(error, "code", None))
            destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(json.dumps({"id": row["id"], "status": result["status"],
                              "characters": len(result.get("snapshot", {}).get("visible_text", ""))}, ensure_ascii=False), flush=True)

    async with reader.reuse():
        await asyncio.gather(*(read(row) for row in rows))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    asyncio.run(collect(args.manifest, args.output))
