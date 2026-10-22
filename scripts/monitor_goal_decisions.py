"""Read-only observation of whether multiple goals retain their own judgments."""
import argparse
import hashlib
import json
import sqlite3
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--seconds", type=int, default=1200)
    args = parser.parse_args()
    folder = args.directory.resolve()
    if not folder.is_relative_to(ROOT / "artifacts"):
        parser.error("Only isolated artifact databases are supported")
    from src.services.source_understanding import fingerprint

    last = {}
    fingerprints = {}
    started = time.monotonic()
    while time.monotonic() - started < args.seconds:
        with sqlite3.connect((folder / "trial.db").as_uri() + "?mode=ro", uri=True) as db:
            goals = list(db.execute("select id,conditions from search_goals"))
            counts = Counter()
            changes = []
            rows = db.execute("select id,title,source_url,raw_content,locations,job_type,recruitment_context from job_postings")
            for identifier, title, url, raw, locations, kind, encoded in rows:
                context = json.loads(encoded or "{}")
                record = context.get("source_understanding", {})
                value = record.get("fingerprint")
                if not value:
                    continue
                key = (identifier, value)
                if key not in fingerprints:
                    stub = SimpleNamespace(title=title, detail_url=url or "", raw_content=raw,
                        locations=json.loads(locations or "[]"), job_type=kind, recruitment_context=context)
                    fingerprints[key] = next((goal_id for goal_id, conditions in goals
                        if fingerprint(stub, json.loads(conditions)) == value), "stale_or_other")
                owner = fingerprints[key]
                counts[owner] += 1
                if identifier in last and last[identifier] != (owner, value):
                    changes.append({"id": identifier, "title": title, "previous_goal": last[identifier][0],
                        "current_goal": owner, "body_hash": hashlib.sha256((raw or "").encode()).hexdigest()})
                last[identifier] = (owner, value)
            tasks = [dict(zip(("goal_id", "status", "processed", "completed"), row)) for row in
                db.execute("select goal_id,status,processed,completed from body_review_tasks")]
        event = {"at": datetime.now(UTC).isoformat(), "elapsed_seconds": round(time.monotonic()-started, 2),
            "stored_decisions_by_goal": dict(counts), "changes": changes, "tasks": tasks}
        with (folder / "decision-history.jsonl").open("a", encoding="utf-8") as out:
            out.write(json.dumps(event, ensure_ascii=False) + "\n")
        time.sleep(min(15, max(0, args.seconds - (time.monotonic()-started))))


if __name__ == "__main__":
    main()
