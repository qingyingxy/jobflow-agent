from datetime import date

import pytest

from src.domain.education import EducationRecord
from src.domain.job import StructuredJobDescription
from src.domain.matching import EvidenceRecord
from src.domain.models import EvidenceItem
from src.services.jd_analysis_service import JDAnalysisService
from src.services.job_fact_grounding import ground_runtime_facts
from src.services.legacy_education import education_from_legacy
from src.services.profile_service import ProfileService
from src.services.semantic_evidence_matcher import sentence_catalog


def legacy(eid, claim, user="u"):
    return EvidenceItem(
        id=eid,
        user_id=user,
        type="education",
        title="教育经历",
        claim=claim,
        skills=[],
        source="resume_asset:old",
    )


def test_old_education_restores_separate_records_and_does_not_resurrect_deletions(
    db_session,
):
    service = ProfileService(db_session)
    service.upsert("u", {"degree": "硕士", "major": "错误旧摘要"})
    db_session.add_all(
        [
            legacy("b", "示例大学 机械工程 · 本科 2019.09-2023.07"),
            legacy("m", "另一大学（分校） 金融学 · 硕士 2024.09-2027.07"),
            legacy("other", "示例大学 计算机 · 博士 2021-2026", user="other"),
        ]
    )
    db_session.commit()
    profile = service.get("u")
    records = {r["level"]: r for r in profile.educations}
    assert len(records) == 2
    assert records["bachelor"]["major_raw"] == "机械工程"
    assert records["master"]["major_raw"] == "金融学"
    assert records["master"]["graduation_year"] == 2027
    assert profile.major == "金融学"
    assert not records["master"]["reviewed"]
    assert not profile.education_history_complete
    assert service.get("u").educations == profile.educations
    service.upsert("u", {"educations": []})
    assert service.get("u").educations == []


def test_restore_preserves_manual_education_and_analysis_loads_old_records(db_session):
    service = ProfileService(db_session)
    service.upsert("u", {})
    db_session.add(legacy("b", "示例大学 机械工程 · 本科 2019-2023"))
    db_session.commit()
    inputs, _ = JDAnalysisService(db_session)._profile_inputs("u")
    assert inputs.educations[0].major_raw == "机械工程"
    assert JDAnalysisService(db_session)._evidence_records("u") == []
    manual = EducationRecord(
        level="master", major_raw="用户修正专业", source_text="用户录入硕士专业"
    )
    service.upsert("u", {"educations": [manual.model_dump(mode="json")]})
    assert service.get("u").educations[0]["major_raw"] == "用户修正专业"


@pytest.mark.parametrize(
    "quote,level,major,year",
    [
        (
            "学校：示例大学；专业：材料科学；学历：硕士；2024至今",
            "master",
            "材料科学",
            None,
        ),
        ("本科机械、硕士金融", "unknown", None, None),
        ("硕士 2024", "master", None, None),
        ("示例大学 机械工程 · 本科 2019-2023", "bachelor", "机械工程", 2023),
    ],
)
def test_legacy_fields_require_explicit_local_evidence(quote, level, major, year):
    record = education_from_legacy(legacy("e", quote))
    assert (record.level, record.major_raw, record.graduation_year) == (
        level,
        major,
        year,
    )
    assert record.status == "unknown"  # a past year is not a graduation certificate


@pytest.mark.parametrize(
    "text,keep",
    [
        ("上海市 校招 技术 5人 2026-07-21", False),
        ("发布日期：2026-07-21。申请截止日期：2026-08-21", False),
        ("截止日期：2026-07-21", True),
        ("投递截止时间\n2026年7月21日", True),
        ("申请于2026/7/21截止", True),
        ("Application deadline: 2026-07-21", True),
        ("毕业时间2026-07-21，投递截止时间待定", False),
        ("毕业截止日期：2026-07-21", False),
    ],
)
def test_deadline_requires_date_role_not_just_date_presence(text, keep):
    original = StructuredJobDescription(deadline=date(2026, 7, 21))
    result = ground_runtime_facts(original, text)
    assert (result.deadline is not None) == keep
    assert original.deadline == date(2026, 7, 21)


def test_layout_newline_keeps_a_whole_literal_quote():
    claim = "通过持久化工作流、上\n下文管理完成任务。使用 Python 开发。"
    evidence = EvidenceRecord(id="e", user_id="u", title="项目", claim=claim, skills=[])
    quotes = [s["quote"] for s in sentence_catalog([evidence]).values()]
    assert quotes == ["通过持久化工作流、上\n下文管理完成任务。", "使用 Python 开发。"]
    assert all(q in claim for q in quotes)
