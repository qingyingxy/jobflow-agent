from copy import deepcopy

import pytest

from src.domain.models import UserProfile
from src.infrastructure.llm_client import FakeModelClient
from src.services.evidence_service import EvidenceService
from src.services.profile_service import ProfileService
from src.services.resume_ingestion_service import (
    ExtractedResumeEvidence,
    ResumeEvidenceExtractor,
    ResumeIngestionError,
    ResumeIngestionService,
    is_current_resume_asset,
)


def education(**changes):
    facts = {
        "level": "master",
        "school": "A大学",
        "major_raw": "金融",
        "enrollment_year": 2024,
        "graduation_year": 2027,
        "graduation_source_text": "2027预计毕业",
        "graduation_year_kind": "expected",
    }
    facts.update(changes)
    return ExtractedResumeEvidence(
        type="education",
        title="硕士",
        claim=f"A大学 硕士 {facts['major_raw']} 2024入学 {facts['graduation_year']}预计毕业",
        education=facts,
    )


def ingest(session, records, asset="one", user="a"):
    return ResumeIngestionService(
        session, ResumeEvidenceExtractor(FakeModelClient())
    )._replace_extracted_evidence(
        user_id=user,
        asset_id=asset,
        extracted=records,
    )


def test_user_edit_survives_repeat_and_new_source_conflict(db_session):
    ingest(db_session, [education()])
    profile = db_session.get(UserProfile, "a")
    original_id = profile.educations[0]["id"]
    records = deepcopy(profile.educations)
    records[0].update(
        major_raw="金融学",
        graduation_year=2028,
        graduation_source_text=None,
        graduation_year_confirmed=True,
    )
    ProfileService(db_session).upsert(
        "a", {"educations": records, "education_history_complete": True}
    )
    ingest(db_session, [education()], "two")
    saved = profile.educations[0]
    assert saved["id"] == original_id
    assert saved["major_raw"] == "金融学"
    assert saved["graduation_year"] == 2028
    assert saved["graduation_year_confirmed"]
    assert (
        saved["provenance"]["conflicts"] == {}
    )  # repeated extractor error isn't a new conflict
    assert profile.education_history_complete
    ingest(db_session, [education(graduation_year=2029)], "three")
    saved = profile.educations[0]
    assert saved["graduation_year"] == 2028
    assert saved["provenance"]["conflicts"]["graduation_year"]["incoming"] == 2029
    assert is_current_resume_asset(db_session, user_id="a", asset_id="three")
    assert not is_current_resume_asset(db_session, user_id="other", asset_id="three")
    # Plain saving and unrelated editing do not dismiss the discrepancy.
    records = deepcopy(profile.educations)
    records[0]["status"] = "enrolled"
    ProfileService(db_session).upsert("a", {"educations": records})
    assert profile.educations[0]["provenance"]["conflicts"]
    records = deepcopy(profile.educations)
    records[0]["provenance"]["keep_current"] = True
    ProfileService(db_session).upsert("a", {"educations": records})
    assert profile.educations[0]["provenance"]["conflicts"] == {}
    ingest(db_session, [education(graduation_year=2029)], "four")
    assert profile.educations[0]["provenance"]["conflicts"] == {}


def test_unedited_fields_update_and_legacy_reviewed_values_are_retained(db_session):
    ingest(db_session, [education()])
    profile = db_session.get(UserProfile, "a")
    records = deepcopy(profile.educations)
    records[0]["major_raw"] = "金融学"
    ProfileService(db_session).upsert("a", {"educations": records})
    ingest(db_session, [education(graduation_year=2028)], "two")
    assert profile.educations[0]["graduation_year"] == 2028
    records = deepcopy(profile.educations)
    records[0].pop("provenance")
    records[0]["reviewed"] = True
    records[0]["graduation_year"] = 2030
    profile.educations = records
    db_session.commit()
    ingest(db_session, [education()], "three")
    assert profile.educations[0]["graduation_year"] == 2030


def test_same_degree_is_not_identity_and_missing_corrected_record_is_kept(db_session):
    ingest(db_session, [education()])
    profile = db_session.get(UserProfile, "a")
    records = deepcopy(profile.educations)
    records[0]["major_raw"] = "金融学"
    ProfileService(db_session).upsert("a", {"educations": records})
    ingest(db_session, [education(school="B大学", major_raw="计算机")], "two")
    assert len(profile.educations) == 2
    assert profile.educations[0]["major_raw"] == "金融学"


def test_ambiguous_same_school_history_is_quarantined(db_session):
    ingest(db_session, [education()])
    profile = db_session.get(UserProfile, "a")
    records = deepcopy(profile.educations)
    records[0]["major_raw"] = "金融学"
    ProfileService(db_session).upsert(
        "a", {"educations": records, "education_history_complete": True}
    )
    ingest(db_session, [education(enrollment_year=None, major_raw="计算机")], "two")
    assert len(profile.educations) == 1
    assert profile.educations[0]["major_raw"] == "金融学"
    assert profile.educations[0]["provenance"]["conflicts"]
    assert not profile.education_history_complete
    records = deepcopy(profile.educations)
    records[0]["provenance"]["keep_current"] = True
    ProfileService(db_session).upsert("a", {"educations": records})
    ingest(db_session, [education(enrollment_year=None, major_raw="计算机")], "three")
    assert profile.educations[0]["provenance"]["conflicts"] == {}


def test_reimported_automatic_projects_do_not_become_human_overrides(db_session):
    project = ExtractedResumeEvidence(
        type="project", title="自动项目", claim="使用 Python 写脚本"
    )
    ingest(db_session, [project])
    ingest(db_session, [project], "two")
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from src.domain.models import EvidenceItem

    item = db_session.scalar(select(EvidenceItem))
    item.updated_at = datetime.now(UTC) + timedelta(seconds=2)
    db_session.commit()
    ingest(db_session, [education()], "three")
    assert list(db_session.scalars(select(EvidenceItem))) == []


def test_project_edit_and_explicit_removal_survive_reimport(db_session):
    project = ExtractedResumeEvidence(
        type="project",
        title="Python项目",
        claim="使用 Python 写过脚本",
        skills=["Python"],
    )
    item = ingest(db_session, [project, education()])[0]
    EvidenceService(db_session).update(
        "a", item.id, {"claim": "使用 Python 实现服务并测试"}
    )
    result = ingest(db_session, [project, education()], "two")
    assert len(result) == 1 and result[0].id == item.id
    assert result[0].claim == "使用 Python 实现服务并测试"
    EvidenceService(db_session).delete("a", item.id)
    ProfileService(db_session).upsert("a", {"educations": []})
    assert ingest(db_session, [project, education()], "three") == []
    assert db_session.get(UserProfile, "a").educations == []
    assert is_current_resume_asset(db_session, user_id="a", asset_id="three")


@pytest.mark.asyncio
async def test_skill_grounding_cannot_borrow_another_resume_paragraph():
    extractor = ResumeEvidenceExtractor(
        FakeModelClient(
            output={
                "evidence": [
                    {
                        "type": "employment",
                        "title": "三年工作",
                        "claim": "三年 Java 开发经验",
                        "skills": ["Python"],
                    }
                ]
            }
        ),
        validation_retries=0,
    )
    with pytest.raises(ResumeIngestionError):
        await extractor.extract("三年 Java 开发经验。使用 Python 写课程脚本。")
