from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.evaluation.unified_metrics import (
    _canonical_text,
    _clause_evidence_spans,
    _match_evidence_spans,
)
from src.evaluation.unified_models import UnifiedEvaluationManifest
from src.services.unified_jd_extraction import (
    UNIFIED_EXTRACTION_COMPILER_VERSION,
    compile_unified_extraction_v2,
)

DEFAULT_MANIFEST = Path(
    "artifacts/evaluation/unified-jd-dev50-frozen-v2-2026-09-04.json"
)
DEFAULT_EXPERIMENT = Path(
    "artifacts/evaluation/unified-jd-evidence-line-probe-v2-2026-09-04.json"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evaluation/unified-jd-relation-canonical-analysis-v1-2026-09-04.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compact_text(value: str) -> str:
    return "".join(
        character for character in _canonical_text(value) if character.isalnum()
    )


def _relation_markers(source_text: str) -> list[str]:
    markers: list[str] = []
    patterns = {
        "at_least_one": r"至少(?:一|1)(?:项|种|门|个)?",
        "explicit_choice": r"任一|任选|之一",
        "or": r"或者|或",
        "open_list": r"包括但不限于|不限于|等相关|等核心|等概念",
        "slash": r"/",
    }
    for name, pattern in patterns.items():
        if re.search(pattern, source_text, flags=re.IGNORECASE):
            markers.append(name)
    return markers


def _relation_error_type(
    expected_relation: str,
    predicted_relation: str,
    markers: list[str],
) -> str:
    if expected_relation == "any_of" and predicted_relation == "all_of":
        if set(markers) & {"at_least_one", "explicit_choice", "or"}:
            return "missed_explicit_alternative"
        return "missed_annotation_policy_alternative"
    if set(markers) & {"or", "slash"}:
        return "spurious_alternative_from_surface_marker"
    return "spurious_alternative"


def _relation_causal_bucket(
    *,
    expected_relation: str,
    predicted_relation: str,
    expected_items: list[str],
    predicted_items: list[str],
    shared_evidence_ambiguous: bool,
) -> str:
    if shared_evidence_ambiguous:
        return "shared_evidence_alignment_ambiguity"
    if expected_relation == "any_of" and predicted_relation == "all_of":
        if len(expected_items) > 1 and len(predicted_items) == 1:
            return "alternative_not_decomposed"
        return "relation_misclassified_after_decomposition"
    if len(expected_items) == 1 and len(predicted_items) > 1:
        return "concept_examples_split_as_choices"
    return "spurious_alternative"


def _item_analysis(
    expected_items: list[str], predicted_items: list[str]
) -> dict[str, Any]:
    expected = Counter(_canonical_text(item) for item in expected_items)
    predicted = Counter(_canonical_text(item) for item in predicted_items)
    exact = expected & predicted
    compact_expected = Counter(_compact_text(item) for item in expected_items)
    compact_predicted = Counter(_compact_text(item) for item in predicted_items)
    compact_exact = compact_expected & compact_predicted
    expected_only = expected - predicted
    predicted_only = predicted - expected
    has_containment = any(
        expected_compact in predicted_compact or predicted_compact in expected_compact
        for expected_item in expected_only
        for predicted_item in predicted_only
        if (expected_compact := _compact_text(expected_item))
        and (predicted_compact := _compact_text(predicted_item))
    )
    if expected == predicted:
        surface_class = "exact_set"
    elif exact:
        surface_class = "partial_exact_overlap"
    elif has_containment:
        surface_class = "lexical_containment_only"
    else:
        surface_class = "divergent_surface"
    if len(expected_items) == len(predicted_items):
        cardinality = "same_count"
    elif len(expected_items) > len(predicted_items):
        cardinality = "predicted_fewer_items"
    else:
        cardinality = "predicted_more_items"
    return {
        "surface_class": surface_class,
        "cardinality": cardinality,
        "exact_item_count": sum(exact.values()),
        "compact_exact_item_count": sum(compact_exact.values()),
        "compact_exact_set": compact_expected == compact_predicted,
        "expected_item_count": len(expected_items),
        "predicted_item_count": len(predicted_items),
        "expected_only": sorted(expected_only.elements()),
        "predicted_only": sorted(predicted_only.elements()),
    }


def build_analysis(
    manifest: UnifiedEvaluationManifest,
    experiment: dict[str, Any],
) -> dict[str, Any]:
    cases_by_id = {case.id: case for case in manifest.cases}
    relation_errors: list[dict[str, Any]] = []
    canonical_pairs: list[dict[str, Any]] = []
    per_repetition: dict[int, dict[str, Any]] = {}

    for record in experiment["records"]:
        case = cases_by_id[record["case_id"]]
        if case.expected is None or record.get("raw_output") is None:
            continue
        predicted = compile_unified_extraction_v2(
            record["raw_output"],
            case.raw_content,
        ).output
        expected_spans = _clause_evidence_spans(case.expected, case.raw_content)
        predicted_spans = _clause_evidence_spans(predicted, case.raw_content)
        matches = _match_evidence_spans(expected_spans, predicted_spans)
        expected_span_counts = Counter(
            (span.start, span.end) for span in expected_spans if span.located
        )
        predicted_span_counts = Counter(
            (span.start, span.end) for span in predicted_spans if span.located
        )
        repetition = int(record["repetition"])
        if repetition not in per_repetition:
            per_repetition[repetition] = {
                "span_matched_clause_count": 0,
                "relation_error_count": 0,
                "relation_errors_by_type": Counter(),
                "same_category_pair_count": 0,
                "canonical_surface_classes": Counter(),
                "canonical_cardinality": Counter(),
                "exact_item_count": 0,
                "compact_exact_item_count": 0,
                "expected_item_count": 0,
                "predicted_item_count": 0,
            }
        repetition_stats = per_repetition[repetition]
        repetition_stats["span_matched_clause_count"] += len(matches)

        for expected_span, predicted_span, iou in matches:
            expected_clause = case.expected.clauses[expected_span.index]
            predicted_clause = predicted.clauses[predicted_span.index]
            markers = _relation_markers(expected_clause.source_text)
            shared_evidence_ambiguous = (
                expected_span.located
                and predicted_span.located
                and (
                    expected_span_counts[(expected_span.start, expected_span.end)] > 1
                    or predicted_span_counts[(predicted_span.start, predicted_span.end)]
                    > 1
                )
            )
            if expected_clause.relation != predicted_clause.relation:
                error_type = _relation_error_type(
                    expected_clause.relation,
                    predicted_clause.relation,
                    markers,
                )
                repetition_stats["relation_error_count"] += 1
                repetition_stats["relation_errors_by_type"][error_type] += 1
                relation_errors.append(
                    {
                        "repetition": repetition,
                        "case_id": case.id,
                        "expected_clause_index": expected_span.index,
                        "predicted_clause_index": predicted_span.index,
                        "category": expected_clause.category,
                        "source_text": expected_clause.source_text,
                        "expected_relation": expected_clause.relation,
                        "predicted_relation": predicted_clause.relation,
                        "markers": markers,
                        "error_type": error_type,
                        "causal_bucket": _relation_causal_bucket(
                            expected_relation=expected_clause.relation,
                            predicted_relation=predicted_clause.relation,
                            expected_items=expected_clause.items,
                            predicted_items=predicted_clause.items,
                            shared_evidence_ambiguous=shared_evidence_ambiguous,
                        ),
                        "shared_evidence_ambiguous": shared_evidence_ambiguous,
                        "expected_items": expected_clause.items,
                        "predicted_items": predicted_clause.items,
                        "span_iou": iou,
                    }
                )

            if expected_clause.category != predicted_clause.category:
                continue
            repetition_stats["same_category_pair_count"] += 1
            item_analysis = _item_analysis(
                expected_clause.items,
                predicted_clause.items,
            )
            repetition_stats["canonical_surface_classes"][
                item_analysis["surface_class"]
            ] += 1
            repetition_stats["canonical_cardinality"][item_analysis["cardinality"]] += 1
            repetition_stats["exact_item_count"] += item_analysis["exact_item_count"]
            repetition_stats["compact_exact_item_count"] += item_analysis[
                "compact_exact_item_count"
            ]
            repetition_stats["expected_item_count"] += item_analysis[
                "expected_item_count"
            ]
            repetition_stats["predicted_item_count"] += item_analysis[
                "predicted_item_count"
            ]
            source_copy = any(
                _canonical_text(item) == _canonical_text(predicted_clause.source_text)
                for item in predicted_clause.items
            )
            canonical_pairs.append(
                {
                    "repetition": repetition,
                    "case_id": case.id,
                    "expected_clause_index": expected_span.index,
                    "predicted_clause_index": predicted_span.index,
                    "category": expected_clause.category,
                    "source_text": expected_clause.source_text,
                    "expected_items": expected_clause.items,
                    "predicted_items": predicted_clause.items,
                    "predicted_contains_full_source_copy": source_copy,
                    "shared_evidence_ambiguous": shared_evidence_ambiguous,
                    "span_iou": iou,
                    **item_analysis,
                }
            )

    relation_by_category: Counter[str] = Counter()
    relation_by_type: Counter[str] = Counter()
    relation_by_causal_bucket: Counter[str] = Counter()
    for item in relation_errors:
        relation_by_category[item["category"]] += 1
        relation_by_type[item["error_type"]] += 1
        relation_by_causal_bucket[item["causal_bucket"]] += 1

    canonical_by_category: dict[str, Counter[str]] = defaultdict(Counter)
    canonical_cardinality: Counter[str] = Counter()
    canonical_cardinality_by_category: dict[str, Counter[str]] = defaultdict(Counter)
    full_source_copy_by_category: Counter[str] = Counter()
    non_exact_source_copy_by_category: Counter[str] = Counter()
    for item in canonical_pairs:
        canonical_by_category[item["category"]][item["surface_class"]] += 1
        canonical_cardinality[item["cardinality"]] += 1
        canonical_cardinality_by_category[item["category"]][item["cardinality"]] += 1
        if item["predicted_contains_full_source_copy"]:
            full_source_copy_by_category[item["category"]] += 1
            if item["surface_class"] != "exact_set":
                non_exact_source_copy_by_category[item["category"]] += 1

    relation_keys_by_repetition: dict[int, set[tuple[Any, ...]]] = defaultdict(set)
    predicted_items_by_repetition: dict[int, dict[tuple[str, int], tuple[str, ...]]] = (
        defaultdict(dict)
    )
    for item in relation_errors:
        relation_keys_by_repetition[item["repetition"]].add(
            (
                item["case_id"],
                item["expected_clause_index"],
                item["expected_relation"],
                item["predicted_relation"],
            )
        )
    for item in canonical_pairs:
        predicted_items_by_repetition[item["repetition"]][
            (item["case_id"], item["expected_clause_index"])
        ] = tuple(_canonical_text(value) for value in item["predicted_items"])

    repetitions = sorted(per_repetition)
    stable_relation_errors: set[tuple[Any, ...]] = set()
    stable_item_outputs = 0
    comparable_item_pairs = 0
    if len(repetitions) >= 2:
        stable_relation_errors = set.intersection(
            *(relation_keys_by_repetition[item] for item in repetitions)
        )
        common_item_keys = set.intersection(
            *(set(predicted_items_by_repetition[item]) for item in repetitions)
        )
        comparable_item_pairs = len(common_item_keys)
        stable_item_outputs = sum(
            len(
                {
                    predicted_items_by_repetition[repetition][key]
                    for repetition in repetitions
                }
            )
            == 1
            for key in common_item_keys
        )

    for item in relation_errors:
        item["stable_across_repetitions"] = (
            item["case_id"],
            item["expected_clause_index"],
            item["expected_relation"],
            item["predicted_relation"],
        ) in stable_relation_errors

    rendered_per_repetition = {
        str(repetition): {
            **stats,
            "relation_errors_by_type": dict(
                sorted(stats["relation_errors_by_type"].items())
            ),
            "canonical_surface_classes": dict(
                sorted(stats["canonical_surface_classes"].items())
            ),
            "canonical_cardinality": dict(
                sorted(stats["canonical_cardinality"].items())
            ),
        }
        for repetition, stats in sorted(per_repetition.items())
    }

    return {
        "analysis_version": "unified-jd-relation-canonical-analysis-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "compiler_version": UNIFIED_EXTRACTION_COMPILER_VERSION,
        "experiment_version": experiment.get("experiment_version"),
        "model_call_count": 0,
        "source_record_count": len(experiment["records"]),
        "per_repetition": rendered_per_repetition,
        "relation_summary": {
            "error_count": len(relation_errors),
            "substantive_error_count": sum(
                not item["shared_evidence_ambiguous"] for item in relation_errors
            ),
            "shared_evidence_alignment_ambiguity_count": sum(
                item["shared_evidence_ambiguous"] for item in relation_errors
            ),
            "by_category": dict(sorted(relation_by_category.items())),
            "by_type": dict(sorted(relation_by_type.items())),
            "by_causal_bucket": dict(sorted(relation_by_causal_bucket.items())),
            "stable_across_repetitions_count": len(stable_relation_errors),
            "stable_substantive_error_count": sum(
                item["stable_across_repetitions"]
                and not item["shared_evidence_ambiguous"]
                for item in relation_errors
            )
            // len(repetitions)
            if repetitions
            else 0,
        },
        "canonical_summary": {
            "pair_count": len(canonical_pairs),
            "compact_exact_set_count": sum(
                item["compact_exact_set"] for item in canonical_pairs
            ),
            "exact_item_count": sum(
                item["exact_item_count"] for item in canonical_pairs
            ),
            "compact_exact_item_count": sum(
                item["compact_exact_item_count"] for item in canonical_pairs
            ),
            "surface_classes": dict(
                sorted(
                    Counter(item["surface_class"] for item in canonical_pairs).items()
                )
            ),
            "surface_class_by_category": {
                category: dict(sorted(counts.items()))
                for category, counts in sorted(canonical_by_category.items())
            },
            "cardinality": dict(sorted(canonical_cardinality.items())),
            "cardinality_by_category": {
                category: dict(sorted(counts.items()))
                for category, counts in sorted(
                    canonical_cardinality_by_category.items()
                )
            },
            "full_source_copy_by_category": dict(
                sorted(full_source_copy_by_category.items())
            ),
            "non_exact_source_copy_by_category": dict(
                sorted(non_exact_source_copy_by_category.items())
            ),
            "cross_repetition_comparable_pair_count": comparable_item_pairs,
            "cross_repetition_identical_items_count": stable_item_outputs,
            "cross_repetition_identical_items_rate": (
                stable_item_outputs / comparable_item_pairs
                if comparable_item_pairs
                else None
            ),
        },
        "relation_errors": relation_errors,
        "canonical_pairs": canonical_pairs,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze relation and canonical-item errors from saved raw responses"
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--experiment", type=Path, default=DEFAULT_EXPERIMENT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    manifest = UnifiedEvaluationManifest.model_validate_json(
        arguments.manifest.read_text(encoding="utf-8")
    )
    experiment = json.loads(arguments.experiment.read_text(encoding="utf-8"))
    analysis = build_analysis(manifest, experiment)
    analysis["sources"] = {
        "manifest": {
            "path": arguments.manifest.as_posix(),
            "sha256": _sha256(arguments.manifest),
        },
        "experiment": {
            "path": arguments.experiment.as_posix(),
            "sha256": _sha256(arguments.experiment),
        },
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "offline relation/canonical analysis complete "
        f"records={analysis['source_record_count']} "
        f"relation_errors={analysis['relation_summary']['error_count']} "
        f"output={arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
