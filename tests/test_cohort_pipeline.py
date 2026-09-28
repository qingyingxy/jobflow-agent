from __future__ import annotations

import httpx
import pytest

from src.api import jobs as jobs_api
from src.domain.eligibility import (
    CandidateProfileInput,
    EligibilityInput,
    SearchPreferences,
)
from src.domain.job import FieldEvidence, JobRequirement, StructuredJobDescription
from src.domain.matching import EvidenceRecord
from src.infrastructure.llm_client import FakeModelClient
from src.main import app
from src.services.eligibility_checker import check_eligibility
from src.services.local_evidence_matcher import match_requirement_locally


@pytest.mark.parametrize(
    "requirement,expected",
    [
        ("Bachelor's degree or higher", "pass"),
        ("At least a bachelor's degree", "pass"),
        (
            "Bachelor's degree or an equivalent combination of education, training, and/or experience",
            "unknown",
        ),
    ],
)
def test_english_degree_qualifiers_do_not_incorrectly_reject_masters(
    requirement, expected
):
    result = check_eligibility(
        EligibilityInput(
            profile=CandidateProfileInput(degree="硕士"),
            preferences=SearchPreferences(),
            job=StructuredJobDescription(education_requirements=[requirement]),
        ),
        include_search_preferences=False,
    )
    assert (
        next(check for check in result.checks if check.rule_name == "education").result
        == expected
    )


def test_one_skill_does_not_support_an_entire_all_of_clause():
    requirement = JobRequirement(
        category="required_skill",
        name="Python and React",
        description="Proficient in Python and React",
        mandatory=True,
        relation="all_of",
        items=["Proficient in Python and React"],
    )
    evidence = EvidenceRecord(
        id="evidence-python",
        user_id="test",
        title="Python project",
        claim="Built a Python service",
        skills=["Python"],
    )
    match = match_requirement_locally(
        user_id="test", requirement=requirement, evidence=[evidence]
    )
    assert match.support_level != "supported"


@pytest.mark.parametrize(
    "source,years,year,expected",
    [
        ("2027届中国大陆毕业生，2026届海外毕业生", [2026, 2027], 2026, "unknown"),
        ("2027届中国大陆毕业生，2026届海外毕业生", [2026, 2027], 2025, "unknown"),
        ("2026年9月至2027年8月毕业", [2026, 2027], 2027, "unknown"),
        ("2027届或符合其他应届条件", [2027], 2027, "unknown"),
        ("2027届", [2027], 2027, "pass"),
        ("面向2026、2027届毕业生", [2026, 2027], 2026, "pass"),
        ("2027届", [2027], 2026, "fail"),
    ],
)
def test_legacy_cohort_evidence_is_not_reduced_to_year_membership(
    source, years, year, expected
):
    job = StructuredJobDescription(
        graduation_years=years,
        education_requirements=[],
        major_requirements=[],
        field_evidence=[
            FieldEvidence(field_path="graduation_years", source_text=source)
        ],
    )
    result = check_eligibility(
        EligibilityInput(
            profile=CandidateProfileInput(graduation_year=year),
            preferences=SearchPreferences(),
            job=job,
        ),
        include_search_preferences=False,
    )
    assert result.checks[0].result == expected
    assert result.eligible == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("degree,overall", [("硕士", "unknown"), ("高中", "fail")])
async def test_product_parse_store_match_api_preserves_cohort_and_any_of(
    monkeypatch, db_session, degree, overall
):
    cohort = "2027届中国大陆毕业生，2026届海外毕业生"
    requirement = "熟悉 Python 或 Java 中至少一种语言"
    raw = f"测试公司招聘开发工程师。{cohort}。本科及以上学历。{requirement}。负责开发软件。"
    model = FakeModelClient(
        outputs=[
            {
                "facts": {
                    "graduation_years": {"values": [2026, 2027], "source_text": cohort},
                    "education_requirements": {
                        "values": ["本科及以上"],
                        "source_text": "本科及以上学历",
                    },
                },
                "requirements": [{"source_text": requirement, "level": "required"}],
                "responsibilities": ["负责开发软件"],
            },
            {
                "decisions": [
                    {
                        "requirement_index": 0,
                        "relation": "any_of",
                        "items": ["Python", "Java"],
                        "reason": "明确任选一种",
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr(
        jobs_api, "create_structured_model_client", lambda settings: model
    )
    headers = {"X-User-ID": "cohort-user"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers
    ) as client:
        profile = await client.put(
            "/api/profile",
            json={
                "graduation_year": 2026,
                "degree": degree,
                "major": "计算机",
                "search_preferences": {
                    "preferred_locations": ["上海"],
                    "job_types": ["internship"],
                },
            },
        )
        assert profile.status_code == 200
        evidence = await client.post(
            "/api/evidence",
            json={
                "type": "project",
                "title": "Python 项目",
                "claim": "使用 Python 开发服务",
                "skills": ["Python"],
                "source": "integration_fixture",
            },
        )
        assert evidence.status_code == 201
        imported = await client.post("/api/jobs/import-text", json={"raw_content": raw})
        assert imported.status_code == 201
        job_id = imported.json()["id"]
        response = await client.post(f"/api/jobs/{job_id}/analyze")
        assert response.status_code == 200, response.text
        db_session.expire_all()
        reread = await client.get(f"/api/jobs/{job_id}/analysis")
        assert reread.status_code == 200, reread.text
        body = reread.json()
        assert body["structured_jd"]["graduation_condition_kind"] == "qualified"
        assert body["structured_jd"]["graduation_source_text"] == cohort
        assert body["eligibility"]["eligible"] == overall
        checks = {item["rule_name"]: item for item in body["eligibility"]["checks"]}
        assert checks["graduation_year"]["result"] == "unknown"
        assert checks["graduation_year"]["jd_evidence"][0]["source_text"] == cohort
        assert set(checks) == {"graduation_year", "education", "major"}
        match = body["matches"][0]
        assert match["requirement"]["relation"] == "any_of"
        assert match["requirement"]["items"] == ["Python", "Java"]
        assert match["support_level"] == "supported"
        assert match["evidence_ids"] == [evidence.json()["id"]]
        assert len(model.requests) == 2
