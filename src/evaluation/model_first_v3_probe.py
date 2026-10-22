from __future__ import annotations

from statistics import mean
from typing import Any

from src.domain.unified_jd import UnifiedJDModelOutput


def analyze_v3_surface_probe(
    *,
    raw_output: dict[str, Any],
    raw_content: str,
    baseline_surface: dict[str, int | float],
    expected: UnifiedJDModelOutput,
) -> dict[str, Any]:
    """Measure observed pair behavior without repairing the invalid response."""

    raw_facts = raw_output.get("fact_mentions")
    raw_clauses = raw_output.get("clauses")
    facts = raw_facts if isinstance(raw_facts, list) else []
    clauses = raw_clauses if isinstance(raw_clauses, list) else []
    fact_objects = [item for item in facts if isinstance(item, dict)]
    clause_objects = [item for item in clauses if isinstance(item, dict)]
    clause_items = [
        item
        for clause in clause_objects
        for item in clause.get("items", [])
        if isinstance(clause.get("items"), list) and isinstance(item, dict)
    ]

    fact_surface = _surface_summary(
        fact_objects,
        raw_content,
        source_key="source_text",
    )
    clause_surface = _surface_summary(
        clause_items,
        raw_content,
        source_key="source_text",
    )
    semantic_pairs = [
        (item.get("semantic_item"), item.get("surface_item"))
        for item in clause_items
        if isinstance(item.get("semantic_item"), str)
        and isinstance(item.get("surface_item"), str)
    ]
    grouped_source_counts = [
        len(
            {
                item.get("source_text")
                for item in clause.get("items", [])
                if isinstance(item, dict) and isinstance(item.get("source_text"), str)
            }
        )
        for clause in clause_objects
        if isinstance(clause.get("items"), list)
    ]
    expected_non_fact_clauses = [
        clause for clause in expected.clauses if clause.category != "fact"
    ]
    expected_item_count = sum(len(clause.items) for clause in expected_non_fact_clauses)
    observed_item_count = len(clause_items)
    topology = {
        "fact_count": len(fact_objects),
        "facts_using_expected_field_key": sum("field" in item for item in fact_objects),
        "facts_using_observed_fact_key": sum("fact" in item for item in fact_objects),
        "facts_with_expected_items_array": sum(
            isinstance(item.get("items"), list) for item in fact_objects
        ),
        "facts_flattened_to_single_item": sum(
            "raw_item" in item and "surface_item" in item for item in fact_objects
        ),
        "clause_count": len(clause_objects),
        "clauses_with_category": sum("category" in item for item in clause_objects),
        "clauses_with_source_text": sum(
            "source_text" in item for item in clause_objects
        ),
        "items_with_unexpected_source_text": sum(
            "source_text" in item for item in clause_items
        ),
        "clauses_grouping_multiple_source_texts": sum(
            count > 1 for count in grouped_source_counts
        ),
    }
    identical_pairs = sum(semantic == surface for semantic, surface in semantic_pairs)
    different_pairs = len(semantic_pairs) - identical_pairs
    return {
        "response_topology": topology,
        "surface_pairing": {
            "facts": fact_surface,
            "clause_items": clause_surface,
        },
        "semantic_surface_separation": {
            "paired_item_count": len(semantic_pairs),
            "identical_count": identical_pairs,
            "different_count": different_pairs,
            "separation_rate": (
                different_pairs / len(semantic_pairs) if semantic_pairs else None
            ),
        },
        "granularity": {
            "gold_non_fact_clause_count": len(expected_non_fact_clauses),
            "gold_non_fact_item_count": expected_item_count,
            "v1_semantic_item_count": baseline_surface["semantic_item_count"],
            "observed_v3_item_count": observed_item_count,
            "observed_versus_v1_item_ratio": (
                observed_item_count / baseline_surface["semantic_item_count"]
            ),
            "observed_versus_gold_item_ratio": (
                observed_item_count / expected_item_count
                if expected_item_count
                else None
            ),
            "mean_observed_surface_chars": (
                mean(
                    len(item["surface_item"])
                    for item in clause_items
                    if isinstance(item.get("surface_item"), str)
                )
                if clause_items
                else None
            ),
        },
        "mechanism_checks": {
            "paired_values_were_attempted": bool(fact_objects or semantic_pairs),
            "all_observed_surfaces_are_exact_full_jd_substrings": (
                fact_surface["full_jd_exact_rate"] == 1.0
                and clause_surface["full_jd_exact_rate"] == 1.0
            ),
            "semantic_and_surface_values_were_actually_separated": different_pairs > 0,
            "required_response_topology_was_followed": (
                topology["facts_using_expected_field_key"] == len(fact_objects)
                and topology["facts_with_expected_items_array"] == len(fact_objects)
                and topology["clauses_with_category"] == len(clause_objects)
                and topology["clauses_with_source_text"] == len(clause_objects)
                and topology["items_with_unexpected_source_text"] == 0
            ),
            "v1_item_granularity_was_retained": (
                observed_item_count >= baseline_surface["semantic_item_count"]
            ),
        },
    }


def _surface_summary(
    items: list[dict[str, Any]],
    raw_content: str,
    *,
    source_key: str,
) -> dict[str, int | float | None]:
    pairs = [
        (item.get("surface_item"), item.get(source_key))
        for item in items
        if isinstance(item.get("surface_item"), str)
    ]
    full_exact = sum(surface in raw_content for surface, _ in pairs)
    local_exact = sum(
        isinstance(source, str) and surface in source for surface, source in pairs
    )
    return {
        "emitted_count": len(pairs),
        "full_jd_exact_count": full_exact,
        "full_jd_exact_rate": full_exact / len(pairs) if pairs else None,
        "local_source_exact_count": local_exact,
        "local_source_exact_rate": local_exact / len(pairs) if pairs else None,
    }
