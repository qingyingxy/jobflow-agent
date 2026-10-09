"""Regressions from qualification review; these are not model accuracy tests."""

from __future__ import annotations

from copy import deepcopy

import httpx
import pytest

from src.domain.education import (
    EducationCondition,
    EducationFacts,
    EducationRecord,
    MajorPredicate,
    validate_education_grounding,
)
from src.domain.education_dates import education_date_support, supported_graduation_year
from src.domain.eligibility import (
    CandidateProfileInput,
    EligibilityInput,
    SearchPreferences,
)
from src.domain.job import (
    FieldEvidence,
    JobRequirement,
    RawJobDocument,
    StructuredJobDescription,
)
from src.domain.models import UserProfile
from src.infrastructure.llm_client import FakeModelClient
from src.main import app
from src.services.education_evaluator import evaluate_education, match_major
from src.services.eligibility_checker import check_eligibility
from src.services.jd_analysis_service import JDAnalysisService
from src.services.product_jd_education_parser import ProductJDParser
from src.services.resume_ingestion_service import ResumeEvidenceExtractor


def test_related_major_different_family_is_not_proof_of_ineligibility():
    rule = MajorPredicate(
        mode="related", values=["计算机"], source_text="计算机相关专业"
    )
    assert match_major("数学与应用数学", rule) == "unknown"
    assert match_major("机械工程", rule) == "unknown"


def test_admission_year_cannot_pass_as_graduation_year():
    record = EducationFacts(
        level="bachelor",
        major_raw="计算机科学",
        graduation_year=2020,
        graduation_source_text="2020-2024",
    )
    with pytest.raises(ValueError, match="毕业"):
        validate_education_grounding(record, "本科 计算机科学 2020-2024")


def test_bare_year_quote_does_not_prove_its_date_role():
    record = EducationFacts(
        level="bachelor", graduation_year=2020, graduation_source_text="2020"
    )
    with pytest.raises(ValueError, match="毕业"):
        validate_education_grounding(record, "本科 2020-2024")


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("2020-2024", {2020}, {2024}),
        ("2020.09—2024.06", {2020}, {2024}),
        ("2020年9月—2024年6月", {2020}, {2024}),
        ("2020年9月1日至2024年6月30日", {2020}, {2024}),
        ("2020/09/01 to 2024/06/30", {2020}, {2024}),
        ("2024-2024", {2024}, {2024}),
        ("2024至今", {2024}, set()),
        ("2024年9月-至今", {2024}, set()),
        ("2024–present", {2024}, set()),
        ("2020入学；2024毕业", {2020}, {2024}),
        ("入学年份：2020；预计毕业：2024", {2020}, {2024}),
        ("Enrolled in 2020; expected graduation in 2024", {2020}, {2024}),
        ("2024获奖；2027预计毕业", set(), {2027}),
        ("2020-2022 肄业", {2020}, set()),
        ("2020-2022 exchange", {2020}, set()),
        ("2020-2024 未毕业", {2020}, set()),
        ("未毕业于2024", set(), set()),
        ("not graduated in 2024", set(), set()),
        ("本科 2024", set(), set()),
    ],
)
def test_education_dates_preserve_roles(text, start, end):
    result = education_date_support(text)
    assert result.enrollment == start
    assert result.graduation == end


def test_education_dates_reject_inverted_or_ambiguous_years():
    with pytest.raises(ValueError, match="早于"):
        education_date_support("2024-2020")
    with pytest.raises(ValueError, match="早于"):
        EducationFacts(enrollment_year=2024, graduation_year=2020)
    record = EducationFacts(
        graduation_year=2024, graduation_source_text="预计2024毕业，延期至2025毕业"
    )
    with pytest.raises(ValueError, match="无法确定"):
        validate_education_grounding(record, "预计2024毕业，延期至2025毕业")
    record.graduation_source_text = "2024毕业"
    with pytest.raises(ValueError, match="无法确定"):
        validate_education_grounding(record, "预计2024毕业，延期至2025毕业")


@pytest.mark.parametrize(
    ("quote", "kind", "valid"),
    [
        ("2020-2024", "unknown", True),
        ("2020-2024", "actual", False),
        ("2020-2024", "expected", False),
        ("2024预计毕业", "expected", True),
        ("2024预计毕业", "actual", False),
        ("已毕业于2024", "actual", True),
    ],
)
def test_date_kind_cannot_be_inferred_from_past_year(quote, kind, valid):
    facts = EducationFacts(
        level="bachelor",
        graduation_year=2024,
        graduation_source_text=quote,
        graduation_year_kind=kind,
    )
    if valid:
        validate_education_grounding(facts, f"本科 {quote}")
    else:
        with pytest.raises(ValueError, match="毕业"):
            validate_education_grounding(facts, f"本科 {quote}")


SCOPE_SOURCE = "面向2027届应届毕业生，要求硕士学历，本科为计算机相关专业"


def scoped_condition():
    return EducationCondition(
        relation="all_of",
        branches=[
            {
                "source_text": "要求硕士学历",
                "degree": {"operator": "eq", "level": "master", "source_text": "硕士"},
                "major": {"mode": "not_specified"},
                "scope": "application",
                "scope_source_text": SCOPE_SOURCE,
            },
            {
                "source_text": "本科为计算机相关专业",
                "degree": {
                    "operator": "eq",
                    "level": "bachelor",
                    "source_text": "本科",
                },
                "major": {
                    "mode": "related",
                    "values": ["计算机"],
                    "source_text": "计算机相关专业",
                },
                "scope": "historical",
                "scope_source_text": SCOPE_SOURCE,
            },
        ],
    )


def candidate(master_year=2027):
    return CandidateProfileInput(
        education_history_complete=True,
        educations=[
            EducationRecord(
                id="edu_b",
                level="bachelor",
                major_raw="计算机科学",
                graduation_year=2024,
                source_text="本科 计算机科学 2020-2024",
            ),
            EducationRecord(
                id="edu_m",
                level="master",
                major_raw="金融",
                graduation_year=master_year,
                source_text=f"硕士 金融 预计{master_year}毕业",
            ),
        ],
    )


def eligibility(conditions, profile):
    requirements = [
        JobRequirement(
            category="education",
            name="教育资格",
            description="，".join(b.source_text for b in c.branches),
            relation=c.relation,
            items=[b.source_text for b in c.branches],
            education=c,
        )
        for c in conditions
    ]
    job = StructuredJobDescription(
        requirements=requirements,
        graduation_years=[2027],
        field_evidence=[
            FieldEvidence(
                field_path="graduation_years", source_text="面向2027届应届毕业生"
            )
        ],
    )
    return check_eligibility(
        EligibilityInput(profile=profile, job=job, preferences=SearchPreferences()),
        include_search_preferences=False,
    )


@pytest.mark.parametrize(
    ("master_year", "expected"), [(2027, "pass"), (2026, "fail"), (None, "unknown")]
)
def test_application_cohort_does_not_require_historical_bachelor_same_year(
    master_year, expected
):
    result = eligibility([scoped_condition()], candidate(master_year))
    assert result.eligible == expected
    if expected == "pass":
        assert {e.id for e in result.checks[0].education_evidence} == {"edu_b", "edu_m"}


def test_scope_works_across_separate_required_clauses():
    conditions = [
        EducationCondition(relation="all_of", branches=[b])
        for b in scoped_condition().branches
    ]
    assert eligibility(conditions, candidate()).eligible == "pass"
    assert eligibility(conditions, candidate(2026)).eligible == "fail"


@pytest.mark.parametrize("scope", ["historical", "unknown"])
def test_historical_or_unknown_scope_cannot_remove_global_cohort_gate(scope):
    branch = scoped_condition().branches[1].model_copy(update={"scope": scope})
    condition = EducationCondition(relation="all_of", branches=[branch])
    result = eligibility([condition], candidate())
    assert result.eligible == "unknown"
    assert (
        next(c for c in result.checks if c.rule_name == "graduation_year").result
        == "unknown"
    )


def test_mixed_any_of_cannot_pass_using_only_historical_branch():
    condition = scoped_condition().model_copy(update={"relation": "any_of"})
    assert eligibility([condition], candidate(2026)).eligible == "unknown"


def test_explicit_historical_branch_year_still_applies():
    condition = scoped_condition()
    condition.branches[1].graduation_years = [2023]
    condition.branches[1].source_text += "，2023届"
    condition.branches[1].graduation_source_text = "2023届"
    assert eligibility([condition], candidate()).eligible == "fail"


def test_any_of_application_paths_accept_finance_master():
    condition = scoped_condition()
    condition.relation = "any_of"
    condition.branches[1].scope = "application"
    profile = candidate()
    profile.educations[0].major_raw = "机械工程"
    result = eligibility([condition], profile)
    assert result.eligible == "pass"
    assert [e.id for e in result.checks[0].education_evidence] == ["edu_m"]


@pytest.mark.parametrize("version", ["v2", "v3"])
def test_old_auto_start_year_is_not_trusted_as_graduation_even_when_reviewed(version):
    record = EducationRecord(
        level="master",
        graduation_year=2024,
        graduation_source_text="2024-2027",
        source_text="硕士 2024-2027",
        source=f"resume_asset:{version}:asset",
        reviewed=True,
    )
    assert supported_graduation_year(record) is None
    condition = scoped_condition()
    condition.branches = condition.branches[:1]
    profile = CandidateProfileInput(
        educations=[record], education_history_complete=True
    )
    assert (
        evaluate_education(condition, profile, graduation_years=[2027]).result
        == "unknown"
    )
    record.graduation_year = 2028
    record.graduation_source_text = None
    record.graduation_year_confirmed = True
    assert supported_graduation_year(record) == 2028
    assert (
        evaluate_education(condition, profile, graduation_years=[2027]).result == "fail"
    )


def test_analysis_rechecks_stale_legacy_summary_without_rewriting_profile(db_session):
    record = EducationRecord(
        level="master",
        graduation_year=2024,
        graduation_source_text="2024-2027",
        source_text="硕士 2024-2027",
        source="resume_asset:v2:asset",
    )
    profile = UserProfile(
        user_id="a",
        degree="硕士",
        graduation_year=2024,
        educations=[record.model_dump()],
    )
    db_session.add(profile)
    db_session.commit()
    inputs, _ = JDAnalysisService(db_session)._profile_inputs("a")
    assert inputs.degree == "硕士"
    assert inputs.graduation_year is None
    assert profile.graduation_year == 2024


@pytest.mark.asyncio
async def test_resume_wrong_date_role_triggers_model_repair():
    source = "本科 机械工程 2020-2024"
    bad = {
        "evidence": [
            {
                "type": "education",
                "title": "本科",
                "claim": source,
                "skills": [],
                "education": {
                    "level": "bachelor",
                    "graduation_year": 2020,
                    "graduation_source_text": "2020-2024",
                },
            }
        ]
    }
    repaired = deepcopy(bad)
    repaired["evidence"][0]["education"].update(
        enrollment_year=2020, enrollment_source_text="2020-2024", graduation_year=2024
    )
    client = FakeModelClient(outputs=[bad, repaired])
    records = await ResumeEvidenceExtractor(client).extract(source)
    assert len(client.requests) == 2
    assert "时间角色" in client.requests[1].messages[-1].content
    assert records[0].education.enrollment_year == 2020
    assert records[0].education.graduation_year == 2024


@pytest.mark.asyncio
@pytest.mark.parametrize("repair", [False, True])
async def test_two_stage_parser_preserves_scope_and_full_document_evidence(repair):
    # Scope context intentionally extends outside the extracted requirement.
    clause = "要求硕士学历，本科为计算机相关专业"
    extraction = {
        "facts": {
            "graduation_years": {
                "values": [2027],
                "source_text": "面向2027届应届毕业生",
            }
        },
        "requirements": [{"source_text": clause, "level": "required"}],
        "responsibilities": [],
    }
    relation = {
        "decisions": [
            {
                "requirement_index": 0,
                "relation": "all_of",
                "items": [clause],
                "reason": "硕士为申请学历，本科为历史背景",
                "education": scoped_condition().model_dump(),
            }
        ]
    }
    outputs = [extraction, relation]
    if repair:
        invalid = deepcopy(relation)
        invalid["decisions"][0]["education"]["branches"][1]["scope_source_text"] = (
            "岗位另行要求历史本科背景"
        )
        outputs.insert(1, invalid)
    client = FakeModelClient(outputs=outputs)
    parsed = await ProductJDParser(client).parse(
        RawJobDocument(raw_content=SCOPE_SOURCE)
    )
    assert len(client.requests) == (3 if repair else 2)
    assert (
        parsed.structured_jd.requirements[0].education.branches[1].scope == "historical"
    )
    evidence = [
        e
        for e in parsed.structured_jd.requirements[0].evidence
        if e.field_path.endswith(".scope")
    ]
    assert len(evidence) == 2
    for item in evidence:
        assert SCOPE_SOURCE[item.start_char : item.end_char] == item.source_text
    result = check_eligibility(
        EligibilityInput(
            profile=candidate(),
            job=parsed.structured_jd,
            preferences=SearchPreferences(),
        ),
        include_search_preferences=False,
    )
    assert result.eligible == "pass"


@pytest.mark.asyncio
async def test_profile_api_roundtrips_distinct_years_and_explicit_correction(
    db_session,
):
    record = EducationRecord(
        level="master",
        enrollment_year=2024,
        enrollment_source_text="2024-2027",
        graduation_year=2028,
        graduation_source_text=None,
        graduation_year_kind="expected",
        graduation_year_confirmed=True,
        source_text="硕士 2024-2027 预计毕业",
        source="resume_asset:v3:asset",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.put(
            "/api/profile",
            headers={"X-User-ID": "a"},
            json={"educations": [record.model_dump()]},
        )
        assert response.status_code == 200, response.text
        saved = (await client.get("/api/profile", headers={"X-User-ID": "a"})).json()
    assert saved["graduation_year"] == 2028
    actual = saved["educations"][0]
    assert {k: v for k, v in actual.items() if k != "provenance"} == record.model_dump(exclude={"provenance"})
    assert actual["provenance"]["extracted"]["graduation_year"] == 2028
