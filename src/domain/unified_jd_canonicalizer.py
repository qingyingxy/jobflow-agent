from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.domain.unified_jd import (
    ClauseCategory,
    ClauseLevel,
    ClauseRelation,
    NonEmptyText,
    UnifiedJDModelOutput,
)

UNIFIED_JD_CANONICALIZER_VERSION = "unified-jd-canonicalizer-v1"

_WHITESPACE = re.compile(r"\s+")
_EXACT_ALIASES = {
    "agent 工作流": "Agent工作流",
    "ai 工具": "AI工具",
    "cet 6": "CET-6",
    "cet-6": "CET-6",
    "cet6": "CET-6",
    "pipeline 优化": "Pipeline优化",
    "prompt engineering": "Prompt Engineering",
    "pytorch 框架": "PyTorch",
    "pytorch框架": "PyTorch",
    "tool use": "Tool Use",
    "大学英语六级": "CET-6",
    "大型语言模型": "大语言模型",
    "英语六级": "CET-6",
}
_TECHNOLOGY_NAMES = {
    "autogen": "AutoGen",
    "chatgpt": "ChatGPT",
    "claude code": "Claude Code",
    "codex": "Codex",
    "langchain": "LangChain",
    "matlab": "MATLAB",
    "mcp": "MCP",
    "numpy": "NumPy",
    "paddlepaddle": "PaddlePaddle",
    "python": "Python",
    "pytorch": "PyTorch",
    "rag": "RAG",
    "rlhf": "RLHF",
    "scipy": "SciPy",
    "sft": "SFT",
    "simulink": "Simulink",
    "tensorflow": "TensorFlow",
}


class CanonicalItemMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface_item: NonEmptyText
    canonical_item: NonEmptyText
    rule_ids: list[str] = Field(default_factory=list)


class CanonicalClauseProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause_index: int = Field(ge=0)
    category: ClauseCategory
    level: ClauseLevel
    relation: ClauseRelation
    source_text: NonEmptyText
    items: list[CanonicalItemMapping] = Field(min_length=1)


class UnifiedJDCanonicalProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonicalizer_version: str = UNIFIED_JD_CANONICALIZER_VERSION
    clauses: list[CanonicalClauseProjection] = Field(default_factory=list)


def canonicalize_item(surface_item: str) -> CanonicalItemMapping:
    value = surface_item
    rule_ids: list[str] = []
    normalized = unicodedata.normalize("NFKC", value)
    if normalized != value:
        rule_ids.append("canonical.nfkc")
    collapsed = _WHITESPACE.sub(" ", normalized).strip()
    if collapsed != normalized:
        rule_ids.append("canonical.whitespace")

    key = collapsed.casefold()
    canonical = _EXACT_ALIASES.get(key)
    if canonical is not None:
        rule_ids.append("canonical.exact-alias")
    else:
        canonical = _TECHNOLOGY_NAMES.get(key, collapsed)
        if canonical != collapsed:
            rule_ids.append("canonical.technology-casing")
    if not rule_ids:
        rule_ids.append("canonical.identity")
    return CanonicalItemMapping(
        surface_item=surface_item,
        canonical_item=canonical,
        rule_ids=rule_ids,
    )


def canonicalize_unified_output(
    output: UnifiedJDModelOutput | dict[str, Any],
) -> tuple[UnifiedJDModelOutput, UnifiedJDCanonicalProjection]:
    structured = (
        output
        if isinstance(output, UnifiedJDModelOutput)
        else UnifiedJDModelOutput.model_validate(output)
    )
    clauses = []
    projections: list[CanonicalClauseProjection] = []
    for clause_index, clause in enumerate(structured.clauses):
        mappings = [canonicalize_item(item) for item in clause.items]
        canonical_items = _unique(item.canonical_item for item in mappings)
        if clause.relation == "any_of" and len(canonical_items) < 2:
            mappings = [
                CanonicalItemMapping(
                    surface_item=item.surface_item,
                    canonical_item=_WHITESPACE.sub(
                        " ", unicodedata.normalize("NFKC", item.surface_item)
                    ).strip(),
                    rule_ids=[*item.rule_ids, "canonical.any-of-collision-veto"],
                )
                for item in mappings
            ]
            canonical_items = _unique(item.canonical_item for item in mappings)
        clauses.append(clause.model_copy(update={"items": canonical_items}))
        projections.append(
            CanonicalClauseProjection(
                clause_index=clause_index,
                category=clause.category,
                level=clause.level,
                relation=clause.relation,
                source_text=clause.source_text,
                items=mappings,
            )
        )
    canonicalized = UnifiedJDModelOutput.model_validate(
        structured.model_copy(update={"clauses": clauses})
    )
    return canonicalized, UnifiedJDCanonicalProjection(clauses=projections)


def _unique(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key not in seen:
            result.append(value)
            seen.add(key)
    return result
