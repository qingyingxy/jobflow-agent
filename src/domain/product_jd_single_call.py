"""Inline runtime contract; frozen extraction and evaluation contracts stay intact."""

from pydantic import BaseModel, ConfigDict, Field

from src.domain.education import EducationCondition
from src.domain.product_jd import (
    NonEmptyText,
    ProductJDExtractionOutput,
    ProductRequirementExtraction,
    RequirementRelation,
)


class SingleCallRequirement(ProductRequirementExtraction):
    relation: RequirementRelation
    items: list[NonEmptyText] = Field(default_factory=list, max_length=12)
    reason: NonEmptyText
    education: EducationCondition | None = None


class SingleCallOutput(ProductJDExtractionOutput):
    requirements: list[SingleCallRequirement] = Field(
        default_factory=list, max_length=50
    )


class RequirementRepair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_index: int = Field(ge=0)
    requirement: SingleCallRequirement


class SingleCallRepairOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repaired_requirements: list[RequirementRepair] = Field(min_length=1, max_length=50)
