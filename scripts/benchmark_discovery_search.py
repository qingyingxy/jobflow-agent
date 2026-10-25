"""Run bounded live searches against isolated databases, without app services.

Optionally compare a committed src/ snapshot with the working tree. Both use
the same explicit company scope, query and budgets; external results may vary.
"""

import argparse
import asyncio
import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from time import monotonic


async def run(args):
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    os.environ["DATABASE_URL"] = "sqlite:///" + (root / "search.db").as_posix()
    os.environ["PRIVATE_STORAGE_DIR"] = str(root / "private")
    os.environ["WEB_SEARCH_BUDGET_SECONDS"] = str(args.seconds)
    os.environ["COMPANY_DISCOVERY_ENABLED"] = "false"
    os.environ["LOG_LEVEL"] = "WARNING"
    if args.source_root:
        sys.path.insert(0, str(args.source_root))

    from datetime import UTC, datetime

    from src import main  # noqa: F401 - register all ORM models, no lifespan
    from src.config import get_settings
    from src.domain.discovery import DiscoveryRun
    from src.infrastructure.database import Base, SessionLocal, engine
    from src.services.multiround_search import execute_multiround_search
    from src.services.search_goal_service import SearchGoalService
    from src.services.search_intent import parse_conditions

    Base.metadata.create_all(engine)
    companies = args.companies.split(",")
    with SessionLocal() as session:
        goal = SearchGoalService(session).save(user_id="benchmark", input_text=args.query,
            conditions=parse_conditions(args.query), condition_sources={}, company_ids=companies)
        goal_id, version, query, conditions = goal.id, goal.version, goal.query, goal.conditions
    settings = get_settings()
    protocol = {"query": query, "companies": companies, "seconds": args.seconds,
                "source_root": str(args.source_root) if args.source_root else "working-tree",
                "mode": "isolated cold + warm" if args.warm else "isolated cold",
                "background_schedulers": False, "analysis_limit": 0,
                "model": settings.llm_model, "reasoning": settings.llm_reasoning_effort,
                "semantic_timeout": settings.web_search_semantic_timeout_seconds,
                "direct_sources": settings.web_search_direct_sources_enabled,
                "caveat": "Live website/search/model variance; a small scoped check is not a universal speed guarantee."}
    (root / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8")
    summaries = []
    for mode in (["cold", "warm"] if args.warm else ["cold"]):
        with SessionLocal() as session:
            run_id = f"benchmark-{mode}"
            discovery = DiscoveryRun(id=run_id, user_id="benchmark", source="benchmark",
                source_url="https://example.com/benchmark", search_goal_id=goal_id,
                search_goal_version=version, search_query=query, goal_conditions=conditions,
                library_baseline=SearchGoalService(session).snapshot("benchmark", query=query),
                started_at=datetime.now(UTC))
            session.add(discovery)
            session.commit()
        print(f"START {root.name} {mode}", flush=True)
        started = monotonic()
        execution_error = None
        try:
            await execute_multiround_search(run_id=run_id, user_id="benchmark", query=query,
                                            company_ids=companies, analysis_limit=0)
        except Exception as error:  # noqa: BLE001 - retain failures as benchmark outcomes
            # A baseline failure is a result, not a reason to discard the pair.
            execution_error = {"type": type(error).__name__, "message": str(error)}
        with SessionLocal() as session:
            discovery = session.get(DiscoveryRun, run_id)
            report = {"mode": mode, "seconds": round(monotonic() - started, 3),
                      "metrics": discovery.usage_metrics, "matches": discovery.result_matches,
                      "trace": discovery.agent_trace, "failure": discovery.failure_summary,
                      "execution_error": execution_error}
        (root / f"{mode}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = {k: report[k] for k in ("mode", "seconds", "metrics", "failure", "execution_error")}
        summaries.append(summary)
        print(json.dumps(summary, ensure_ascii=True), flush=True)
    (root / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    engine.dispose()


def paired(args):
    args.output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, "-X", "utf8", "-m", "scripts.benchmark_discovery_search",
               "--seconds", str(args.seconds), "--companies", args.companies, "--query", args.query]
    if args.warm:
        command.append("--warm")
    archive = subprocess.run(["git", "-c", "safe.directory=" + Path.cwd().as_posix(),
        "archive", "--format=zip", args.baseline_ref, "src"], check=True, capture_output=True).stdout
    with tempfile.TemporaryDirectory(prefix="jobflow-baseline-") as temporary:
        with zipfile.ZipFile(io.BytesIO(archive)) as files:
            files.extractall(temporary)
        subprocess.run([*command, "--source-root", temporary, "--output", str(args.output / "before")], check=True)
        subprocess.run([*command, "--output", str(args.output / "after")], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=90)
    parser.add_argument("--companies", default="bytedance,baidu,alibaba,jd")
    parser.add_argument("--query", default="岗位方向：ai agent、rag、ai产品；招聘类型：校招；届别：2027届")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--baseline-ref")
    parser.add_argument("--warm", action="store_true")
    args = parser.parse_args()
    if args.baseline_ref:
        paired(args)
    else:
        asyncio.run(run(args))
