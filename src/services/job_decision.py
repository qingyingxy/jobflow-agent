from __future__ import annotations

from collections.abc import Sequence

from src.domain.analysis import JobDecision
from src.domain.eligibility import EligibilityResult
from src.domain.matching import RequirementMatch


def build_job_decision(
    *,
    eligibility: EligibilityResult,
    matches: Sequence[RequirementMatch],
) -> JobDecision:
    """Return an explainable four-level decision without a numeric score."""

    required = [match for match in matches if match.requirement.mandatory]
    supported = [match for match in required if match.support_level == "supported"]
    confirmation = [
        match
        for match in required
        if match.support_level in {"partial", "needs_confirmation", "unsupported"}
    ]
    failed_checks = [check for check in eligibility.checks if check.result == "fail"]
    unknown_checks = [check for check in eligibility.checks if check.result == "unknown"]

    reasons: list[str] = []
    if failed_checks:
        reasons.extend(check.reason for check in failed_checks[:3])
        recommendation = "not_recommended"
        summary = "存在明确的硬性资格冲突，建议先核对官方要求。"
    elif unknown_checks:
        reasons.extend(check.reason for check in unknown_checks[:3])
        recommendation = "insufficient_information"
        summary = "缺少决定性岗位或个人信息，当前不宜给出确定建议。"
    elif not required:
        reasons.append("JD 没有识别出明确的必须条件。")
        recommendation = "insufficient_information"
        summary = "岗位条件信息不足，请补充完整 JD 或人工确认。"
    elif confirmation:
        reasons.append(
            f"{len(supported)}/{len(required)} 条必须条件有直接经历证据，"
            f"另有 {len(confirmation)} 条需要确认。"
        )
        recommendation = "consider"
        summary = "没有硬性冲突，但必须条件仍存在证据缺口。"
    else:
        reasons.append(f"{len(required)} 条必须条件均有直接经历证据。")
        recommendation = "recommended_application"
        summary = "硬性条件通过，主要必须条件都有真实经历支持。"

    return JobDecision(
        recommendation=recommendation,
        summary=summary,
        reasons=reasons,
        required_supported=len(supported),
        required_total=len(required),
        needs_confirmation=len(confirmation) + len(unknown_checks),
    )
