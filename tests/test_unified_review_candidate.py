from __future__ import annotations

from scripts.build_unified_dev50_human_reviewed import (
    DEFAULT_CANDIDATE,
    ROUND2_REVIEW_NOTE,
    build_human_reviewed_manifest,
)
from scripts.build_unified_dev50_human_reviewed import (
    DEFAULT_DECISIONS as DEFAULT_ROUND2_DECISIONS,
)
from scripts.build_unified_dev50_review_candidate import (
    DEFAULT_DECISIONS,
    DEFAULT_DRAFT,
    ROUND1_REVIEW_NOTE,
    build_review_candidate,
)
from scripts.freeze_unified_dev50_labels import DEFAULT_SOURCE as DEFAULT_FREEZE_SOURCE
from scripts.freeze_unified_dev50_labels import (
    EXPECTED_SOURCE_SHA256,
    build_frozen_manifest,
)
from src.domain.unified_jd import UnifiedJDClause
from src.evaluation.unified_models import (
    UnifiedEvaluationCase,
    UnifiedEvaluationManifest,
)


def _case_by_id(
    manifest: UnifiedEvaluationManifest,
    case_id: str,
) -> UnifiedEvaluationCase:
    return next(case for case in manifest.cases if case.id == case_id)


def _clause_by_source(
    case: UnifiedEvaluationCase,
    source_text: str,
) -> UnifiedJDClause:
    assert case.expected is not None
    return next(
        clause for clause in case.expected.clauses if clause.source_text == source_text
    )


def test_round1_review_candidate_applies_all_confirmed_decisions() -> None:
    manifest = build_review_candidate(
        draft_path=DEFAULT_DRAFT,
        decisions_path=DEFAULT_DECISIONS,
    )

    assert manifest.label_status == "draft"
    assert len(manifest.cases) == 50
    assert all(case.annotation_status == "draft" for case in manifest.cases)
    assert all(
        any(ROUND1_REVIEW_NOTE in note for note in case.review_notes)
        for case in manifest.cases
    )

    open_branch_case = _case_by_id(manifest, "campus-ai-089")
    open_branch_clause = _clause_by_source(
        open_branch_case,
        "在 3D 视觉基础模型方向至少一个分支"
        "(DUSt3R/MASt3R/VGGT/Spann3R、3DGS/NeRF、Occupancy/BEV 等)"
        "有深入实践",
    )
    assert open_branch_clause.allow_other is True

    conflict_case = _case_by_id(manifest, "campus-ai-140")
    assert conflict_case.expected.facts.education_requirements == [
        "本科或硕士"
    ]
    assert all(
        clause.source_text != "硕士及以上2027届校园招聘-正式批"
        for clause in conflict_case.expected.clauses
    )

    combined_case = _case_by_id(manifest, "campus-ai-072")
    combined_clause = _clause_by_source(
        combined_case,
        "熟悉当前大语言模型（LLM）的原理、Prompt Engineering或RAG架构",
    )
    assert combined_clause.relation == "any_of"
    assert combined_clause.items == [
        "大语言模型原理",
        "Prompt Engineering",
        "RAG架构",
    ]

    date_case = _case_by_id(manifest, "campus-ai-052")
    date_clause = next(
        clause
        for clause in date_case.expected.clauses
        if clause.source_text == "毕业时间：2026-11-01 - 2029-09-30"
        and clause.items == ["2026-11-01 至 2029-09-30"]
    )
    assert date_clause.level == "required"

    simulator_case = _case_by_id(manifest, "campus-ai-152")
    simulator_clause = _clause_by_source(
        simulator_case,
        "熟练使用 Isaac Sim、MuJoCo、Genesis 等仿真环境",
    )
    assert simulator_clause.items == ["机器人仿真环境"]
    assert simulator_clause.examples == ["Isaac Sim", "MuJoCo", "Genesis"]


def test_round2_review_builds_human_reviewed_labels() -> None:
    manifest = build_human_reviewed_manifest(
        candidate_path=DEFAULT_CANDIDATE,
        decisions_path=DEFAULT_ROUND2_DECISIONS,
    )

    assert manifest.label_status == "human_reviewed"
    assert len(manifest.cases) == 50
    assert all(case.annotation_status == "human_reviewed" for case in manifest.cases)
    assert all(
        any(ROUND2_REVIEW_NOTE in note for note in case.review_notes)
        for case in manifest.cases
    )

    health_case = _case_by_id(manifest, "campus-ai-008")
    assert _clause_by_source(
        health_case,
        "在公开数据集或国际竞赛上取得优异成绩者优先",
    ).relation == "any_of"
    assert _clause_by_source(
        health_case,
        "能够提出新算法、新架构或新范式",
    ).relation == "any_of"

    agent_case = _case_by_id(manifest, "campus-ai-153")
    assert _clause_by_source(
        agent_case,
        "设计分层或端到端 Agent 架构",
    ).relation == "any_of"
    assert _clause_by_source(
        agent_case,
        "覆盖任务理解、行为规划与 VLA/RL/WBC 动作执行",
    ).relation == "all_of"

    solution_case = _case_by_id(manifest, "campus-ai-072")
    assert _clause_by_source(
        solution_case,
        "设计基于大模型（LLM）或自动化算法的解决方案",
    ).relation == "any_of"

    open_group_case = _case_by_id(manifest, "campus-ai-027")
    assert _clause_by_source(
        open_group_case,
        "有Agent开发、Agent框架、Agent Skills等相关经验者优先",
    ).allow_other is True


def test_round2_review_does_not_use_job_titles_as_fact_evidence() -> None:
    manifest = build_human_reviewed_manifest(
        candidate_path=DEFAULT_CANDIDATE,
        decisions_path=DEFAULT_ROUND2_DECISIONS,
    )

    for case in manifest.cases:
        assert case.expected is not None
        assert all(
            evidence.source_text != case.source.title
            for evidence in case.expected.facts.evidence
        )

    year_removed_case = _case_by_id(manifest, "campus-ai-068")
    assert year_removed_case.expected is not None
    assert year_removed_case.expected.facts.graduation_years is None


def test_round2_review_normalizes_named_framework_examples() -> None:
    manifest = build_human_reviewed_manifest(
        candidate_path=DEFAULT_CANDIDATE,
        decisions_path=DEFAULT_ROUND2_DECISIONS,
    )

    low_code_case = _case_by_id(manifest, "campus-ai-073")
    low_code_clause = _clause_by_source(
        low_code_case,
        "熟练使用Coze/Dify等低代码平台",
    )
    assert low_code_clause.items == ["低代码平台"]
    assert low_code_clause.examples == ["Coze", "Dify"]

    framework_case = _case_by_id(manifest, "campus-ai-052")
    framework_clause = _clause_by_source(
        framework_case,
        "精通Python及PyTorch/TensorFlow等框架",
    )
    assert framework_clause.items == ["Python", "深度学习框架"]
    assert framework_clause.examples == ["PyTorch", "TensorFlow"]


def test_reviewed_labels_freeze_only_from_approved_hash() -> None:
    manifest = build_frozen_manifest(DEFAULT_FREEZE_SOURCE)

    assert EXPECTED_SOURCE_SHA256 == (
        "d3edc8b3dc448e499236987d61e322112ebca594a481320f28bd4ec61cc02b0f"
    )
    assert manifest.label_status == "frozen"
    assert len(manifest.cases) == 50
    assert all(case.annotation_status == "frozen" for case in manifest.cases)
