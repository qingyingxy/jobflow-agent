from sqlalchemy import select

from src.domain.education import validate_condition_grounding
from src.domain.job import (
    FieldEvidence,
    JobRequirement,
    SkillRequirementGroup,
    StructuredJobDescription,
)
from src.domain.job_correction import JobCorrection


def latest_correction(session, user_id, job_id):
    return session.scalar(select(JobCorrection).where(
        JobCorrection.user_id == user_id, JobCorrection.job_posting_id == job_id,
    ).order_by(JobCorrection.revision.desc()).limit(1))


def effective_structure(session, user_id, parse_result):
    correction = latest_correction(session, user_id, parse_result.job_posting_id)
    if (correction and correction.structured_jd is not None
            and correction.parse_result_id == parse_result.id
            and correction.content_hash == parse_result.content_hash):
        return StructuredJobDescription.model_validate(correction.structured_jd)
    return StructuredJobDescription.model_validate(parse_result.structured_jd)


def compile_correction(base, requirements, raw_content):
    """Rebuild derived fields while keeping original facts and typed education."""
    result = base.model_dump(mode="json")
    corrected = []
    for index, requirement in enumerate(requirements):
        if requirement.description not in raw_content:
            raise ValueError("条件原文必须逐字来自当前 JD")
        if any(item not in requirement.description for item in requirement.items or []):
            raise ValueError("每个条件选项必须逐字来自该条原文")
        if requirement.education:
            validate_condition_grounding(requirement.education, requirement.description, document_content=raw_content)
        data = requirement.model_dump(mode="json")
        if data["category"] in {"required_skill", "preferred_skill"}:
            data["category"] = "required_skill" if data["mandatory"] else "preferred_skill"
        start = raw_content.index(requirement.description)
        data["evidence"] = [FieldEvidence(
            field_path=f"requirements[{index}]", source_text=requirement.description,
            start_char=start, end_char=start + len(requirement.description),
        ).model_dump()]
        corrected.append(JobRequirement.model_validate(data))
    result["requirements"] = [r.model_dump(mode="json") for r in corrected]
    prefixes = ("requirements", "required_skills", "preferred_skills", "required_skill_groups")
    evidence = [e for e in base.field_evidence or [] if not e.field_path.startswith(prefixes)]
    for category, field in (("required_skill", "required_skills"), ("preferred_skill", "preferred_skills")):
        items = [r for r in corrected if r.category == category]
        result[field] = list(dict.fromkeys(r.name for r in items)) or None
        evidence.extend(FieldEvidence(field_path=field, source_text=r.description) for r in items)
    groups = [r for r in corrected if r.category == "required_skill" and r.relation == "any_of"]
    result["required_skill_groups"] = [SkillRequirementGroup(name=r.name[:80], any_of=r.items).model_dump() for r in groups] or None
    evidence.extend(FieldEvidence(field_path="required_skill_groups", source_text=r.description) for r in groups)
    result["field_evidence"] = [e.model_dump() for e in evidence]
    return StructuredJobDescription.model_validate(result)
