from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PARSER_PATH = PROJECT_ROOT / "src/domain/unified_jd_structured_spans_v4.py"
RULE_FREEZE_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_rules_freeze_v4_2026-09-04.json"
)
SOURCES_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_v4_corpus_external_sources_v1_2026-09-04.json"
)
SELECTION_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_v4_corpus_external_selection_v1_2026-09-04.json"
)
LABELS_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_v4_corpus_external_labels_v1_2026-09-04.json"
)
LABEL_FREEZE_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_v4_corpus_external_label_freeze_v1_2026-09-04.json"
)
RAW_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-corpus-external-raw-v1-2026-09-04.json"
)
REPORT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-corpus-external-report-v1-2026-09-04.json"
)
FINDINGS_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-corpus-external-findings-v1-2026-09-04.md"
)
EVALUATION_RECEIPT_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_v4_corpus_external_evaluation_receipt_v1_2026-09-04.json"
)

OUTPUT_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_v4_corpus_external_revealed_development_v1_2026-09-04.json"
)
REVEAL_RECEIPT_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_v4_corpus_external_reveal_receipt_v1_2026-09-04.json"
)

EXPECTED_INPUT_HASHES = {
    PARSER_PATH: "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094",
    RULE_FREEZE_PATH: "6a8a1d9ccce7c1069a483c7cc387221164de52800a133308922d57ff75ad6a12",
    SOURCES_PATH: "1e693bd69642511ffa005b2bc33489b68a4a1ef99abb3c65b8615862c0eb5b29",
    SELECTION_PATH: "3061f49377ef937325743c1e1afc14e9651215f36dfad6b8c02771bd99b5661a",
    LABELS_PATH: "64823eb502b5219254a0376808a234e056b2964fe85cd00c30d898b821a79b54",
    LABEL_FREEZE_PATH: "c2e08912e26dcfa693959b25a4d4bcf6e357a55995c056cd245ca6fb9ebe599d",
    RAW_PATH: "36b65c1df79d856c7507ae1357ed24c10b7a3e383bad79b9471b124f4999e058",
    REPORT_PATH: "5a0d53f1d55f7d62c52506c907b2231826f1f2753f653bb97880e1e7ac373dfc",
    FINDINGS_PATH: "282c793f8fdac6675906893391a91169950f0f146a6a7f8a23117265f5ad7055",
    EVALUATION_RECEIPT_PATH: (
        "6d361f769b3468ee31780f00ad24027a67b770099cb8ba21fa39dbada700f792"
    ),
}

DIFFERENCE_LAYERS = (
    "wrappers",
    "coordination_members",
    "shared_scope_edges",
    "example_attachment_parents",
    "example_attachment_edges",
    "surface_projection",
    "example_projection",
)

ELIGIBLE_FOR = ["v5_diagnosis", "v5_development"]
INELIGIBLE_FOR = [
    "v4_retest",
    "v5_holdout",
    "future_holdout",
    "generalization_claim",
    "threshold_selection",
]


def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _index_unique(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    indexed = {record[key]: record for record in records}
    if len(indexed) != len(records):
        raise ValueError(f"duplicate {key} in {len(records)} records")
    return indexed


def _assert_span(span: dict[str, Any], source: str, context: str) -> None:
    if source[span["start"] : span["end"]] != span["text"]:
        raise ValueError(f"unanchored span in {context}: {span!r}")


def _assert_all_spans(value: Any, source: str, context: str) -> None:
    if isinstance(value, dict):
        if {"text", "start", "end"} <= value.keys():
            _assert_span(value, source, context)
        for child in value.values():
            _assert_all_spans(child, source, context)
    elif isinstance(value, list):
        for child in value:
            _assert_all_spans(child, source, context)


def _assert_frozen_inputs() -> None:
    changed = {
        _relative(path): {"expected": expected, "actual": _sha256(path)}
        for path, expected in EXPECTED_INPUT_HASHES.items()
        if _sha256(path) != expected
    }
    if changed:
        raise ValueError(f"frozen inputs changed: {changed}")


def _source_artifacts() -> dict[str, dict[str, str]]:
    names = {
        "parser": PARSER_PATH,
        "rules_freeze": RULE_FREEZE_PATH,
        "source_corpus": SOURCES_PATH,
        "selection": SELECTION_PATH,
        "gold_labels": LABELS_PATH,
        "label_freeze": LABEL_FREEZE_PATH,
        "raw_predictions": RAW_PATH,
        "evaluation_report": REPORT_PATH,
        "evaluation_findings": FINDINGS_PATH,
        "evaluation_receipt": EVALUATION_RECEIPT_PATH,
    }
    return {
        name: {"path": _relative(path), "sha256": EXPECTED_INPUT_HASHES[path]}
        for name, path in names.items()
    }


def _validate_and_merge() -> list[dict[str, Any]]:
    sources = _load(SOURCES_PATH)
    selection = _load(SELECTION_PATH)
    labels = _load(LABELS_PATH)
    raw = _load(RAW_PATH)
    report = _load(REPORT_PATH)

    source_by_id = _index_unique(sources["jobs"], "job_id")
    selection_by_id = _index_unique(selection["fixtures"], "id")
    label_by_id = _index_unique(labels["fixtures"], "id")
    raw_by_id = _index_unique(raw["records"], "id")
    report_by_id = _index_unique(report["records"], "id")

    fixture_ids = set(label_by_id)
    for name, indexed in (
        ("selection", selection_by_id),
        ("raw predictions", raw_by_id),
        ("evaluation report", report_by_id),
    ):
        if set(indexed) != fixture_ids:
            raise ValueError(f"{name} fixture IDs do not match gold labels")
    if len(fixture_ids) != 20 or len(source_by_id) != 20:
        raise ValueError("revealed development data must contain 20 unique jobs")

    fixtures: list[dict[str, Any]] = []
    for fixture_id in label_by_id:
        selected = selection_by_id[fixture_id]
        gold = label_by_id[fixture_id]
        prediction = raw_by_id[fixture_id]
        evaluation = report_by_id[fixture_id]
        source_job = source_by_id[selected["job_id"]]
        context = f"fixture {fixture_id}"

        if any(
            record["job_id"] != selected["job_id"]
            for record in (gold, prediction, evaluation)
        ):
            raise ValueError(f"job ID mismatch in {context}")
        if any(
            record["category"] != selected["category"]
            for record in (gold, prediction, evaluation)
        ):
            raise ValueError(f"category mismatch in {context}")
        if gold["source_text"] != selected["source_text"]:
            raise ValueError(f"gold source text mismatch in {context}")
        if prediction["source_text"] != selected["source_text"]:
            raise ValueError(f"prediction source text mismatch in {context}")
        if prediction["error"] is not None or evaluation["error"] is not None:
            raise ValueError(f"unexpected v4 execution error in {context}")

        section_text = source_job[selected["source_section"]]
        _assert_span(selected["clause_span_in_section"], section_text, context)
        _assert_span(
            selected["clause_span_in_raw_content"],
            source_job["raw_content"],
            context,
        )
        if selected["clause_span_in_section"]["text"] != selected["source_text"]:
            raise ValueError(f"selected section clause mismatch in {context}")
        if selected["clause_span_in_raw_content"]["text"] != selected["source_text"]:
            raise ValueError(f"selected raw-content clause mismatch in {context}")
        if _text_sha256(source_job["raw_content"]) != source_job["raw_content_sha256"]:
            raise ValueError(f"full job text hash mismatch in {context}")
        if source_job["raw_content_sha256"] != selected["raw_content_sha256"]:
            raise ValueError(f"selection provenance hash mismatch in {context}")
        if len(source_job["raw_content"]) != source_job["raw_content_length"]:
            raise ValueError(f"full job text length mismatch in {context}")

        _assert_all_spans(gold, gold["source_text"], f"{context} gold")
        _assert_all_spans(
            prediction["parsed_clause"],
            prediction["source_text"],
            f"{context} prediction",
        )

        differences = {
            layer: evaluation[layer] for layer in DIFFERENCE_LAYERS
        }
        for layer, result in differences.items():
            expected_exact = not result["missing"] and not result["unexpected"]
            if result["exact"] is not expected_exact:
                raise ValueError(f"inconsistent {layer} differences in {context}")

        fixtures.append(
            {
                "id": fixture_id,
                "job_id": selected["job_id"],
                "category": selected["category"],
                "development_status": "revealed_after_v4_single_use_evaluation",
                "job_provenance": source_job,
                "selected_clause": selected,
                "gold": gold,
                "v4_prediction": prediction,
                "evaluation_differences": differences,
                "connector_classification": evaluation["connector_classification"],
            }
        )

    if len({fixture["job_id"] for fixture in fixtures}) != 20:
        raise ValueError("each revealed fixture must come from a unique job")
    return fixtures


def _build_dataset(fixtures: list[dict[str, Any]]) -> dict[str, Any]:
    report = _load(REPORT_PATH)
    category_counts = dict(sorted(Counter(x["category"] for x in fixtures).items()))
    return {
        "dataset_version": (
            "unified-jd-structured-span-v4-corpus-external-"
            "revealed-development-v1"
        ),
        "created_at": "2026-09-04",
        "status": "revealed_corpus_external_development_only",
        "former_holdout_status": "consumed_single_use_failed_gate",
        "reveal_reason": (
            "The frozen v4 parser failed the one-time external holdout gate. "
            "Gold labels and per-layer errors are now visible."
        ),
        "usage_policy": {
            "eligible_for": ELIGIBLE_FOR,
            "ineligible_for": INELIGIBLE_FOR,
            "generalization_claim": False,
            "holdout_reuse_prohibited": True,
        },
        "v4_baseline": {
            "parser_version": report["parser_version"],
            "parser_sha256": report["parser_sha256"],
            "run_count_on_former_holdout": 1,
            "gate_passed": False,
            "canonicalizer_allowed": False,
            "metrics": {
                "connector_classification_accuracy": report[
                    "connector_classification"
                ]["overall"]["accuracy"],
                "coordination_member_f1": report["coordination_members"][
                    "overall"
                ]["f1"],
                "shared_scope_edge_f1": report["shared_scope_edges"]["overall"][
                    "f1"
                ],
                "example_attachment_edge_f1": report[
                    "example_attachment_edges"
                ]["overall"]["f1"],
                "surface_projection_f1": report["surface_projection"]["overall"][
                    "f1"
                ],
                "surface_projection_exact_rate": report["surface_projection"][
                    "overall"
                ]["exact_fixture_rate"],
            },
        },
        "source_artifacts": _source_artifacts(),
        "fixture_count": len(fixtures),
        "unique_job_count": len({fixture["job_id"] for fixture in fixtures}),
        "category_counts": category_counts,
        "fixtures": fixtures,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _build_receipt() -> dict[str, Any]:
    return {
        "receipt_version": (
            "unified-jd-structured-span-v4-corpus-external-reveal-receipt-v1"
        ),
        "revealed_at": "2026-09-04",
        "status": "revealed_corpus_external_development_only",
        "former_holdout_status": "consumed_single_use_failed_gate",
        "revealed_development": {
            "path": _relative(OUTPUT_PATH),
            "sha256": _sha256(OUTPUT_PATH),
            "fixture_count": 20,
            "unique_job_count": 20,
        },
        "source_artifacts": _source_artifacts(),
        "frozen_v4_assurance": {
            "parser_modified": False,
            "rules_freeze_modified": False,
            "parser_imported_or_executed_during_reveal": False,
            "additional_v4_runs_on_former_holdout": 0,
            "total_v4_runs_on_former_holdout": 1,
        },
        "usage_policy": {
            "eligible_for": ELIGIBLE_FOR,
            "ineligible_for": INELIGIBLE_FOR,
            "generalization_claim": False,
            "holdout_reuse_prohibited": True,
            "next_valid_generalization_test": (
                "A newly collected and frozen corpus-external holdout that excludes "
                "these 20 jobs and is not inspected during v5 development."
            ),
        },
        "conversion": {
            "builder_path": _relative(Path(__file__).resolve()),
            "builder_sha256": _sha256(Path(__file__).resolve()),
            "model_call_count": 0,
            "network_call_count": 0,
        },
    }


def main() -> int:
    _assert_frozen_inputs()
    fixtures = _validate_and_merge()
    _write_json(OUTPUT_PATH, _build_dataset(fixtures))
    _write_json(REVEAL_RECEIPT_PATH, _build_receipt())
    print(f"wrote {_relative(OUTPUT_PATH)}")
    print(f"wrote {_relative(REVEAL_RECEIPT_PATH)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
