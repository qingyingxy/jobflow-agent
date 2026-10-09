"""Export persisted model traces from an isolated acceptance database, read-only."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def export(directory: Path) -> Path:
    directory = directory.resolve()
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    job_ids = [job["job_id"] for source in report["sources"] for job in source["jobs"]]
    with sqlite3.connect(
        (directory / "acceptance.db").as_uri() + "?mode=ro", uri=True
    ) as db:
        db.row_factory = sqlite3.Row
        runs = []
        for job_id in job_ids:
            for row in db.execute(
                "SELECT * FROM agent_runs WHERE target_id = ? ORDER BY started_at",
                (job_id,),
            ):
                item = dict(row)
                for key in ("output", "validation_result"):
                    if isinstance(item[key], str):
                        item[key] = json.loads(item[key])
                runs.append(item)
    target = directory / "agent-runs.json"
    target.write_text(
        json.dumps(
            {"scope": "synthetic candidate; real model executions", "runs": runs},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest = {
        "backend_status": report["status"],
        "frontend_verification": report["frontend_verification"],
        "source_count": len(report["sources"]),
        "analyzed_job_count": len(job_ids),
        "agent_run_count": len(runs),
        "files": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.iterdir())
            if path.suffix in {".json", ".png"}
            and path.name != "evidence-manifest.json"
        },
    }
    (directory / "evidence-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    print(export(parser.parse_args().directory))
