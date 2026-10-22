from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.domain.application import CandidateJob, CandidateStatus
from src.services.application_service import ApplicationService
from src.services.job_url import canonical_job_url
from src.services.personal_requirements import personal_requirement_hints
from src.services.search_goal_service import SearchGoalService
from tests.test_search_goals import BASE, add_posting


def test_tracking_aliases_share_library_identity_and_selection_without_deleting_history(db_session):
    a = add_posting(db_session, identifier="a")
    b = add_posting(db_session, identifier="b")
    a.source_url = "https://jobs.example.com/campus/position/123/detail"
    b.source_url = a.source_url + "?spread=campaign&utm_source=share"
    db_session.get(CandidateJob, "candidate-a").status = "SAVED"
    db_session.get(CandidateJob, "candidate-b").status = "DISCOVERED"
    db_session.commit()
    service = ApplicationService(db_session)
    assert [v.posting.id for v in service.list_candidates(user_id="owner")] == [a.id]
    assert [j.id for j in SearchGoalService(db_session).postings("owner")] == [a.id]
    service.transition_candidate(user_id="owner", candidate_id="candidate-a", target_status=CandidateStatus.IGNORED)
    assert db_session.get(CandidateJob, "candidate-b").status == "IGNORED"
    assert not service.list_candidates(user_id="owner", status=CandidateStatus.SAVED)
    assert len(service.list_candidates(user_id="owner", status=CandidateStatus.IGNORED)) == 1
    assert service.list_candidates(user_id="owner")[0].posting.id == a.id
    assert db_session.get(CandidateJob, "candidate-a") and db_session.get(CandidateJob, "candidate-b")


def test_distinct_job_and_channel_selectors_stay_distinct():
    assert canonical_job_url("https://example.com/detail?jobId=1&spread=foo") == "https://example.com/detail?jobId=1"
    assert canonical_job_url("https://example.com/detail?jobId=1&channel=campus") != canonical_job_url("https://example.com/detail?jobId=2&channel=campus")
    assert canonical_job_url("https://example.com/#/detail?jobId=1") != canonical_job_url("https://example.com/#/detail?jobId=2")


def test_new_tracking_link_reuses_legacy_row_but_equal_body_different_position_does_not(db_session):
    from src.domain.discovery import LeadProvider
    from src.services.job_lead_service import JobLeadService

    service = JobLeadService(db_session)

    def ingest(identifier, url):
        lead = service.create_lead(user_id="owner", provider=LeadProvider.EXTERNAL_AGENT, source_url=url)
        stub = replace(BASE, source_job_id=identifier, detail_url=url)
        return service.verify_stub(user_id="owner", lead_id=lead.id, stub=stub).posting

    first = ingest("first", "https://example.com/position/1?spread=share")
    # Simulate a URL saved before tracking-parameter normalization was introduced.
    first.source_url = "https://example.com/position/1?spread=share"
    db_session.commit()
    assert ingest("alias", "https://example.com/position/1").id == first.id
    assert ingest("other", "https://example.com/position/2").id != first.id


@pytest.mark.parametrize("requirement,attention,preferred", [
    ("计算机相关专业，博士研究生学历。", True, False),
    ("硕士或博士学历。", False, False),
    ("本科及以上学历，博士优先。", False, True),
    ("博士学历，优秀硕士可放宽。", False, False),
    ("不要求博士学历。", False, False),
    ("熟悉博士论文的阅读和整理。", False, False),
    ("985或QS前100院校，第一作者发表顶会论文。", False, False),
])
def test_requirement_notices_keep_alternatives_and_preferences(requirement, attention, preferred):
    job = SimpleNamespace(raw_content="岗位职责：开发Agent。\n任职要求：\n" + requirement,
        recruitment_context={}, source_url=BASE.detail_url)
    profile = SimpleNamespace(degree="硕士", educations=[])
    hints = personal_requirement_hints(job, profile)
    assert hints and all(h["evidence"] == requirement for h in hints)
    assert any(h["status"] == "attention" for h in hints) == attention
    assert any(h["status"] == "preferred" for h in hints) == preferred


def test_doctor_in_team_description_is_not_a_candidate_requirement():
    job = replace(BASE, raw_content="公司介绍：我们的博士团队研发Agent。\n岗位职责：负责后端研发。\n任职要求：熟悉Python。")
    assert not personal_requirement_hints(job, None)
