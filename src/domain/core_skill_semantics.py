from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.domain.job import ParsingWarning
from src.domain.skill_normalizer import (
    explicit_skill_categories,
    normalize_atomic_skill_values,
    normalize_skill_group,
    normalize_skill_groups,
    normalize_skill_values,
    skill_category_for,
)

CoreJobType = Literal[
    "campus",
    "internship",
    "full_time",
    "part_time",
    "unknown",
]
SkillStrength = Literal["required", "preferred", "mention"]
SkillRelation = Literal["all_of", "any_of"]


class CoreSkillClause(BaseModel):
    """One source-backed semantic scope from a job description."""

    model_config = ConfigDict(extra="forbid")

    source_text: str = Field(
        min_length=1,
        description="Exact contiguous text copied from the job description.",
    )
    strength: SkillStrength
    relation: SkillRelation
    skills: list[str] = Field(
        min_length=1,
        description="Atomic skills that share this clause's strength and relation.",
    )
    group_name: str | None = Field(
        default=None,
        description="Shared category for skills when relation is any_of.",
    )
    allow_other: bool = False

    @model_validator(mode="after")
    def require_skill_content(self) -> CoreSkillClause:
        if self.relation == "any_of" and len(self.skills) < 2:
            raise ValueError("any_of relation must contain at least two skills")
        if self.relation == "all_of" and self.group_name is not None:
            raise ValueError("group_name requires any_of relation")
        if self.relation == "all_of" and self.allow_other:
            raise ValueError("allow_other requires any_of relation")
        return self


class CoreModelOutput(BaseModel):
    """Clause-oriented model contract; public CoreJobFields remain unchanged."""

    model_config = ConfigDict(extra="forbid")

    job_type: CoreJobType | None = None
    locations: list[str] | None = None
    skill_clauses: list[CoreSkillClause] | None = None


@dataclass(frozen=True)
class CompiledCoreOutput:
    fields: dict[str, Any]
    skill_sources: dict[str, str]
    warnings: tuple[ParsingWarning, ...] = ()


def compile_core_model_output(
    output: CoreModelOutput,
    *,
    source_content: str,
) -> CompiledCoreOutput:
    """Compile clause decisions once without reclassifying model output."""

    required: list[str] = []
    preferred: list[str] = []
    mentions: list[str] = []
    groups: list[dict[str, Any]] = []
    group_options: list[str] = []
    skill_sources: dict[str, str] = {}
    warnings: list[ParsingWarning] = []

    for index, clause in enumerate(output.skill_clauses or []):
        source_text = _resolve_source_text(clause.source_text, source_content)
        if source_text is None:
            warnings.append(
                ParsingWarning(
                    code="unsupported_clause_evidence",
                    field_path=f"skill_clauses[{index}].source_text",
                    value=clause.source_text,
                    message="已忽略无法在原文中定位的技能条款",
                )
            )
            continue

        skills = normalize_atomic_skill_values(
            clause.skills,
            source_text=source_text,
        )
        skills = expand_tool_capability_compounds(skills, source_text)
        category_mentions: list[str] = []
        if clause.strength == "preferred":
            skills = collapse_shared_experience_suffixes(skills, source_text)
            skills = normalize_source_scoped_preferred_skills(skills, source_text)
            skills = drop_redundant_practice_skills(skills)
            skills = collapse_shared_cae_contexts(skills, source_text)
            skills = collapse_shared_robotics_contexts(skills, source_text)
        if clause.relation == "all_of" and clause.strength in {
            "required",
            "preferred",
        }:
            skills, category_mentions = collapse_category_examples(
                skills,
                source_text,
                source_content=source_content,
            )
            if clause.strength == "required":
                skills = normalize_source_scoped_required_skills(
                    skills,
                    source_text,
                )
                skills, parenthetical_mentions = collapse_parenthetical_examples(
                    skills,
                    source_text,
                )
                category_mentions.extend(parenthetical_mentions)
        for skill in [*skills, *category_mentions]:
            skill_sources.setdefault(skill, source_text)
        mentions.extend(category_mentions)

        if clause.strength == "required":
            if clause.relation == "all_of":
                required.extend(skills)
            else:
                group = normalize_skill_group(
                    {
                        "name": clause.group_name or "技能选项",
                        "any_of": skills,
                        "allow_other": normalize_allow_other(
                            clause.allow_other,
                            source_text,
                        ),
                    },
                    options_are_atomic=True,
                )
                if group is not None:
                    group = normalize_source_scoped_groups(
                        [group],
                        source_content,
                    )[0]
                    groups.append(group)
                    group_options.extend(group["any_of"])
                    for option in group["any_of"]:
                        skill_sources.setdefault(option, source_text)
        elif clause.strength == "preferred":
            # The public v2 contract has no preferred group field, so its options
            # remain preferred skills while the model still classifies them once.
            preferred.extend(skills)
        elif clause.strength == "mention":
            mentions.extend(skills)

    fields = _finalize_fields(
        job_type=output.job_type,
        locations=output.locations,
        required=required,
        preferred=preferred,
        mentions=mentions,
        groups=groups,
        group_options=group_options,
    )
    return CompiledCoreOutput(
        fields=fields,
        skill_sources=skill_sources,
        warnings=tuple(warnings),
    )


def compile_legacy_core_output(payload: dict[str, Any]) -> CompiledCoreOutput:
    """Normalize old flat model fixtures without applying semantic repair rules."""

    required = _normalize_field(payload.get("required_skills"))
    preferred = _normalize_field(payload.get("preferred_skills"))
    mentions = _normalize_field(payload.get("skill_mentions"))
    groups = normalize_skill_groups(payload.get("required_skill_groups"))
    group_options = [option for group in groups for option in group["any_of"]]
    fields = _finalize_fields(
        job_type=payload.get("job_type"),
        locations=payload.get("locations"),
        required=required,
        preferred=preferred,
        mentions=mentions,
        groups=groups,
        group_options=group_options,
    )
    return CompiledCoreOutput(fields=fields, skill_sources={})


def _finalize_fields(
    *,
    job_type: Any,
    locations: Any,
    required: list[str],
    preferred: list[str],
    mentions: list[str],
    groups: list[dict[str, Any]],
    group_options: list[str],
) -> dict[str, Any]:
    normalized_groups = [
        group
        for group in normalize_skill_groups(groups, options_are_atomic=True)
        if len(group["any_of"]) >= 2
    ]
    normalized_group_options = _unique(
        option for group in normalized_groups for option in group["any_of"]
    )
    group_keys = {value.casefold() for value in normalized_group_options}

    normalized_required = [
        value for value in _unique(required) if value.casefold() not in group_keys
    ]
    required_keys = {value.casefold() for value in normalized_required}
    normalized_preferred = [
        value
        for value in _unique(preferred)
        if value.casefold() not in required_keys and value.casefold() not in group_keys
    ]
    preferred_keys = {value.casefold() for value in normalized_preferred}
    normalized_mentions = [
        value
        for value in _unique([*mentions, *group_options, *normalized_group_options])
        if value.casefold() not in required_keys
        and value.casefold() not in preferred_keys
    ]

    return {
        "job_type": job_type.strip() if isinstance(job_type, str) else job_type,
        "locations": _normalize_locations(locations),
        "required_skills": normalized_required or None,
        "required_skill_groups": normalized_groups or None,
        "preferred_skills": normalized_preferred or None,
        "skill_mentions": normalized_mentions or None,
    }


def _normalize_field(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    return normalize_skill_values(values, keep_unknown=True)


def _normalize_locations(value: Any) -> list[str] | None:
    values = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    locations = _unique(
        item.strip()
        for item in values
        if isinstance(item, str) and item.strip()
    )
    return locations or None


_SHARED_EXPERIENCE_SUFFIX = re.compile(
    r"(?:相关)?(?:项目|实习|科研|实践|开源(?:项目)?)(?:经历|经验)?$|"
    r"(?:经历|经验)$",
    flags=re.IGNORECASE,
)


def collapse_shared_experience_suffixes(
    skills: list[str],
    source_text: str,
) -> list[str]:
    """Collapse a model-created skill x experience-suffix Cartesian product.

    A trailing phrase such as "相关项目、实习或开源经历优先" changes the
    strength of the preceding technologies. It does not create a distinct
    project, internship, and open-source skill for every technology. The guard
    only fires when stripping those suffixes exposes repeated base concepts, so
    independent conditions such as "AI 项目或开源实践" remain untouched.
    """

    if len(skills) < 3 or not re.search(
        r"相关[^，,。；\n]{0,24}(?:项目|实习|科研|实践|开源)"
        r"[^，,。；\n]{0,24}(?:经历|经验)",
        source_text,
        flags=re.IGNORECASE,
    ):
        return skills

    naive_bases = [
        _SHARED_EXPERIENCE_SUFFIX.sub("", skill).strip()
        for skill in skills
    ]
    naive_keys = [base.casefold() for base in naive_bases if base]
    has_repeated_bases = len(set(naive_keys)) < len(naive_keys)
    bases = (
        naive_bases
        if has_repeated_bases
        else [
            (
                skill
                if _explicit_project_label(skill, source_text)
                else base
            )
            for skill, base in zip(skills, naive_bases, strict=True)
        ]
    )
    has_shared_tail = bool(
        re.search(
            r"(?:等)?相关[^，,。；\n]{0,24}(?:项目|实习|科研|实践|开源)"
            r"[^，,。；\n]{0,24}(?:经历|经验)",
            source_text,
            flags=re.IGNORECASE,
        )
    )
    if not has_shared_tail and not has_repeated_bases:
        return skills
    return normalize_atomic_skill_values(
        [base or skill for base, skill in zip(bases, skills, strict=True)],
        source_text=source_text,
    )


def _explicit_project_label(skill: str, source_text: str) -> bool:
    if not skill.endswith("项目"):
        return False
    base = skill[: -len("项目")].strip()
    if not base:
        return False
    compact_source = re.sub(r"\s+", "", source_text).casefold()
    compact_base = re.sub(r"\s+", "", base).casefold()
    if re.search(re.escape(compact_base) + r"(?:相关)?项目", compact_source):
        return True
    return bool(
        "研究/项目" in compact_source and compact_base in compact_source
    )


def collapse_category_examples(
    skills: list[str],
    source_text: str,
    *,
    source_content: str | None = None,
) -> tuple[list[str], list[str]]:
    """Keep an explicit upper category and route concrete examples to mentions."""

    explicit_categories = set(explicit_skill_categories(source_text))
    if not explicit_categories and source_content:
        category_context = find_shared_skill_context(skills, source_content)
        if category_context is not None:
            explicit_categories = set(
                explicit_skill_categories(category_context)
            )
    if not explicit_categories:
        return skills, []

    members_by_category: dict[str, list[str]] = {}
    for skill in skills:
        category = skill_category_for(skill)
        if category in explicit_categories:
            members_by_category.setdefault(category, []).append(skill)
    skill_keys = {skill.casefold() for skill in skills}
    collapsed_categories = {
        category
        for category, members in members_by_category.items()
        if len(members) >= 2 or (category.casefold() in skill_keys and members)
    }
    if not collapsed_categories:
        return skills, []

    preferred: list[str] = []
    mentions: list[str] = []
    emitted: set[str] = set()
    for skill in skills:
        category = skill_category_for(skill)
        if category not in collapsed_categories:
            preferred.append(skill)
            continue
        mentions.append(skill)
        if category not in emitted:
            preferred.append(category)
            emitted.add(category)
    return preferred, mentions


def find_shared_skill_context(
    skills: list[str],
    source_content: str,
) -> str | None:
    """Find one source sentence that names at least two clause skills."""

    compact_skills = [
        re.sub(r"\s+", "", skill).casefold()
        for skill in skills
        if skill
    ]
    for segment in re.split(r"[。；;\n]", source_content):
        compact_segment = re.sub(r"\s+", "", segment).casefold()
        named_count = sum(
            compact_skill in compact_segment
            for compact_skill in compact_skills
        )
        if named_count >= 2:
            return segment
    return None


_CLOSED_ALTERNATIVE = re.compile(
    r"中至少一(?:种|门|项)|任选(?:其)?一|任意一(?:种|门|项)|任一",
    flags=re.IGNORECASE,
)
_OPEN_ALTERNATIVE = re.compile(
    r"包括但不限于|(?:如|例如|比如)[^。；\n]{0,80}等|其他|等等",
    flags=re.IGNORECASE,
)


def normalize_allow_other(value: bool, source_text: str) -> bool:
    """Close an explicitly bounded alternative list despite model drift."""

    if _CLOSED_ALTERNATIVE.search(source_text) and not _OPEN_ALTERNATIVE.search(
        source_text
    ):
        return False
    return value


_TOOL_DATA_PROCESSING = re.compile(
    r"^(Python|MATLAB|R|SQL|NumPy|Pandas)\s*数据处理$",
    flags=re.IGNORECASE,
)


def expand_tool_capability_compounds(
    skills: list[str],
    source_text: str,
) -> list[str]:
    """Split a named tool from a shared capability without losing either."""

    if "数据处理" not in source_text:
        return skills
    expanded: list[str] = []
    for skill in skills:
        match = _TOOL_DATA_PROCESSING.fullmatch(skill)
        if match is None:
            expanded.append(skill)
            continue
        expanded.extend((match.group(1), "数据处理"))
    return normalize_atomic_skill_values(expanded, source_text=source_text)


def normalize_source_scoped_required_skills(
    skills: list[str],
    source_text: str,
) -> list[str]:
    """Preserve source-explicit qualifiers on otherwise generic model labels."""

    normalized = list(skills)
    if re.search(r"机器人运动学\s*[、,，/]\s*动力学", source_text):
        normalized = [
            "机器人动力学" if skill == "动力学" else skill
            for skill in normalized
        ]
    if re.search(
        r"深度学习框架[^。；\n]{0,16}(?:架构|运行原理)",
        source_text,
        flags=re.IGNORECASE,
    ):
        normalized = [
            "深度学习框架原理" if skill == "深度学习框架" else skill
            for skill in normalized
        ]
    if re.search(
        r"熟练掌握\s*Python\s*/\s*(?:Go|Golang)\s*编程语言",
        source_text,
        flags=re.IGNORECASE,
    ) and any(skill == "编程语言" for skill in normalized):
        normalized = _replace_skills(
            normalized,
            {"编程语言"},
            ["Python", "Go"],
        )
    if re.search(
        r"使用\s*LLM\s*进行项目开发和效果调优",
        source_text,
        flags=re.IGNORECASE,
    ) and {skill.casefold() for skill in normalized} >= {
        "llm",
        "项目开发",
        "效果调优",
    }:
        normalized = _replace_skills(
            normalized,
            {"LLM", "项目开发", "效果调优"},
            ["LLM项目开发", "LLM效果调优"],
        )
    return normalize_atomic_skill_values(normalized, source_text=source_text)


def collapse_parenthetical_examples(
    skills: list[str],
    source_text: str,
) -> tuple[list[str], list[str]]:
    """Route parenthetical language examples under an explicit ability label."""

    match = re.search(
        r"(?:扎实)?编程\s*[（(](?P<examples>[^）)\n]{1,80})[）)]",
        source_text,
        flags=re.IGNORECASE,
    )
    if match is None or "编程能力" not in skills:
        return skills, []
    examples = match.group("examples")
    language_examples = [
        skill
        for skill in skills
        if skill_category_for(skill) == "编程语言"
        and re.search(re.escape(skill), examples, flags=re.IGNORECASE)
    ]
    if len(language_examples) < 2:
        return skills, []
    example_keys = {skill.casefold() for skill in language_examples}
    return (
        [skill for skill in skills if skill.casefold() not in example_keys],
        language_examples,
    )


def normalize_source_scoped_groups(
    groups: list[dict[str, Any]],
    source_content: str,
) -> list[dict[str, Any]]:
    """Apply a shared source suffix to every option in a bounded group."""

    has_direction_experience_scope = bool(
        re.search(r"任一方向经验(?:均可)?", source_content)
    )
    if not has_direction_experience_scope:
        return groups
    normalized: list[dict[str, Any]] = []
    for group in groups:
        options = list(group["any_of"])
        if len(options) >= 2 and all(option.endswith("方向") for option in options):
            options = [f"{option}经验" for option in options]
        normalized.append({**group, "any_of": options})
    return normalized


def _replace_skills(
    skills: list[str],
    removed: set[str],
    replacements: list[str],
) -> list[str]:
    removed_keys = {skill.casefold() for skill in removed}
    first_index = min(
        index
        for index, skill in enumerate(skills)
        if skill.casefold() in removed_keys
    )
    kept = [skill for skill in skills if skill.casefold() not in removed_keys]
    kept[first_index:first_index] = replacements
    return kept


def normalize_source_scoped_preferred_skills(
    skills: list[str],
    source_text: str,
) -> list[str]:
    """Resolve project semantics that are explicit only in the source clause."""

    has_nlp_project_scope = bool(
        re.search(
            r"(?<![A-Za-z])NLP(?![A-Za-z])[^。；\n]{0,24}研究\s*/\s*项目经历",
            source_text,
            flags=re.IGNORECASE,
        )
    )
    return [
        "NLP项目" if has_nlp_project_scope and skill == "NLP" else skill
        for skill in skills
    ]


def drop_redundant_practice_skills(skills: list[str]) -> list[str]:
    """Drop a generic practice label when the same clause has a specific one."""

    keys = {skill.casefold() for skill in skills}
    result: list[str] = []
    for skill in skills:
        if not skill.endswith("实践"):
            result.append(skill)
            continue
        base = skill[: -len("实践")].strip().casefold()
        has_specific_peer = any(
            key != skill.casefold() and key.startswith(base)
            for key in keys
        )
        if not has_specific_peer:
            result.append(skill)
    return result


def collapse_shared_cae_contexts(
    skills: list[str],
    source_text: str,
) -> list[str]:
    """Avoid multiplying one robotics CAE capability by application contexts."""

    if "机器人CAE分析" not in skills or not re.search(
        r"CAE\s*分析经验",
        source_text,
        flags=re.IGNORECASE,
    ):
        return skills
    return [
        skill
        for skill in skills
        if skill == "机器人CAE分析" or not skill.casefold().endswith("cae分析")
    ]


def collapse_shared_robotics_contexts(
    skills: list[str],
    source_text: str,
) -> list[str]:
    """Collapse robot-form examples under one explicitly shared bonus capability."""

    normalized = list(skills)
    deployment_skills = [
        skill
        for skill in normalized
        if re.fullmatch(r"(?:足式机器人|机械臂|人形机器人)真机部署", skill)
    ]
    if len(deployment_skills) >= 2 and re.search(
        r"(?:足式机器人|机械臂|人形机器人)[^。；\n]{0,48}真机部署经验",
        source_text,
    ):
        normalized = _replace_skills(
            normalized,
            set(deployment_skills),
            ["机器人真机部署"],
        )
    if "开源项目" in normalized and re.search(
        r"机器人[^。；\n]{0,36}开源项目(?:成果)?",
        source_text,
    ):
        normalized = [
            "机器人开源项目" if skill == "开源项目" else skill
            for skill in normalized
        ]
    return normalize_atomic_skill_values(normalized, source_text=source_text)


def normalize_compiled_core_fields(
    payload: dict[str, Any],
    *,
    source_content: str,
) -> dict[str, Any]:
    """Replay deterministic atomic normalization on compiled Core fields.

    This is used to compare ontology/compiler changes against saved model
    predictions without spending another model call. It does not infer new
    skills or change a skill's model-assigned strength.
    """

    groups = normalize_skill_groups(
        payload.get("required_skill_groups"),
        options_are_atomic=True,
    )
    groups = [
        {
            **group,
            "allow_other": normalize_allow_other(
                group["allow_other"],
                find_shared_skill_context(group["any_of"], source_content)
                or source_content,
            ),
        }
        for group in groups
    ]
    groups = normalize_source_scoped_groups(groups, source_content)
    group_options = [option for group in groups for option in group["any_of"]]
    required = expand_tool_capability_compounds(
        normalize_atomic_skill_values(payload.get("required_skills") or []),
        source_content,
    )
    required, required_category_mentions = collapse_category_examples(
        required,
        source_content,
    )
    required = normalize_source_scoped_required_skills(required, source_content)
    required, parenthetical_mentions = collapse_parenthetical_examples(
        required,
        source_content,
    )
    preferred = collapse_shared_experience_suffixes(
        expand_tool_capability_compounds(
            normalize_atomic_skill_values(payload.get("preferred_skills") or []),
            source_content,
        ),
        source_content,
    )
    preferred = normalize_source_scoped_preferred_skills(
        preferred,
        source_content,
    )
    preferred = drop_redundant_practice_skills(preferred)
    preferred = collapse_shared_cae_contexts(preferred, source_content)
    preferred = collapse_shared_robotics_contexts(preferred, source_content)
    preferred, category_mentions = collapse_category_examples(
        preferred,
        source_content,
    )
    return _finalize_fields(
        job_type=payload.get("job_type"),
        locations=payload.get("locations"),
        required=required,
        preferred=preferred,
        mentions=[
            *normalize_atomic_skill_values(payload.get("skill_mentions") or []),
            *required_category_mentions,
            *parenthetical_mentions,
            *category_mentions,
        ],
        groups=groups,
        group_options=group_options,
    )


def _resolve_source_text(fragment: str, source_content: str) -> str | None:
    candidate = fragment.strip()
    if candidate in source_content:
        return candidate
    parts = re.split(r"\s+", candidate)
    if not parts:
        return None
    match = re.search(r"\s*".join(re.escape(part) for part in parts), source_content)
    return match.group(0) if match else None


def _unique(values: Any) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            labels.append(normalized)
            seen.add(key)
    return labels
