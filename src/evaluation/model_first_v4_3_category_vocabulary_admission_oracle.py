from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from src.domain.unified_jd_extraction import UnifiedFactMentionV2
from src.domain.unified_jd_flat_atomic_v4 import UnifiedJDFlatAtomicClauseV4
from src.evaluation.model_first_v4_live_probe import (
    ATOM_FIELDS,
    FACT_FIELDS,
    ROOT_FIELDS,
    UnifiedJDFlatAtomicLiveResponseV4,
    analyze_live_response_v4,
)

OracleSemanticClauseCategory = Literal[
    "skill",
    "capability",
    "experience",
    "responsibility",
    "knowledge",
    "motivation",
]

FROZEN_CATEGORIES = frozenset(
    {"skill", "capability", "experience", "responsibility"}
)
ADMITTED_CATEGORIES = frozenset({"knowledge", "motivation"})


class CategoryVocabularyAdmissionClauseV4(UnifiedJDFlatAtomicClauseV4):
    """Frozen v4 atom with only the category literal union widened."""

    category: OracleSemanticClauseCategory


class CategoryVocabularyAdmissionResponseV4(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_mentions: list[UnifiedFactMentionV2]
    clause_atoms: list[CategoryVocabularyAdmissionClauseV4]


def analyze_category_vocabulary_admission(
    raw_output: object,
    source_content: str,
) -> dict[str, Any]:
    """Validate without mutating output under the preregistered enum-only schema."""

    baseline = analyze_live_response_v4(raw_output, source_content)
    diagnostics: list[dict[str, Any]] = []
    if not isinstance(raw_output, dict):
        return {
            "schema_valid": False,
            "diagnostics": [
                {"path": "response", "code": "root_not_object"}
            ],
        }

    root_keys_exact = set(raw_output) == ROOT_FIELDS
    raw_facts = raw_output.get("fact_mentions")
    raw_atoms = raw_output.get("clause_atoms")
    fact_array_valid = isinstance(raw_facts, list)
    atom_array_valid = isinstance(raw_atoms, list)
    fact_fields_exact = fact_array_valid and all(
        isinstance(fact, dict) and set(fact) == FACT_FIELDS for fact in raw_facts
    )
    atom_fields_exact = atom_array_valid and all(
        isinstance(atom, dict) and set(atom) == ATOM_FIELDS for atom in raw_atoms
    )
    no_nested_clause_fields = atom_array_valid and all(
        isinstance(atom, dict)
        and not any(key in atom for key in ("items", "examples", "clauses"))
        for atom in raw_atoms
    )
    parsed: CategoryVocabularyAdmissionResponseV4 | None = None
    try:
        parsed = CategoryVocabularyAdmissionResponseV4.model_validate(raw_output)
    except ValidationError as error:
        diagnostics.extend(
            {
                "path": ".".join(str(part) for part in item["loc"]),
                "code": item["type"],
                "message": item["msg"],
            }
            for item in error.errors()
        )

    schema_valid = bool(
        root_keys_exact
        and fact_array_valid
        and atom_array_valid
        and fact_fields_exact
        and atom_fields_exact
        and no_nested_clause_fields
        and parsed is not None
    )
    return {
        "schema_valid": schema_valid,
        "root_keys_exact": root_keys_exact,
        "fact_fields_exact": fact_fields_exact,
        "atom_fields_exact": atom_fields_exact,
        "no_nested_clause_fields": no_nested_clause_fields,
        "diagnostics": diagnostics,
        "baseline_schema_valid": baseline["schema_valid"],
        "baseline_diagnostics": baseline["diagnostics"],
    }


def category_admission_diagnostics(
    raw_output: object,
    *,
    record_index: int,
) -> list[dict[str, Any]]:
    """Report runtime-observable admitted tokens without changing the payload."""

    if not isinstance(raw_output, dict):
        return []
    atoms = raw_output.get("clause_atoms")
    if not isinstance(atoms, list):
        return []
    return [
        {
            "record_index": record_index,
            "atom_index": atom_index,
            "path": f"clause_atoms[{atom_index}].category",
            "category": atom["category"],
        }
        for atom_index, atom in enumerate(atoms)
        if isinstance(atom, dict) and atom.get("category") in ADMITTED_CATEGORIES
    ]


def schema_delta_is_category_only() -> bool:
    """Prove the oracle model inherits every non-category v4 atom contract."""

    base_fields = UnifiedJDFlatAtomicClauseV4.model_fields
    oracle_fields = CategoryVocabularyAdmissionClauseV4.model_fields
    base_response_fields = UnifiedJDFlatAtomicLiveResponseV4.model_fields
    oracle_response_fields = CategoryVocabularyAdmissionResponseV4.model_fields
    non_category_fields_match = all(
        _field_signature(oracle_fields[name]) == _field_signature(base_fields[name])
        for name in base_fields
        if name != "category"
    )
    validators_match = (
        set(CategoryVocabularyAdmissionClauseV4.__pydantic_decorators__.model_validators)
        == set(UnifiedJDFlatAtomicClauseV4.__pydantic_decorators__.model_validators)
    )
    return bool(
        set(oracle_fields) == set(base_fields)
        and set(oracle_response_fields) == set(base_response_fields)
        and _field_signature(oracle_response_fields["fact_mentions"])
        == _field_signature(base_response_fields["fact_mentions"])
        and non_category_fields_match
        and validators_match
        and _category_enum(CategoryVocabularyAdmissionClauseV4)
        == sorted(FROZEN_CATEGORIES | ADMITTED_CATEGORIES)
        and _category_enum(UnifiedJDFlatAtomicClauseV4)
        == sorted(FROZEN_CATEGORIES)
    )


def _field_signature(field: Any) -> tuple[Any, ...]:
    return (
        field.annotation,
        field.default,
        field.default_factory,
        tuple(field.metadata),
        field.alias,
        field.validation_alias,
        field.serialization_alias,
        field.exclude,
    )


def _category_enum(model: type[BaseModel]) -> list[str]:
    schema = model.model_json_schema()
    category = schema["properties"]["category"]
    values = category.get("enum")
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise TypeError("category field does not expose a string enum")
    return sorted(values)
