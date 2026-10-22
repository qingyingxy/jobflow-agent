from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.evaluate_job_review_acceptance import observed_results
from src.domain.discovery import DiscoveryRun, LeadProvider
from src.domain.job import JobAvailabilityStatus
from src.services.discovery_matching import search_filter_conditions
from src.services.discovery_sources import JobStub
from src.services.job_lead_service import JobLeadService
from src.services.search_goal_service import SearchGoalService


@pytest.mark.parametrize("status,owner,expected", [
    ("VERIFIED", "u", True), ("DUPLICATE", "u", True),
    ("NEEDS_USER", "u", False), ("VERIFIED", "other", False),
])
def test_verified_redirect_identity_is_reused_and_audited_without_dropping_selectors(db_session, status, owner, expected):
    query = "上海后端校招"
    run = DiscoveryRun(id="aliases", user_id="u", source="test", source_url="https://example.com",
        search_query=query, goal_conditions=search_filter_conditions(query), started_at=datetime.now(UTC))
    db_session.add(run)
    db_session.commit()
    service = JobLeadService(db_session)
    alias = "https://example.com/detail?jobId=123&channel=campus"
    final = "https://example.com/detail?jobId=123"
    lead = service.create_lead(user_id="u", provider=LeadProvider.EXTERNAL_AGENT,
        discovery_run_id=run.id, source_url=alias)
    stub = JobStub(source_id="test", source_job_id="123", company="测试公司", title="后端工程师",
        locations=["上海"], job_type="campus", published_at=None, detail_url=final,
        raw_content="岗位职责：开发后端服务和工具接口。任职要求：熟悉Python和数据库。")
    posting = service.verify_stub(user_id="u", lead_id=lead.id, stub=stub,
        availability_status=JobAvailabilityStatus.UNKNOWN).posting
    lead.status, lead.user_id = status, owner
    db_session.commit()
    goals = SearchGoalService(db_session)
    assert bool(goals.cached_posting("u", alias)) == expected
    assert goals.cached_posting("u", final).id == posting.id
    assert goals.cached_posting("u", "https://example.com/detail?jobId=999&channel=campus") is None
    data = {"query": query, "samples": [{"id": "one", "title": stub.title, "source_url": alias,
        "expected_review_status": "recommended", "source_sha256": "test"}]}
    report = {"run_id": run.id, "matches": [{"job_posting_id": posting.id}],
        "leads": [{"url": alias}], "metrics": {}}
    with patch("scripts.evaluate_job_review_acceptance.create_engine", return_value=db_session.bind), patch.object(db_session.bind, "dispose"):
        result = observed_results(data, report, Path(__file__))
    assert result["retrieval_counts"] == ({"verified_detail": 1} if expected else {"lead_only": 1})
