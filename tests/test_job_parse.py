from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from src.domain.job import JobPosting
from src.domain.runs import AgentRun, JobParseResult
from src.infrastructure.llm_client import FakeModelClient
from src.services.jd_parser import JDParser
from src.services.job_parse_service import JDParseFailure, JobParseService

RAW_CONTENT = "示例公司招聘 AI 应用开发实习生，熟悉 RAG，工作地点为北京。"


def create_posting(db_session) -> JobPosting:
    posting = JobPosting(
        id="job_m04_test",
        source_url="https://example.com/job/1",
        source_type="manual_text",
        company="示例公司",
        title="AI 应用开发实习生",
        raw_content=RAW_CONTENT,
        content_hash="f" * 64,
        retrieved_at=datetime.now(UTC),
        trace_id="trace_m04_test",
    )
    db_session.add(posting)
    db_session.commit()
    return posting


def valid_output() -> dict[str, object]:
    return {"field_evidence": []}


@pytest.mark.asyncio
async def test_parse_service_writes_job_result_and_successful_agent_run(db_session) -> None:
    posting = create_posting(db_session)
    parser = JDParser(FakeModelClient(output=valid_output()))

    execution = await JobParseService(db_session, parser).parse(
        user_id="user-m04",
        job_id=posting.id,
    )

    assert execution.parse_result.job_posting_id == posting.id
    assert execution.agent_run.status == "succeeded"
    assert execution.agent_run.validation_status == "passed"
    assert execution.agent_run.output["field_evidence"] == []
    assert execution.agent_run.output["company"] is None
    assert db_session.scalar(select(JobParseResult)) is not None


@pytest.mark.asyncio
async def test_parse_service_records_failure_without_half_finished_result(db_session) -> None:
    posting = create_posting(db_session)
    parser = JDParser(
        FakeModelClient(output={"field_evidence": [], "extra": "invalid"})
    )

    with pytest.raises(JDParseFailure) as error:
        await JobParseService(db_session, parser).parse(
            user_id="user-m04",
            job_id=posting.id,
        )

    run = db_session.get(AgentRun, error.value.agent_run_id)
    assert run is not None
    assert run.status == "failed"
    assert run.validation_status == "failed"
    assert run.output is None
    assert db_session.scalar(select(JobParseResult)) is None
