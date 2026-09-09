from __future__ import annotations

import unicodedata
from copy import deepcopy
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

ProductJobType = Literal["campus", "internship", "full_time", "part_time"]
RequirementLevel = Literal["required", "preferred"]
RequirementRelation = Literal["all_of", "any_of", "uncertain"]

NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


def _unique_text(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            result.append(normalized)
            seen.add(key)
    if not result:
        raise ValueError("列表至少需要一个非空值")
    return result


class ProductScalarFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: NonEmptyText
    source_text: NonEmptyText


class ProductJobTypeFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: ProductJobType
    source_text: NonEmptyText


class ProductTextListFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: list[NonEmptyText] = Field(min_length=1)
    source_text: NonEmptyText

    @field_validator("values")
    @classmethod
    def normalize_values(cls, value: list[str]) -> list[str]:
        return _unique_text(value)


class ProductYearListFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: list[int] = Field(min_length=1)
    source_text: NonEmptyText

    @field_validator("values")
    @classmethod
    def normalize_years(cls, value: list[int]) -> list[int]:
        years = sorted(set(value))
        if any(year < 1900 or year > 2200 for year in years):
            raise ValueError("毕业年份必须在 1900 到 2200 之间")
        return years


class ProductDateFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: date
    source_text: NonEmptyText


class ProductJobFacts(BaseModel):
    """Small set of facts that can affect an application decision."""

    model_config = ConfigDict(extra="forbid")

    job_type: ProductJobTypeFact | None = None
    locations: ProductTextListFact | None = None
    graduation_years: ProductYearListFact | None = None
    education_requirements: ProductTextListFact | None = None
    major_requirements: ProductTextListFact | None = None
    deadline: ProductDateFact | None = None


class ProductRequirementExtraction(BaseModel):
    """One requirement span extracted without deciding its internal logic."""

    model_config = ConfigDict(extra="forbid")

    source_text: NonEmptyText
    level: RequirementLevel


class ProductJDExtractionOutput(BaseModel):
    """Stage-one output: source spans only, without relation classification."""

    model_config = ConfigDict(extra="forbid")

    facts: ProductJobFacts
    requirements: list[ProductRequirementExtraction] = Field(
        default_factory=list,
        max_length=50,
    )
    responsibilities: list[NonEmptyText] = Field(default_factory=list, max_length=50)

    @field_validator("responsibilities")
    @classmethod
    def normalize_responsibilities(cls, value: list[str]) -> list[str]:
        return _unique_text(value) if value else []


class ProductRelationDecision(BaseModel):
    """Stage-two semantic decision for one indexed extracted requirement."""

    model_config = ConfigDict(extra="forbid")

    requirement_index: int = Field(ge=0)
    relation: RequirementRelation
    items: list[NonEmptyText] = Field(min_length=1, max_length=12)
    reason: NonEmptyText

    @field_validator("items")
    @classmethod
    def normalize_items(cls, value: list[str]) -> list[str]:
        return _unique_text(value)

    @model_validator(mode="after")
    def validate_relation(self) -> ProductRelationDecision:
        if self.relation == "any_of" and len(self.items) < 2:
            raise ValueError("any_of 至少需要两个原文选项")
        return self


class ProductRelationJudgmentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[ProductRelationDecision] = Field(default_factory=list, max_length=50)


class ProductRequirement(BaseModel):
    """One source clause after API-based relation classification."""

    model_config = ConfigDict(extra="forbid")

    source_text: NonEmptyText
    level: RequirementLevel
    relation: RequirementRelation = "all_of"
    items: list[NonEmptyText] = Field(min_length=1, max_length=12)
    relation_reason: NonEmptyText | None = None

    @field_validator("items")
    @classmethod
    def normalize_items(cls, value: list[str]) -> list[str]:
        return _unique_text(value)

    @model_validator(mode="after")
    def validate_relation(self) -> ProductRequirement:
        if self.relation == "any_of" and len(self.items) < 2:
            raise ValueError("any_of 至少需要两个原文选项")
        return self


class ProductJDModelOutput(BaseModel):
    """The only model-owned contract used by the product runtime."""

    model_config = ConfigDict(extra="forbid")

    facts: ProductJobFacts
    requirements: list[ProductRequirement] = Field(default_factory=list, max_length=50)
    responsibilities: list[NonEmptyText] = Field(default_factory=list, max_length=50)

    @field_validator("responsibilities")
    @classmethod
    def normalize_responsibilities(cls, value: list[str]) -> list[str]:
        return _unique_text(value) if value else []


def _comparable(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _fact_values_have_source_support(
    field: str,
    fact: dict[str, Any],
) -> bool:
    source_text = fact.get("source_text")
    if not isinstance(source_text, str):
        return False
    comparable_source = _comparable(source_text)
    if field in {
        "locations",
        "education_requirements",
        "major_requirements",
    }:
        values = fact.get("values")
        return (
            isinstance(values, list)
            and bool(values)
            and all(
                isinstance(value, str)
                and bool(_comparable(value))
                and _comparable(value) in comparable_source
                for value in values
            )
        )
    return True


def validate_product_jd_output(
    output: ProductJDModelOutput,
    source_content: str,
) -> None:
    """Reject unsupported quotes and rewritten items without judging semantics."""

    invalid: list[str] = []
    for field in (
        "job_type",
        "locations",
        "graduation_years",
        "education_requirements",
        "major_requirements",
        "deadline",
    ):
        fact = getattr(output.facts, field)
        if fact is None:
            continue
        if fact.source_text not in source_content:
            invalid.append(f"facts.{field}.source_text")
            continue
        comparable_source = _comparable(fact.source_text)
        if isinstance(fact, ProductTextListFact):
            for value_index, value in enumerate(fact.values):
                if _comparable(value) not in comparable_source:
                    invalid.append(f"facts.{field}.values[{value_index}]")

    for index, requirement in enumerate(output.requirements):
        if requirement.source_text not in source_content:
            invalid.append(f"requirements[{index}].source_text")
            continue
        comparable_source = _comparable(requirement.source_text)
        for item_index, item in enumerate(requirement.items):
            if _comparable(item) not in comparable_source:
                invalid.append(f"requirements[{index}].items[{item_index}]")
    for index, responsibility in enumerate(output.responsibilities):
        if responsibility not in source_content:
            invalid.append(f"responsibilities[{index}]")

    if invalid:
        raise ValueError("以下产品 JD 字段没有逐字原文支持：" + ", ".join(invalid))


def validate_product_jd_extraction(
    output: ProductJDExtractionOutput,
    source_content: str,
) -> None:
    """Validate stage-one spans without inferring requirement relations."""

    provisional = ProductJDModelOutput(
        facts=output.facts,
        requirements=[
            ProductRequirement(
                source_text=requirement.source_text,
                level=requirement.level,
                relation="uncertain",
                items=[requirement.source_text],
            )
            for requirement in output.requirements
        ],
        responsibilities=output.responsibilities,
    )
    validate_product_jd_output(provisional, source_content)


def validate_product_relation_judgment(
    output: ProductRelationJudgmentOutput,
    extraction: ProductJDExtractionOutput,
) -> None:
    """Require one source-backed API decision for every extracted requirement."""

    expected_indices = set(range(len(extraction.requirements)))
    actual_indices = [decision.requirement_index for decision in output.decisions]
    if len(actual_indices) != len(set(actual_indices)):
        raise ValueError("关系判断包含重复的 requirement_index")
    if set(actual_indices) != expected_indices:
        raise ValueError("关系判断必须完整覆盖所有 requirement_index")

    invalid: list[str] = []
    for decision in output.decisions:
        source_text = extraction.requirements[decision.requirement_index].source_text
        comparable_source = _comparable(source_text)
        for item_index, item in enumerate(decision.items):
            if _comparable(item) not in comparable_source:
                invalid.append(
                    f"decisions[{decision.requirement_index}].items[{item_index}]"
                )
    if invalid:
        raise ValueError("以下关系选项没有逐字原文支持：" + ", ".join(invalid))


def sanitize_product_jd_payload(payload: Any, source_content: str) -> Any:
    """Conservatively remove unsupported model text before strict validation."""

    if not isinstance(payload, dict):
        return payload
    sanitized = deepcopy(payload)
    facts = sanitized.get("facts")
    if isinstance(facts, dict):
        for field in (
            "job_type",
            "locations",
            "graduation_years",
            "education_requirements",
            "major_requirements",
            "deadline",
        ):
            fact = facts.get(field)
            if not isinstance(fact, dict):
                continue
            source_text = fact.get("source_text")
            if (
                not isinstance(source_text, str)
                or source_text not in source_content
                or not _fact_values_have_source_support(field, fact)
            ):
                facts[field] = None

    requirements = sanitized.get("requirements")
    if isinstance(requirements, list):
        cleaned_requirements: list[dict[str, Any]] = []
        for requirement in requirements:
            if not isinstance(requirement, dict):
                continue
            source_text = requirement.get("source_text")
            if not isinstance(source_text, str) or source_text not in source_content:
                continue
            items = requirement.get("items")
            if not isinstance(items, list):
                requirement["items"] = [source_text]
                requirement["relation"] = "all_of"
                cleaned_requirements.append(requirement)
                continue
            valid_items = [
                item
                for item in items
                if isinstance(item, str)
                and bool(_comparable(item))
                and _comparable(item) in _comparable(source_text)
            ]
            unique_valid_items = {_comparable(item) for item in valid_items}
            relation = requirement.get("relation")
            valid_any_of = (
                relation == "any_of"
                and 2 <= len(valid_items) <= 12
                and len(unique_valid_items) == len(valid_items)
                and len(valid_items) == len(items)
            )
            if relation == "any_of" and not valid_any_of:
                requirement["relation"] = "all_of"
                requirement["items"] = [source_text]
            elif relation in {"all_of", "uncertain"} and (
                not valid_items
                or len(valid_items) > 12
                or len(valid_items) != len(items)
            ):
                requirement["items"] = [source_text]
            cleaned_requirements.append(requirement)
        sanitized["requirements"] = cleaned_requirements

    responsibilities = sanitized.get("responsibilities")
    if isinstance(responsibilities, list):
        sanitized["responsibilities"] = [
            item
            for item in responsibilities
            if isinstance(item, str) and item in source_content
        ]
    return sanitized
