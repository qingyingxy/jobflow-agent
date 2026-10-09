"""Read-only live discovery -> real parser -> local matching acceptance.

Uses an isolated SQLite database and synthetic candidate, never submits applications.
Run: uv run python -m scripts.run_discovery_acceptance --sources bytedance tencent anthropic
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path


async def run(args, directory: Path) -> dict:
    # Set before importing the application so its engine cannot target user data.
    os.environ["DATABASE_URL"] = f"sqlite:///{(directory / 'acceptance.db').as_posix()}"
    os.environ["LOG_LEVEL"] = "WARNING"
    import httpx
    from sqlalchemy import func, select

    from src.config import get_settings
    from src.domain.job import JobPosting
    from src.infrastructure.database import Base, SessionLocal, engine
    from src.main import app
    from src.services.company_registry import enabled_company_sources
    from src.services.discovery_service import DiscoveryService
    from src.services.discovery_sources import (
        GreenhouseAdapter,
        OfficialCompanyRegistryAdapter,
    )
    from src.services.official_search_service import analyze_discovery_jobs
    from src.services.url_reader import SafeHTTPReader

    settings = get_settings()
    if settings.structured_model_provider == "fake" or not settings.llm_api_key:
        raise RuntimeError("Live acceptance requires a real configured model")
    Base.metadata.create_all(engine)
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "mode": "live",
        "candidate_profile": "synthetic test profile; not the user's resume",
        "database": str(directory / "acceptance.db"),
        "query": args.query,
        "model": settings.llm_model,
        "parser_version": settings.product_parser_version,
        "prompt_version": settings.product_prompt_version,
        "application_submission": False,
        "sources": [],
    }

    def save():
        (directory / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://acceptance",
        headers={"X-User-ID": "local-user"},
    ) as client:
        profile = await client.put(
            "/api/profile",
            json={"graduation_year": 2027, "degree": "硕士", "major": "计算机科学"},
        )
        profile.raise_for_status()
        evidence = await client.post(
            "/api/evidence",
            json={
                "type": "project",
                "title": "验收专用 Python 项目",
                "claim": "使用 Python 开发服务，使用 RAG 实现文档检索。",
                "skills": ["Python", "RAG"],
                "source": "synthetic_acceptance_fixture",
            },
        )
        evidence.raise_for_status()
        for source in args.sources:
            query = dict(item.split("=", 1) for item in args.source_query).get(
                source, args.query
            )
            entry = {
                "source": source,
                "query": query,
                "started_at": datetime.now(UTC).isoformat(),
                "status": "running",
                "jobs": [],
            }
            report["sources"].append(entry)
            save()
            print(f"START {source}", flush=True)
            try:
                reader = SafeHTTPReader(
                    timeout_seconds=20,
                    max_retries=0,
                    proxy=settings.url_fetch_proxy,
                    proxy_allowed_hosts={
                        "jobs.bytedance.com",
                        "careers.tencent.com",
                        "boards-api.greenhouse.io",
                        "boards.greenhouse.io",
                        "job-boards.greenhouse.io",
                    },
                )
                if source in {"bytedance", "tencent"}:
                    adapter = OfficialCompanyRegistryAdapter(
                        sources=enabled_company_sources([source]),
                        query=query,
                        reader=reader,
                        max_jobs=3,
                    )
                else:
                    adapter = GreenhouseAdapter.from_board_url(
                        f"https://boards.greenhouse.io/{source}",
                        reader=reader,
                        company=source,
                        max_jobs=3,
                        query=query,
                    )
                with SessionLocal() as session:
                    service = DiscoveryService(session, adapter)
                    discovery = service.create_run(
                        user_id="local-user", search_query=query, max_results=3
                    )
                    result = await service.run(user_id="local-user", run=discovery)
                    entry.update(
                        run_id=discovery.id,
                        discovered_count=discovery.discovered_count,
                        verified_count=len(result.job_posting_ids),
                        failure_summary=discovery.failure_summary,
                        trace=discovery.agent_trace,
                        search_plan=discovery.search_plan,
                    )
                    save()
                    if not result.job_posting_ids:
                        raise RuntimeError(
                            "No verified job postings; inspect failure_summary and trace"
                        )
                    print(f"ANALYZE {source}", flush=True)
                    await analyze_discovery_jobs(
                        session,
                        run_id=discovery.id,
                        user_id="local-user",
                        job_ids=result.job_posting_ids[: args.jobs_per_source],
                    )
                    session.refresh(discovery)
                    entry.update(
                        trace=discovery.agent_trace,
                        run_status=discovery.status,
                        analysis_status=discovery.analysis_status,
                        failure_summary=discovery.failure_summary,
                    )
                    for job_id in result.job_posting_ids[: args.jobs_per_source]:
                        job = session.get(JobPosting, job_id)
                        item = {
                            "job_id": job_id,
                            "url": job.source_url,
                            "title": job.title,
                            "company": job.company,
                            "content_hash": job.content_hash,
                            "retrieved_at": job.retrieved_at.isoformat(),
                            "raw_content": job.raw_content,
                            "verification_status": job.verification_status,
                            "availability_status": job.availability_status,
                        }
                        entry["jobs"].append(item)
                        response = await client.get(f"/api/jobs/{job_id}/analysis")
                        item["analysis_http_status"] = response.status_code
                        item["analysis"] = response.json()
                        save()
                        response.raise_for_status()
                        reread = await client.get(f"/api/jobs/{job_id}/analysis")
                        reread.raise_for_status()
                        assert (
                            reread.json()["structured_jd"]
                            == response.json()["structured_jd"]
                        )
                        candidates = await client.get("/api/candidates")
                        candidates.raise_for_status()
                        candidate = next(
                            c
                            for c in candidates.json()
                            if c["job_posting_id"] == job_id
                        )
                        saved = await client.patch(
                            f"/api/candidates/{candidate['id']}/status",
                            json={"status": "SAVED"},
                        )
                        saved.raise_for_status()
                        item["saved_candidate"] = saved.json()
                        assert saved.json()["status"] == "SAVED"
                        item["api_roundtrip"] = "passed"
                    before = session.scalar(
                        select(func.count()).select_from(JobPosting)
                    )
                    repeated = await service.run(
                        user_id="local-user",
                        run=service.create_run(
                            user_id="local-user", search_query=query, max_results=3
                        ),
                    )
                    # This second pass tests discovery idempotency only.
                    await analyze_discovery_jobs(
                        session,
                        run_id=repeated.run.id,
                        user_id="local-user",
                        job_ids=[],
                    )
                    after = session.scalar(select(func.count()).select_from(JobPosting))
                    entry["repeat"] = {
                        "before_count": before,
                        "after_count": after,
                        "new_count": repeated.run.new_count,
                        "duplicate_count": repeated.run.duplicate_count,
                        "same_job_ids": set(result.job_posting_ids)
                        == set(repeated.job_posting_ids),
                    }
                    entry["idempotency"] = (
                        "passed"
                        if before == after and entry["repeat"]["same_job_ids"]
                        else "changed_source_or_failure"
                    )
                    entry["status"] = (
                        "passed" if entry["idempotency"] == "passed" else "partial"
                    )
            except Exception as error:  # noqa: BLE001 - preserve per-source failure evidence
                entry["status"] = "failed"
                # No credentials or request headers are included.
                entry["error"] = {
                    "type": type(error).__name__,
                    "message": str(error)[:700],
                }
                if getattr(error, "__cause__", None):
                    entry["error"]["cause"] = str(error.__cause__)[:700]
            entry["finished_at"] = datetime.now(UTC).isoformat()
            save()
            print(f"END {source}: {entry['status']}", flush=True)
    report["finished_at"] = datetime.now(UTC).isoformat()
    report["status"] = (
        "passed"
        if all(s["status"] == "passed" for s in report["sources"])
        else "partial"
    )
    report["frontend_verification"] = "pending"
    report["source_sha256"] = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [
            Path(__file__),
            Path("src/services/product_jd_parser.py"),
            Path("src/services/product_jd_runtime_parser.py"),
            Path("src/services/eligibility_checker.py"),
            Path("src/domain/graduation.py"),
            Path("src/services/discovery_sources.py"),
            Path("src/services/jd_analysis_service.py"),
        ]
    }
    save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sources", nargs="+", default=["bytedance", "tencent", "anthropic"]
    )
    parser.add_argument("--query", default="Python")
    parser.add_argument(
        "--source-query",
        action="append",
        default=[],
        help="Override one source query: anthropic=Software Engineer",
    )
    parser.add_argument("--jobs-per-source", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if any(
        "=" not in item or not item.split("=", 1)[1].strip()
        for item in args.source_query
    ):
        parser.error("--source-query must be SOURCE=QUERY")
    directory = args.output or Path("artifacts/acceptance") / datetime.now(
        UTC
    ).strftime("%Y%m%dT%H%M%SZ")
    directory.mkdir(parents=True, exist_ok=False)
    report = asyncio.run(run(args, directory.resolve()))
    print(f"REPORT {directory / 'report.json'}: {report['status']}", flush=True)
    raise SystemExit(0 if report["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
