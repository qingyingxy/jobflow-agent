from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Any

from pydantic import ValidationError

from src.domain.job import (
    FieldEvidence,
    JobRequirement,
    QualificationCondition,
    RawJobDocument,
    StructuredJobDescription,
    validate_field_evidence,
)
from src.domain.skill_normalizer import (
    extract_requirement_skill_matches,
    extract_skill_matches,
    normalize_skill_values,
)
from src.infrastructure.llm_client import StructuredModelClient
from src.services.core_jd_parser import CoreJDParser, ParsedCoreJobDescription
from src.services.detail_jd_parser import (
    DEFAULT_DETAIL_PROMPT_VERSION,
    DetailJDParser,
    ParsedDetailJobDescription,
)
from src.services.jd_parser import (
    SCHEMA_VERSION,
    JDParserError,
    ParsedJobDescription,
)

DEFAULT_STAGED_PROMPT_VERSION = "jd-staged-parser-prompt-v1"
DEFAULT_STAGED_PARSER_VERSION = "jd-staged-parser-v1"


class StagedJDParser:
    """Run small model calls and assemble the legacy full JD contract locally."""

    def __init__(
        self,
        client: StructuredModelClient,
        *,
        prompt_version: str = DEFAULT_STAGED_PROMPT_VERSION,
        parser_version: str = DEFAULT_STAGED_PARSER_VERSION,
        core_prompt_version: str = "jd-core-parser-prompt-v1",
        detail_prompt_version: str = DEFAULT_DETAIL_PROMPT_VERSION,
        validation_retries: int = 1,
    ) -> None:
        self.client = client
        self.prompt_version = prompt_version
        self.parser_version = parser_version
        self.core_parser = CoreJDParser(
            client,
            prompt_version=core_prompt_version,
            validation_retries=validation_retries,
        )
        self.detail_parser = DetailJDParser(
            client,
            prompt_version=detail_prompt_version,
            validation_retries=validation_retries,
        )

    @property
    def model_name(self) -> str:
        return self.client.model_name

    @property
    def schema_version(self) -> str:
        return SCHEMA_VERSION

    async def parse(self, document: RawJobDocument) -> ParsedJobDescription:
        try:
            core = await self.core_parser.parse(document)
        except JDParserError as error:
            raise self._stage_error(error, "core") from error

        try:
            detail = await self.detail_parser.parse(document)
        except JDParserError as error:
            raise self._stage_error(error, "detail") from error

        try:
            structured = _assemble_structured_jd(
                document,
                core=core,
                detail=detail,
            )
        except ValidationError as error:
            raise JDParserError(
                "structured_output_invalid",
                "分阶段岗位解析结果未通过最终校验",
                {"stage": "assembly", "errors": _validation_errors(error)},
            ) from error
        except ValueError as error:
            raise JDParserError(
                "structured_output_invalid",
                "分阶段岗位解析结果未通过最终校验",
                {"stage": "assembly", "errors": [{"message": str(error)}]},
            ) from error

        return ParsedJobDescription(
            structured_jd=structured,
            input_hash=hashlib.sha256(
                document.raw_content.encode("utf-8")
            ).hexdigest(),
            schema_version=SCHEMA_VERSION,
            parser_version=self.parser_version,
            prompt_version=self.prompt_version,
            model=detail.model,
        )

    @staticmethod
    def _stage_error(error: JDParserError, stage: str) -> JDParserError:
        return JDParserError(
            error.code,
            str(error),
            {**error.details, "stage": stage},
        )


def _assemble_structured_jd(
    document: RawJobDocument,
    *,
    core: ParsedCoreJobDescription,
    detail: ParsedDetailJobDescription,
) -> StructuredJobDescription:
    source = document.raw_content
    evidence = list(core.field_evidence)
    detail_fields = detail.fields

    company = _verified_scalar(
        "company",
        detail_fields.company,
        source,
        evidence,
    )
    title = _verified_scalar(
        "title",
        detail_fields.title,
        source,
        evidence,
    )
    graduation_years = _verified_years(
        detail_fields.graduation_years,
        source,
        evidence,
    )
    recruitment_batch = _verified_scalar(
        "recruitment_batch",
        detail_fields.recruitment_batch,
        source,
        evidence,
    )
    education_requirements = _verified_list(
        "education_requirements",
        detail_fields.education_requirements,
        source,
        evidence,
    )
    major_requirements = _verified_list(
        "major_requirements",
        detail_fields.major_requirements,
        source,
        evidence,
    )
    internship_duration_months = _verified_number(
        "internship_duration_months",
        detail_fields.internship_duration_months,
        source,
        patterns=(r"{value}\s*个月", r"{value}\s*month"),
        evidence=evidence,
    )
    weekly_days = _verified_number(
        "weekly_days",
        detail_fields.weekly_days,
        source,
        patterns=(
            r"每周\s*{value}\s*天",
            r"每周\s*{value}\s*日",
            r"一周\s*{value}\s*天",
        ),
        evidence=evidence,
    )
    earliest_start_date = _verified_date(
        "earliest_start_date",
        detail_fields.earliest_start_date,
        source,
        evidence,
    )
    deadline = _verified_date(
        "deadline",
        detail_fields.deadline,
        source,
        evidence,
    )
    application_url = _verified_scalar(
        "application_url",
        detail_fields.application_url,
        source,
        evidence,
    )

    requirements = _build_requirements(
        source,
        core=core,
        detail=detail,
        evidence=evidence,
    )
    required_skills = [
        item.name for item in requirements if item.category == "required_skill"
    ] or None
    preferred_skills = [
        item.name for item in requirements if item.category == "preferred_skill"
    ] or None
    for index, skill in enumerate(preferred_skills or []):
        source_text = _skill_source(skill, source)
        if source_text:
            evidence.append(
                _make_evidence(
                    f"preferred_skills[{index}]",
                    _context_fragment(source, source_text),
                    source,
                )
            )

    qualification_conditions = _build_qualification_conditions(
        source,
        detail=detail,
        evidence=evidence,
    )

    payload = {
        "company": company,
        "title": title,
        "job_type": core.fields.job_type,
        "graduation_years": graduation_years,
        "recruitment_batch": recruitment_batch,
        "locations": core.fields.locations,
        "education_requirements": education_requirements,
        "major_requirements": major_requirements,
        "required_skills": required_skills,
        "preferred_skills": preferred_skills,
        "internship_duration_months": internship_duration_months,
        "weekly_days": weekly_days,
        "earliest_start_date": earliest_start_date,
        "deadline": deadline,
        "application_url": application_url,
        "qualification_conditions": qualification_conditions or None,
        "requirements": requirements or None,
        "field_evidence": evidence,
    }
    structured = StructuredJobDescription.model_validate(payload)
    validate_field_evidence(structured, source)
    return structured


def _build_requirements(
    source: str,
    *,
    core: ParsedCoreJobDescription,
    detail: ParsedDetailJobDescription,
    evidence: list[FieldEvidence],
) -> list[JobRequirement]:
    requirements: list[JobRequirement] = []
    seen: set[tuple[str, str]] = set()

    def add_requirement(
        *,
        category: str,
        name: str,
        description: str,
        mandatory: bool,
        anchor: str | None = None,
    ) -> None:
        normalized_name = name.strip()
        if not normalized_name:
            return
        key = (category, normalized_name.casefold())
        if key in seen:
            return
        source_text = (
            anchor
            or _skill_source(normalized_name, source)
            or _find_source_fragment(normalized_name, source)
            or _find_source_fragment(description, source)
        )
        if not source_text:
            return
        index = len(requirements)
        context = _context_fragment(source, source_text)
        requirement = JobRequirement(
            category=category,
            name=normalized_name,
            description=description.strip() or f"岗位原文提到：{normalized_name}",
            mandatory=mandatory,
            evidence=[
                _make_evidence(
                    f"requirements[{index}]",
                    context,
                    source,
                )
            ],
        )
        requirements.append(requirement)
        seen.add(key)

    skill_sources = _skill_source_map(source)
    for skill in core.fields.required_skills or []:
        add_requirement(
            category="required_skill",
            name=skill,
            description=f"岗位明确要求 {skill}",
            mandatory=True,
            anchor=skill_sources.get(skill),
        )

    for skill in normalize_skill_values(
        detail.fields.preferred_skills or [],
        keep_unknown=False,
    ):
        add_requirement(
            category="preferred_skill",
            name=skill,
            description=f"岗位将 {skill} 作为加分项或优先条件",
            mandatory=False,
            anchor=skill_sources.get(skill),
        )

    for item in detail.fields.requirements or []:
        if item.category == "required_skill":
            continue
        if item.category == "preferred_skill":
            labels = normalize_skill_values([item.name], keep_unknown=False)
            for label in labels:
                add_requirement(
                    category="preferred_skill",
                    name=label,
                    description=item.description,
                    mandatory=False,
                    anchor=skill_sources.get(label),
                )
            continue
        add_requirement(
            category=item.category,
            name=item.name,
            description=item.description,
            mandatory=item.mandatory,
        )

    if requirements:
        first_source = requirements[0].evidence[0].source_text
        evidence.append(_make_evidence("requirements", first_source, source))
    return requirements


def _build_qualification_conditions(
    source: str,
    *,
    detail: ParsedDetailJobDescription,
    evidence: list[FieldEvidence],
) -> list[QualificationCondition]:
    conditions: list[QualificationCondition] = []
    for item in detail.fields.qualification_conditions or []:
        source_text = _condition_source(item.field, item.value, source)
        if not source_text and item.operator == "unknown":
            source_text = _find_source_fragment(item.field, source)
        if not source_text:
            continue
        index = len(conditions)
        context = _context_fragment(source, source_text)
        condition = QualificationCondition(
            field=item.field,
            operator=item.operator,
            value=item.value,
            source_text=context,
            evidence=[
                _make_evidence(
                    f"qualification_conditions[{index}]",
                    context,
                    source,
                )
            ],
        )
        conditions.append(condition)

    if conditions:
        first_source = conditions[0].evidence[0].source_text
        evidence.append(
            _make_evidence("qualification_conditions", first_source, source)
        )
    return conditions


def _verified_scalar(
    field_name: str,
    value: Any,
    source: str,
    evidence: list[FieldEvidence],
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    source_text = _find_source_fragment(value, source)
    if not source_text:
        return None
    evidence.append(
        _make_evidence(field_name, _context_fragment(source, source_text), source)
    )
    return value.strip()


def _verified_list(
    field_name: str,
    values: list[str] | None,
    source: str,
    evidence: list[FieldEvidence],
) -> list[str] | None:
    accepted: list[str] = []
    for value in values or []:
        source_text = _find_source_fragment(value, source)
        if not source_text:
            continue
        if value in accepted:
            continue
        index = len(accepted)
        evidence.append(
            _make_evidence(
                f"{field_name}[{index}]",
                _context_fragment(source, source_text),
                source,
            )
        )
        accepted.append(value.strip())
    return accepted or None


def _verified_years(
    values: list[int] | None,
    source: str,
    evidence: list[FieldEvidence],
) -> list[int] | None:
    accepted: list[int] = []
    for value in values or []:
        source_text = _find_source_fragment(str(value), source)
        if not source_text or value in accepted:
            continue
        index = len(accepted)
        evidence.append(
            _make_evidence(
                f"graduation_years[{index}]",
                _context_fragment(source, source_text),
                source,
            )
        )
        accepted.append(value)
    return accepted or None


def _verified_number(
    field_name: str,
    value: int | None,
    source: str,
    *,
    patterns: tuple[str, ...],
    evidence: list[FieldEvidence],
) -> int | None:
    if value is None:
        return None
    for pattern in patterns:
        match = re.search(pattern.format(value=re.escape(str(value))), source, re.IGNORECASE)
        if match:
            evidence.append(
                _make_evidence(
                    field_name,
                    _context_fragment(source, match.group(0)),
                    source,
                )
            )
            return value
    return None


def _verified_date(
    field_name: str,
    value: str | None,
    source: str,
    evidence: list[FieldEvidence],
) -> date | None:
    parsed = _parse_date(value)
    if parsed is None:
        return None
    source_text = _date_source(parsed, source)
    if not source_text:
        return None
    evidence.append(
        _make_evidence(field_name, _context_fragment(source, source_text), source)
    )
    return parsed


def _parse_date(value: str | None) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("/", "-").replace("年", "-")
    normalized = normalized.replace("月", "-").replace("日", "")
    try:
        return date.fromisoformat(normalized)
    except ValueError:
        return None


def _date_source(value: date, source: str) -> str | None:
    candidates = (
        value.isoformat(),
        f"{value.year}年{value.month}月{value.day}日",
        f"{value.year}/{value.month}/{value.day}",
        f"{value.year}-{value.month}-{value.day}",
    )
    return _find_first_source(candidates, source)


def _condition_source(field: str, value: Any, source: str) -> str | None:
    values: list[str] = []
    if isinstance(value, list):
        values.extend(str(item) for item in value)
    elif value is not None:
        values.append(str(value))
    for candidate in values:
        found = _find_source_fragment(candidate, source)
        if found:
            return found

    field_key = field.casefold()
    if "graduation" in field_key or "毕业" in field:
        match = re.search(r"\d{4}\s*届|\d{4}\s*年", source)
        if match:
            return match.group(0)
    if "degree" in field_key or "education" in field_key or "学历" in field:
        match = re.search(r"本科|硕士|博士|大专|学历", source)
        if match:
            return match.group(0)
    if "major" in field_key or "专业" in field:
        match = re.search(r"[^。；\n]{0,20}专业", source)
        if match:
            return match.group(0)
    return None


def _skill_source_map(source: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    matches = [
        *extract_requirement_skill_matches(source),
        *extract_skill_matches(source),
    ]
    for match in matches:
        mapping.setdefault(match.canonical, match.source_text)
    return mapping


def _skill_source(skill: str, source: str) -> str | None:
    return _skill_source_map(source).get(skill) or _find_source_fragment(
        skill,
        source,
    )


def _find_first_source(candidates: tuple[str, ...], source: str) -> str | None:
    for candidate in candidates:
        if candidate and candidate in source:
            return candidate
    return None


def _find_source_fragment(value: str, source: str) -> str | None:
    normalized = value.strip()
    if not normalized:
        return None
    start = source.casefold().find(normalized.casefold())
    if start < 0:
        return None
    return source[start : start + len(normalized)]


def _context_fragment(source: str, anchor: str) -> str:
    index = source.find(anchor)
    if index < 0:
        return anchor
    boundaries = "。；;\n"
    start = max(source.rfind(boundary, 0, index) for boundary in boundaries) + 1
    end_candidates = [
        source.find(boundary, index + len(anchor))
        for boundary in boundaries
        if source.find(boundary, index + len(anchor)) >= 0
    ]
    end = min(end_candidates) if end_candidates else len(source)
    return source[start:end].strip() or anchor


def _make_evidence(
    field_path: str,
    source_text: str,
    source: str,
) -> FieldEvidence:
    start = source.find(source_text)
    return FieldEvidence(
        field_path=field_path,
        source_text=source_text,
        start_char=start if start >= 0 else None,
        end_char=(start + len(source_text)) if start >= 0 else None,
    )


def _validation_errors(error: ValidationError) -> list[dict[str, Any]]:
    return [
        {
            "location": list(item["loc"]),
            "message": item["msg"],
            "type": item["type"],
        }
        for item in error.errors()
    ]
