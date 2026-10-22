"""Measure saved-goal searches against live services, with isolated job libraries.

Four cold queries and one warm repeat use the configured production budgets.
Only public job data is sent; source relevance labels are supplied after the run.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

import httpx

REPO = Path(__file__).resolve().parents[1]
CASES = [
    ("shanghai-agent", "2027届上海AI Agent、RAG、大模型应用校招，排除北京和社招"),
    ("shenzhen-backend", "2027届深圳后端校招 Python优先，排除北京和社招"),
    ("hangzhou-java", "2027届杭州Java后端校招，排除北京和社招"),
    ("preferred-shanghai-intern", "上海优先，Agent应用开发实习，不限届别，排除社招"),
]
SETTING_KEYS = (
    "web_search_provider", "web_search_decision_mode", "web_search_max_rounds",
    "web_search_budget_seconds", "web_search_target_jobs",
    "web_search_verification_budget_seconds", "web_search_verification_item_seconds",
    "web_search_request_timeout_seconds", "web_search_transient_retries",
    "web_search_role_review_enabled", "web_search_role_review_concurrency",
    "web_search_role_review_batch_size", "web_search_role_review_max_calls",
    "web_search_role_review_timeout_seconds", "web_search_direct_sources_enabled",
    "structured_model_provider", "llm_model",
)


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def hashes():
    paths = list((REPO / "src").rglob("*.py")) + list((REPO / "frontend/app").glob("*"))
    return {p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths) if p.is_file()}


def serve(args):
    os.environ["DATABASE_URL"] = f"sqlite:///{args.database.resolve().as_posix()}"
    os.environ["LOG_LEVEL"] = "WARNING"
    os.environ["FRONTEND_ORIGINS"] = f"http://localhost:{args.frontend_port}"
    os.environ["PRIVATE_STORAGE_DIR"] = str(args.database.parent / "private")
    import uvicorn

    from src.config import get_settings
    from src.infrastructure.database import Base, engine
    from src.main import app

    settings = get_settings()
    save(args.database.parent / "runtime-settings.json",
         {key: getattr(settings, key) for key in SETTING_KEYS})
    Base.metadata.create_all(engine)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


def ensure_free(port):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def launch(command, directory, log, env=None):
    return subprocess.Popen(command, cwd=directory, env=env, stdin=subprocess.DEVNULL,
                            stdout=log, stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def stop(process):
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        process.terminate()
    process.wait(timeout=15)


async def wait_ready(url, process):
    async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
        deadline = monotonic() + 90
        while monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Benchmark server exited; inspect its saved log")
            try:
                if (await client.get(url)).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(.5)
    raise TimeoutError("Benchmark server did not become ready")


def database_receipt(database):
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        names = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {name: connection.execute('SELECT COUNT(*) FROM "' + name + '"').fetchone()[0]
                for name in names}


async def measure(api_url, directory, query, cache):
    directory.mkdir()
    started = monotonic()
    elapsed = lambda: round(monotonic() - started, 3)
    async with httpx.AsyncClient(base_url=api_url, headers={"X-User-ID": "local-user"},
                                timeout=30, trust_env=False) as client:
        async def get(endpoint):
            response = await client.get(endpoint)
            response.raise_for_status()
            return response.json()

        response = await client.post("/api/discovery/goals", json={"input_text": query})
        response.raise_for_status()
        goal = response.json()
        save(directory / "goal.json", goal)
        saved_seconds = elapsed()
        library_url = f"/api/discovery/goals/{goal['id']}/library"
        before = await get(library_url)
        cache_seconds = elapsed()
        save(directory / "library-before.json", before)
        before_ids = {m["job_posting_id"] for m in before["result_matches"]}
        initial_usable = any(m["filter_status"] == "matched" for m in before["result_matches"])
        response = await client.post(f"/api/discovery/goals/{goal['id']}/search",
                                     json={"expected_version": goal["version"]})
        response.raise_for_status()
        run = response.json()
        save(directory / "created-run.json", run)
        first_run_seen, first_library_seen, matched_first_seen = {}, {}, {}
        first_new_usable, first_lead, first_run_matched = None, None, None
        first_available = cache_seconds if initial_usable else None
        previous = None
        with (directory / "timeline.jsonl").open("w", encoding="utf-8") as timeline:
            while True:
                run, library, all_leads = await asyncio.gather(
                    get(f"/api/discovery/runs/{run['id']}"), get(library_url), get("/api/discovery/leads"))
                leads = [lead for lead in all_leads if lead["discovery_run_id"] == run["id"]]
                seconds = elapsed()
                if leads and first_lead is None:
                    first_lead = seconds
                for match in run["result_matches"]:
                    first_run_seen.setdefault(match["job_posting_id"], seconds)
                    if match["filter_status"] == "matched" and first_run_matched is None:
                        first_run_matched = seconds
                for match in library["result_matches"]:
                    identifier = match["job_posting_id"]
                    first_library_seen.setdefault(identifier, seconds)
                    if match["filter_status"] == "matched":
                        matched_first_seen.setdefault(identifier, seconds)
                        if first_available is None:
                            first_available = seconds
                        if identifier not in before_ids and first_new_usable is None:
                            first_new_usable = seconds
                snapshot = {"elapsed_seconds": seconds, "status": run["status"],
                            "lead_count": len(leads), "library_counts": library["counts"],
                            "matches": [{k: m[k] for k in ("job_posting_id", "filter_status")}
                                        for m in library["result_matches"]]}
                timeline.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
                timeline.flush()
                signature = json.dumps({k: v for k, v in snapshot.items() if k != "elapsed_seconds"})
                if signature != previous:
                    print(json.dumps({"case": directory.parent.name, "mode": cache,
                                      **snapshot}, ensure_ascii=False), flush=True)
                    previous = signature
                save(directory / "latest-run.json", run)
                if run["status"] != "RUNNING":
                    break
                if seconds > 1000:
                    raise TimeoutError("Observation exceeded 1000s; partial results are preserved")
                await asyncio.sleep(1.5)
        timing = {"cache": cache, "goal_saved_seconds": saved_seconds,
                  "cached_library_seconds": cache_seconds if before_ids else None,
                  "cached_usable_seconds": cache_seconds if initial_usable else None,
                  "first_lead_seconds": first_lead,
                  "first_run_system_matched_seconds": first_run_matched,
                  "first_library_system_usable_seconds": first_available,
                  "first_new_library_system_usable_seconds": first_new_usable,
                  "first_run_seen_job_seconds": first_run_seen,
                  "first_library_seen_job_seconds": first_library_seen,
                  "first_library_matched_job_seconds": matched_first_seen,
                  "total_observed_seconds": seconds,
                  "server_started_at": run["started_at"], "server_finished_at": run["finished_at"],
                  "run_id": run["id"], "goal_id": goal["id"]}
        save(directory / "timing.json", timing)
        save(directory / "final-run.json", run)
        save(directory / "library.json", library)
        save(directory / "leads.json", leads)
        save(directory / "candidates.json", await get("/api/candidates"))
        save(directory / "search-evidence.json", await get(f"/api/discovery/runs/{run['id']}/search-evidence"))
        save(directory / "jobs.json", [await get(f"/api/jobs/{m['job_posting_id']}")
                                       for m in library["result_matches"]])
        return {"query": query, "directory": directory.relative_to(REPO).as_posix(),
                "timing": timing, "counts": library["counts"], "status": run["status"]}


async def capture(page, directory, frontend_url, goal_id):
    await page.goto(frontend_url)
    await page.get_by_label("当前求职目标").wait_for(timeout=30000)
    await page.locator(".goal-selector select").select_option(goal_id)
    await page.get_by_label("岗位库统计").wait_for(timeout=30000)
    await page.get_by_role("button", name="全部展开", exact=True).click()
    rows = await page.locator(".jobs-table tbody tr").evaluate_all("""rows => rows.filter(r => r.querySelector('.jobs-title')).map(r => ({
        title: r.querySelector('.jobs-title').textContent,
        url: r.querySelector('[data-label="原始链接"] a')?.href || null,
        filter_status: r.closest('tbody').dataset.filterStatus,
        verification: r.querySelector('[data-label="核验状态"]')?.textContent,
        locations: r.querySelector('[data-label="地点"]')?.textContent,
        job_type: r.querySelector('[data-label="招聘类型"]')?.textContent
    }))""")
    save(directory / "ui-rows.json", rows)
    save(directory / "top10.json", rows[:10])
    await page.screenshot(path=str(directory / "results-desktop.png"), full_page=True)


async def main(args):
    cases = json.loads(args.cases_file.read_text(encoding="utf-8")) if args.cases_file else CASES
    if not cases or any(not isinstance(c, list | tuple) or len(c) != 2 for c in cases):
        raise ValueError("Cases must be nonempty [name, query] pairs")
    if any(not re.fullmatch(r"[a-z0-9-]+", name) for name, _ in cases) or len({c[0] for c in cases}) != len(cases):
        raise ValueError("Case names must be unique path-safe names")
    root = args.output.resolve()
    root.relative_to(REPO)
    root.mkdir(parents=True, exist_ok=False)
    ensure_free(args.port)
    ensure_free(args.frontend_port)
    initial_hashes = hashes()
    save(root / "code-hashes-start.json", initial_hashes)
    save(root / "protocol.json", {
        "started_at": datetime.now(UTC).isoformat(), "sample_count_per_cold_query": 1,
        "cases": cases, "warm_repeat": cases[0][0], "search_settings_modified": False,
        "no_mocks": True, "candidate_data_sent": False, "poll_interval_seconds": 1.5,
        "first_usable": "First observed matched job in the goal library, confirmed relevant by subsequent source-text review; report cached and newly inserted jobs separately.",
        "total": "Goal save dispatch to first terminal run observation, including goal interpretation and polling delay.",
        "top10": "First ten actual default UI job rows after expanding company groups, including unresolved job links; fewer than ten uses actual count and reports shortfall.",
        "exclusion_error": "Relevant jobs among determinate source-reviewed system-excluded jobs. Unknown exclusions are separate; no excluded sample is N/A. This does not measure whole-web recall.",
        "reviewer": "Assistant source-text audit, not an independent human gold set",
    })
    summaries = []
    frontend = server = None
    node = args.node or shutil.which("node")
    if not node:
        raise RuntimeError("Specify --node for the installed Node.js runtime")
    from playwright.async_api import async_playwright

    try:
        with (root / "frontend.log").open("w", encoding="utf-8") as frontend_log:
            env = {**os.environ, "NEXT_PUBLIC_API_URL": f"http://127.0.0.1:{args.port}",
                   "NEXT_DIST_DIR": ".next-benchmark"}
            frontend = launch([node, "node_modules/next/dist/bin/next", "dev", "--hostname", "localhost",
                               "--port", str(args.frontend_port)], REPO / "frontend", frontend_log, env)
            await wait_ready(f"http://localhost:{args.frontend_port}", frontend)
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch()
                try:
                    for index, (name, query) in enumerate(cases):
                        case = root / name
                        case.mkdir()
                        database = case / "acceptance.db"
                        with (case / "server.log").open("w", encoding="utf-8") as server_log:
                            server = launch([sys.executable, "-X", "utf8", "-m", "scripts.benchmark_search_goals",
                                             "--serve", "--database", str(database), "--port", str(args.port),
                                             "--frontend-port", str(args.frontend_port)], REPO, server_log)
                            await wait_ready(f"http://127.0.0.1:{args.port}/health", server)
                            before_counts = database_receipt(database)
                            if any(before_counts.values()):
                                raise RuntimeError("Cold database is not empty")
                            print(f"START {name} cold", flush=True)
                            context = await browser.new_context(viewport={"width": 1920, "height": 1080})
                            try:
                                for mode in (["cold", "warm"] if index == 0 else ["cold"]):
                                    row = await measure(f"http://127.0.0.1:{args.port}", case / mode, query, mode)
                                    page = await context.new_page()
                                    await capture(page, case / mode, f"http://localhost:{args.frontend_port}", row["timing"]["goal_id"])
                                    await page.close()
                                    row["database_counts"] = database_receipt(database)
                                    summaries.append(row)
                                    save(root / "summary-pending-review.json", summaries)
                                    print(json.dumps({"finished": name, "mode": mode,
                                                      "total_seconds": row["timing"]["total_observed_seconds"],
                                                      "counts": row["counts"]}, ensure_ascii=False), flush=True)
                            finally:
                                await context.close()
                                stop(server)
                                server = None
                finally:
                    await browser.close()
    finally:
        stop(server)
        stop(frontend)
        final_hashes = hashes()
        save(root / "code-hashes-end.json", final_hashes)
        changed = [p for p in initial_hashes.keys() | final_hashes.keys()
                   if initial_hashes.get(p) != final_hashes.get(p)]
        save(root / "application-code-changed.json", changed)
        if changed:
            raise RuntimeError("Application code changed during measurement")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--port", type=int, default=18041)
    parser.add_argument("--frontend-port", type=int, default=3012)
    parser.add_argument("--node")
    parser.add_argument("--cases-file", type=Path, help="JSON [name, query] pairs; defaults to the original four queries")
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--database", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve:
        if not args.database:
            parser.error("--database is required for --serve")
        serve(args)
    else:
        if not args.output:
            parser.error("--output is required")
        asyncio.run(main(args))
