"""Exercise the real search orchestration with delayed semantic requests."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import sessionmaker

from src.config import Settings
from src.domain.discovery import DiscoveryRun
from src.services import job_role_review, multiround_search, web_search_service
from src.services.job_lead_service import JobLeadService
from tests.test_role_review_batching import jobs
from tests.test_role_review_concurrency import ControlledClient
from tests.test_search_execution import candidate


@pytest.mark.asyncio
async def test_search_publishes_local_jobs_then_updates_each_semantic_result(
    db_session, monkeypatch
):
    client = ControlledClient()
    inputs = {
        str(i + 1): replace(
            job,
            detail_url=candidate(i + 1).source_url,
            raw_content=job.raw_content + f"\n编号：{i + 1}",
        )
        for i, job in enumerate(jobs(5))
    }
    inputs["5"] = replace(
        inputs["5"],
        title="Agent开发工程师",
        raw_content="岗位职责：\n负责Agent系统的开发，实现工具调用接口和任务执行引擎，完善运行监控和功能测试。\n任职要求：\n熟悉Python。",
    )
    local_returned = asyncio.Event()

    class Provider:
        source_id = "test"

        async def discover(self):
            return [candidate(i) for i in range(1, 6)]

    async def verify(service, *, user_id, lead_id, **kwargs):
        lead = service.get_lead(user_id=user_id, lead_id=lead_id)
        number = lead.source_url.rsplit("/", 1)[-1]
        if number == "5":
            await client.two_started.wait()
            local_returned.set()
        return service.verify_stub(
            user_id=user_id, lead_id=lead_id, stub=inputs[number]
        )

    settings = Settings(
        _env_file=None, web_search_understanding_mode="hybrid",
        structured_model_provider="openai",
        llm_api_key="fixture",
        web_search_direct_sources_enabled=False,
        web_search_max_rounds=1,
        web_search_budget_seconds=2,
        web_search_verification_budget_seconds=2,
    )
    monkeypatch.setattr(multiround_search, "get_settings", lambda: settings)
    monkeypatch.setattr(
        multiround_search, "SessionLocal", sessionmaker(bind=db_session.bind)
    )
    monkeypatch.setattr(
        multiround_search, "enabled_company_source_hosts", lambda **_: {"example.com"}
    )
    monkeypatch.setattr(multiround_search, "enabled_company_sources", lambda *_, **__: [])
    monkeypatch.setattr(
        web_search_service, "create_web_search_provider", lambda *_, **__: Provider()
    )
    monkeypatch.setattr(
        job_role_review, "create_structured_model_client", lambda _: client
    )
    monkeypatch.setattr(JobLeadService, "verify_url", verify)
    run = DiscoveryRun(
        id="role-queue",
        user_id="u",
        source="test",
        source_url="https://example.com",
        started_at=datetime.now(UTC),
    )
    db_session.add(run)
    db_session.commit()
    task = asyncio.create_task(
        multiround_search.execute_multiround_search(
            run_id=run.id,
            user_id="u",
            query="上海Agent或RAG校招",
            company_ids=[],
            analysis_limit=0,
        )
    )

    async def all_published():
        await local_returned.wait()
        while True:
            db_session.refresh(run)
            if len(run.result_matches or []) == 5:
                return
            await asyncio.sleep(0)

    try:
        try:
            await asyncio.wait_for(all_published(), 1)
        except TimeoutError:
            db_session.refresh(run)
            raise AssertionError(run.agent_trace) from None
        assert not task.done() and client.peak == 2
        assert sorted(row["filter_status"] for row in run.result_matches) == [
            "matched",
            *(["pending"] * 4),
        ]
        client.release.set()
        await task
    finally:
        client.release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    db_session.refresh(run)
    assert len(run.result_matches) == 5 and run.new_count == 5
    assert sorted(row["filter_status"] for row in run.result_matches) == [
        *(["excluded"] * 4),
        "matched",
    ]
    assert client.active == 0
