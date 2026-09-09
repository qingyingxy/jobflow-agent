from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.domain.job import SkillRequirementGroup
from src.domain.skill_normalizer import normalize_atomic_skill_values
from src.domain.unified_jd import UnifiedJDModelOutput

_SKILL_CATEGORIES = frozenset(
    {"skill", "capability", "experience", "responsibility"}
)


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key not in seen:
            result.append(value)
            seen.add(key)
    return result


class CompiledUnifiedSkillFields(BaseModel):
    """Compatibility view compiled from clauses; never a second fact source."""

    model_config = ConfigDict(extra="forbid")

    required_skills: list[str] = Field(default_factory=list)
    required_skill_groups: list[SkillRequirementGroup] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    skill_mentions: list[str] = Field(default_factory=list)

    def as_legacy_fields(self) -> dict[str, object | None]:
        return {
            "required_skills": self.required_skills or None,
            "required_skill_groups": [
                group.model_dump(mode="json")
                for group in self.required_skill_groups
            ]
            or None,
            "preferred_skills": self.preferred_skills or None,
            "skill_mentions": self.skill_mentions or None,
        }


def compile_unified_skill_fields(
    output: UnifiedJDModelOutput,
) -> CompiledUnifiedSkillFields:
    """Compile four stable skill fields without reclassifying clause semantics."""

    required: list[str] = []
    preferred: list[str] = []
    mentions: list[str] = []
    groups: list[SkillRequirementGroup] = []
    seen_groups: set[tuple[str, tuple[str, ...], bool]] = set()

    for clause in output.clauses:
        if clause.category not in _SKILL_CATEGORIES:
            continue
        items = normalize_atomic_skill_values(
            clause.items,
            source_text=clause.source_text,
        )
        examples = normalize_atomic_skill_values(
            clause.examples or [],
            source_text=clause.source_text,
        )
        if clause.relation == "any_of" and len(items) < 2:
            raise ValueError(
                "any_of 候选项在本地归一化后少于两个，不能编译为逻辑组"
            )

        if clause.level == "required":
            if clause.relation == "any_of":
                group = SkillRequirementGroup(
                    name=clause.group_name or "技能选项",
                    any_of=items,
                    allow_other=clause.allow_other,
                )
                key = (
                    group.name.casefold(),
                    tuple(item.casefold() for item in group.any_of),
                    group.allow_other,
                )
                if key not in seen_groups:
                    groups.append(group)
                    seen_groups.add(key)
            else:
                required.extend(items)
        elif clause.level == "preferred":
            # The source clause retains any_of semantics. The four-field legacy
            # view intentionally flattens non-gating preferred alternatives.
            preferred.extend(items)
        else:
            mentions.extend(items)
        mentions.extend(examples)

    required = _unique(required)
    preferred = _unique(preferred)
    mentions = _unique(mentions)
    required_keys = {item.casefold() for item in required}
    required_group_keys = {
        option.casefold()
        for group in groups
        for option in group.any_of
    }
    preferred = [
        item
        for item in preferred
        if item.casefold() not in required_keys | required_group_keys
    ]
    preferred_keys = {item.casefold() for item in preferred}
    mentions = [
        item
        for item in mentions
        if item.casefold()
        not in required_keys | required_group_keys | preferred_keys
    ]

    return CompiledUnifiedSkillFields(
        required_skills=required,
        required_skill_groups=groups,
        preferred_skills=preferred,
        skill_mentions=mentions,
    )
