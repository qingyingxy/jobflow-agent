from __future__ import annotations

from datetime import date

import httpx
import pytest
from pydantic import ValidationError

from src.domain.eligibility import (
    CandidateProfileInput,
    EligibilityInput,
    SearchPreferences,
)
from src.domain.job import FieldEvidence, StructuredJobDescription
from src.main import app
from src.services.eligibility_checker import check_eligibility


def passing_job() -> StructuredJobDescription:
    return StructuredJobDescription(
        graduation_years=[2027],
        job_type="internship",
        locations=["北京市"],
        education_requirements=["本科及以上"],
        major_requirements=["计算机相关专业"],
        internship_duration_months=6,
        weekly_days=5,
        earliest_start_date=date(2026, 7, 1),
        field_evidence=[
            FieldEvidence(field_path="graduation_years", source_text="2027届"),
            FieldEvidence(field_path="job_type", source_text="实习"),
            FieldEvidence(field_path="locations", source_text="北京市"),
            FieldEvidence(field_path="education_requirements", source_text="本科及以上"),
            FieldEvidence(field_path="major_requirements", source_text="计算机相关专业"),
            FieldEvidence(field_path="internship_duration_months", source_text="6个月"),
            FieldEvidence(field_path="weekly_days", source_text="每周5天"),
            FieldEvidence(field_path="earliest_start_date", source_text="2026年7月1日"),
        ],
    )


def passing_input(
    *,
    profile: CandidateProfileInput | None = None,
    preferences: SearchPreferences | None = None,
    job: StructuredJobDescription | None = None,
) -> EligibilityInput:
    return EligibilityInput(
        profile=profile
        or CandidateProfileInput(
            graduation_year=2027,
            degree="本科",
            major="计算机科学与技术",
        ),
        preferences=preferences
        or SearchPreferences(
            preferred_locations=["北京"],
            job_types=["internship"],
            earliest_start_date=date(2026, 6, 1),
            weekly_days=5,
            internship_duration_months=6,
        ),
        job=job or passing_job(),
    )


def test_search_preferences_have_explicit_types_and_ranges() -> None:
    preferences = SearchPreferences(
        preferred_locations=[" 北京 "],
        job_types=["internship"],
        earliest_start_date="2026-06-01",
        weekly_days=5,
        internship_duration_months=6,
    )

    assert preferences.preferred_locations == ["北京"]
    assert preferences.earliest_start_date == date(2026, 6, 1)

    with pytest.raises(ValidationError):
        SearchPreferences(weekly_days=0)
    with pytest.raises(ValidationError):
        SearchPreferences(internship_duration_months=-1)


def test_legacy_locations_are_normalized_without_dropping_m02_fields() -> None:
    preferences = SearchPreferences(
        target_roles=["AI Agent Engineer"],
        locations=["上海"],
    )

    assert preferences.target_roles == ["AI Agent Engineer"]
    assert preferences.preferred_locations == ["上海"]


def test_eligibility_passes_with_normalized_degree_major_location_and_boundaries() -> None:
    result = check_eligibility(passing_input())

    assert result.eligible == "pass"
    assert all(check.result == "pass" for check in result.checks)
    location_check = next(check for check in result.checks if check.field == "locations")
    assert location_check.jd_evidence[0].source_text == "北京市"


def test_eligibility_is_deterministic_for_identical_inputs() -> None:
    first = check_eligibility(passing_input()).model_dump(mode="json")
    second = check_eligibility(passing_input()).model_dump(mode="json")

    assert first == second


@pytest.mark.parametrize(
    ("input_data", "field"),
    [
        (
            passing_input(profile=CandidateProfileInput(graduation_year=2026, degree="本科", major="计算机科学与技术")),
            "graduation_year",
        ),
        (
            passing_input(profile=CandidateProfileInput(graduation_year=2027, degree="大专", major="计算机科学与技术")),
            "education",
        ),
        (
            passing_input(profile=CandidateProfileInput(graduation_year=2027, degree="本科", major="金融学")),
            "major",
        ),
        (
            passing_input(preferences=SearchPreferences(preferred_locations=["上海"], job_types=["internship"], earliest_start_date=date(2026, 6, 1), weekly_days=5, internship_duration_months=6)),
            "locations",
        ),
        (
            passing_input(preferences=SearchPreferences(preferred_locations=["北京"], job_types=["full_time"], earliest_start_date=date(2026, 6, 1), weekly_days=5, internship_duration_months=6)),
            "job_type",
        ),
    ],
)
def test_each_hard_rule_can_fail_deterministically(
    input_data: EligibilityInput,
    field: str,
) -> None:
    result = check_eligibility(input_data)

    assert result.eligible == "fail"
    failed = [check for check in result.checks if check.field == field]
    assert len(failed) == 1
    assert failed[0].result == "fail"


def test_internship_schedule_is_display_only_and_does_not_gate_eligibility() -> None:
    result = check_eligibility(
        passing_input(
            preferences=SearchPreferences(
                preferred_locations=["北京"],
                job_types=["internship"],
                earliest_start_date=date(2026, 7, 2),
                weekly_days=1,
                internship_duration_months=1,
            )
        )
    )

    assert result.eligible == "pass"
    checked_fields = {check.field for check in result.checks}
    assert "earliest_start_date" not in checked_fields
    assert "weekly_days" not in checked_fields
    assert "internship_duration_months" not in checked_fields


def test_missing_profile_or_jd_information_is_unknown() -> None:
    result = check_eligibility(
        passing_input(
            profile=CandidateProfileInput(),
            preferences=SearchPreferences(),
        )
    )

    assert result.eligible == "unknown"
    assert any(check.result == "unknown" for check in result.checks)
    assert any(check.missing_information for check in result.checks)


def test_fail_has_priority_over_unknown() -> None:
    result = check_eligibility(
        passing_input(
            profile=CandidateProfileInput(
                graduation_year=2026,
                degree=None,
                major=None,
            ),
            preferences=SearchPreferences(),
        )
    )

    assert result.eligible == "fail"
    assert any(check.result == "unknown" for check in result.checks)
    assert any(check.result == "fail" for check in result.checks)


def test_no_explicit_education_or_major_requirement_passes() -> None:
    job = StructuredJobDescription(
        graduation_years=[],
        locations=[],
        education_requirements=[],
        major_requirements=[],
        job_type="full_time",
        earliest_start_date=date(2026, 7, 1),
    )
    result = check_eligibility(
        passing_input(
            profile=CandidateProfileInput(),
            preferences=SearchPreferences(
                preferred_locations=[],
                job_types=[],
                earliest_start_date=date(2026, 6, 1),
            ),
            job=job,
        )
    )

    assert next(check for check in result.checks if check.field == "education").result == "pass"
    assert next(check for check in result.checks if check.field == "major").result == "pass"


@pytest.mark.asyncio
async def test_profile_api_validates_and_serializes_typed_preferences() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            "/api/profile",
            headers={"X-User-ID": "eligibility-user"},
            json={
                "search_preferences": {
                    "preferred_locations": ["北京"],
                    "job_types": ["internship"],
                    "earliest_start_date": "2026-06-01",
                    "weekly_days": 5,
                    "internship_duration_months": 6,
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["search_preferences"]["earliest_start_date"] == "2026-06-01"
