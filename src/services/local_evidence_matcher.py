from __future__ import annotations

from collections.abc import Sequence

from src.domain.job import JobRequirement
from src.domain.matching import EvidenceRecord, RequirementMatch
from src.services.eligibility_checker import normalize_text
from src.services.evidence_retriever import canonical_skill, skill_mentions


def _record_supports(item: str, evidence: EvidenceRecord) -> bool:
    evidence_text = f"{evidence.title} {evidence.claim} {' '.join(evidence.skills)}"
    item_skills = skill_mentions(item)
    evidence_skills = skill_mentions(evidence_text) | {
        canonical_skill(skill) for skill in evidence.skills
    }
    if item_skills and item_skills & evidence_skills:
        return True

    normalized_item = normalize_text(item)
    normalized_evidence = normalize_text(evidence_text)
    return len(normalized_item) >= 2 and normalized_item in normalized_evidence


def match_requirement_locally(
    *,
    user_id: str,
    requirement: JobRequirement,
    evidence: Sequence[EvidenceRecord],
) -> RequirementMatch:
    """Match only explicit local evidence; abstain when support is unclear."""

    records = [item for item in evidence if item.user_id == user_id]
    requirement_items = requirement.items or [requirement.name]
    matched_by_item: dict[str, EvidenceRecord] = {}
    for requirement_item in requirement_items:
        for record in records:
            if _record_supports(requirement_item, record):
                matched_by_item[requirement_item] = record
                break

    matched_items = list(matched_by_item)
    evidence_ids = list(
        dict.fromkeys(record.id for record in matched_by_item.values())
    )
    if requirement.relation == "uncertain":
        return RequirementMatch(
            requirement=requirement,
            support_level="needs_confirmation",
            evidence_ids=evidence_ids,
            explanation=(
                "岗位原文中的条件关系无法可靠确定，请先人工确认是全部满足还是任选其一。"
            ),
        )
    any_option_supported = requirement.relation == "any_of" and bool(matched_items)
    all_options_supported = (
        requirement.relation == "all_of"
        and len(matched_items) == len(requirement_items)
    )
    if any_option_supported or all_options_supported:
        support_level = "supported"
    elif matched_items:
        support_level = "partial"
    else:
        support_level = "needs_confirmation"

    if support_level == "supported":
        explanation = (
            f"当前经历明确支持：{'、'.join(matched_items)}。"
            "结论仅来自已保存的用户证据。"
        )
    elif support_level == "partial":
        missing = [item for item in requirement_items if item not in matched_by_item]
        explanation = (
            f"当前经历支持：{'、'.join(matched_items)}；"
            f"仍需确认：{'、'.join(missing)}。"
        )
    else:
        explanation = (
            "当前结构化经历中没有找到足以确认该要求的直接证据，"
            "这不代表用户一定不具备，请人工确认。"
        )

    return RequirementMatch(
        requirement=requirement,
        support_level=support_level,
        evidence_ids=evidence_ids,
        explanation=explanation,
    )


def match_requirements_locally(
    *,
    user_id: str,
    requirements: Sequence[JobRequirement] | None,
    evidence: Sequence[EvidenceRecord],
) -> list[RequirementMatch]:
    return [
        match_requirement_locally(
            user_id=user_id,
            requirement=requirement,
            evidence=evidence,
        )
        for requirement in requirements or []
    ]
