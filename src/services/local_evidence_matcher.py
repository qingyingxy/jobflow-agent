from __future__ import annotations

from collections.abc import Sequence

from src.domain.eligibility import CandidateProfileInput, EligibilityCheck
from src.domain.job import JobRequirement
from src.domain.matching import EvidenceRecord, RequirementMatch
from src.services.education_evaluator import evaluate_education
from src.services.ordinary_requirement_evaluator import assess_item, requirement_sources


def match_requirement_locally(
    *,
    user_id: str,
    requirement: JobRequirement,
    evidence: Sequence[EvidenceRecord],
    profile: CandidateProfileInput | None = None,
    education_checks: Sequence[EligibilityCheck] | None = None,
) -> RequirementMatch:
    """Match only explicit local evidence; abstain when support is unclear."""

    if requirement.education is not None:
        # Analysis supplies the qualification result so global graduation scope
        # and this requirement's match cannot disagree.
        check = next(
            (
                check
                for check in education_checks or []
                if check.requirement_source_text == requirement.description
            ),
            None,
        )
        if check is not None:
            return RequirementMatch(
                requirement=requirement,
                support_level={
                    "pass": "supported",
                    "fail": "unsupported",
                    "unknown": "needs_confirmation",
                }[check.result],
                education_evidence=check.education_evidence,
                explanation=check.reason,
            )
        result = evaluate_education(
            requirement.education, profile or CandidateProfileInput()
        )
        return RequirementMatch(
            requirement=requirement,
            support_level={
                "pass": "supported",
                "fail": "unsupported",
                "unknown": "needs_confirmation",
            }[result.result],
            education_evidence=result.evidence,
            explanation=result.reason,
        )

    records = [item for item in evidence if item.user_id == user_id]
    sources, relation_known = requirement_sources(requirement)
    checks = [assess_item(source, records) for source in sources]
    for check in checks:
        check.condition_text = check.source_text
        check.source_text = requirement.description
        if not relation_known:
            if check.support_level == "supported":
                check.support_level = "partial"
            check.unresolved.append("分支或限定范围尚未与原文可靠对应")
    supported = [check for check in checks if check.support_level == "supported"]
    evidence_ids = list(dict.fromkeys(eid for check in checks for eid in check.evidence_ids))
    if not relation_known:
        support_level = "needs_confirmation"
        explanation = "条件关系或限定范围尚不能可靠执行，已保留原文并继续分析其他要求。"
    elif (requirement.relation == "any_of" and supported) or (
        requirement.relation == "all_of" and checks and len(supported) == len(checks)
    ):
        support_level = "supported"
        explanation = "当前经历完整支持：" + "、".join(c.condition_text for c in supported) + "。"
    elif any(check.evidence_ids for check in checks):
        support_level = "partial"
        skills = sorted({skill for check in checks for skill in check.matched_skills})
        explanation = (
            ("已找到相关技能证据：" + "、".join(skills) + "；" if skills else "已找到部分证据；")
            + "以下条件尚缺完整证据："
            + "、".join(c.condition_text for c in checks if c.support_level != "supported")
            + "。不会据此认定整条要求已满足，可继续查看其他匹配结果。"
        )
    else:
        support_level = "needs_confirmation"
        explanation = "当前经历尚无足够的直接证据，已保留为信息不足；可继续分析，有补充资料时再更新。"
    return RequirementMatch(
        requirement=requirement,
        support_level=support_level,
        evidence_ids=evidence_ids,
        item_checks=checks,
        explanation=explanation,
    )


def match_requirements_locally(
    *,
    user_id: str,
    requirements: Sequence[JobRequirement] | None,
    evidence: Sequence[EvidenceRecord],
    profile: CandidateProfileInput | None = None,
    education_checks: Sequence[EligibilityCheck] | None = None,
) -> list[RequirementMatch]:
    return [
        match_requirement_locally(
            user_id=user_id,
            requirement=requirement,
            evidence=evidence,
            profile=profile,
            education_checks=education_checks,
        )
        for requirement in requirements or []
    ]
