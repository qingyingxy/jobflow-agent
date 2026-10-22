from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.evaluation.unified_models import UnifiedEvaluationManifest

DEFAULT_LABELS = Path("datasets/unified_jd_surface_holdout_labels_v1_2026-09-04.json")
DEFAULT_SELECTION = Path(
    "datasets/unified_jd_surface_holdout_selection_v1_2026-09-04.json"
)
DEFAULT_RULES_FREEZE = Path(
    "datasets/unified_jd_surface_rules_freeze_v1_2026-09-04.json"
)
DEFAULT_OUTPUT = Path(
    "datasets/unified_jd_surface_holdout_label_freeze_v1_2026-09-04.json"
)
FREEZE_VERSION = "unified-jd-surface-holdout-label-freeze-v1"
LABELS_VERSION = "unified-jd-surface-holdout-labels-v1"
LABEL_STATUS = "reviewed_pre_prediction_frozen"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_immutable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise FileExistsError(f"refusing to overwrite changed label freeze: {path}")
    path.write_text(content, encoding="utf-8")


def validate_labels(
    labels: dict[str, Any],
    selection: dict[str, Any],
    manifest: UnifiedEvaluationManifest,
    *,
    expected_labels_version: str = LABELS_VERSION,
) -> None:
    if labels["labels_version"] != expected_labels_version:
        raise ValueError("unexpected holdout labels version")
    if labels["status"] != LABEL_STATUS:
        raise ValueError("holdout labels must be frozen before prediction")
    if labels["prediction_status_at_labeling"] != "not_generated_or_viewed":
        raise ValueError("holdout labels were not declared prediction-independent")
    if labels["model_call_count"] != 0:
        raise ValueError("holdout surface labels must be created offline")

    label_fixtures = labels["fixtures"]
    selected_fixtures = selection["fixtures"]
    scope = labels["scope"]
    expected_categories = set(scope["categories"])
    if len(label_fixtures) != scope["fixture_count"]:
        raise ValueError("holdout label fixture count differs from its scope")
    if len({item["id"] for item in label_fixtures}) != len(label_fixtures):
        raise ValueError("holdout label fixture ids must be unique")
    if Counter(item["category"] for item in label_fixtures) != Counter(
        {category: scope["fixtures_per_category"] for category in expected_categories}
    ):
        raise ValueError("holdout labels are not category-balanced")
    if scope["unique_case_per_fixture"] and len(
        {item["case_id"] for item in label_fixtures}
    ) != len(label_fixtures):
        raise ValueError("holdout label cases must be unique")

    selected_by_id = {item["id"]: item for item in selected_fixtures}
    cases_by_id = {case.id: case for case in manifest.cases}
    if set(selected_by_id) != {item["id"] for item in label_fixtures}:
        raise ValueError("holdout labels do not cover the frozen selection exactly")

    for item in label_fixtures:
        selected = selected_by_id[item["id"]]
        for field in (
            "case_id",
            "clause_index",
            "category",
            "level",
            "source_text",
        ):
            if item[field] != selected[field]:
                raise ValueError(f"{item['id']} differs from selection field {field}")

        case = cases_by_id[item["case_id"]]
        if case.expected is None:
            raise ValueError(f"{item['case_id']} has no frozen expected clauses")
        clause = case.expected.clauses[item["clause_index"]]
        if (
            clause.source_text != item["source_text"]
            or clause.category != item["category"]
            or clause.level != item["level"]
        ):
            raise ValueError(f"{item['id']} does not match the frozen source clause")
        if item["source_text"] not in case.raw_content:
            raise ValueError(f"{item['id']} source_text is not in the original JD")

        surface_items = item["surface_items"]
        examples = item["examples"] or []
        if not surface_items:
            raise ValueError(f"{item['id']} has no surface items")
        if len(surface_items) != len({value.casefold() for value in surface_items}):
            raise ValueError(f"{item['id']} has duplicate surface items")
        if len(examples) != len({value.casefold() for value in examples}):
            raise ValueError(f"{item['id']} has duplicate examples")
        if {value.casefold() for value in surface_items} & {
            value.casefold() for value in examples
        }:
            raise ValueError(f"{item['id']} mixes surface items with examples")
        for value in [*surface_items, *examples]:
            if not value.strip() or value not in item["source_text"]:
                raise ValueError(f"{item['id']} has unanchored label value {value!r}")


def build_receipt(
    *,
    labels_path: Path,
    selection_path: Path,
    rules_freeze_path: Path,
) -> dict[str, Any]:
    labels: dict[str, Any] = json.loads(labels_path.read_text(encoding="utf-8"))
    selection: dict[str, Any] = json.loads(selection_path.read_text(encoding="utf-8"))
    rules_freeze: dict[str, Any] = json.loads(
        rules_freeze_path.read_text(encoding="utf-8")
    )

    if labels["selection"]["sha256"] != sha256(selection_path):
        raise ValueError("labels are not bound to the current frozen selection")
    if labels["selection"]["version"] != selection["selection_version"]:
        raise ValueError("labels and selection versions differ")
    contract_path = Path(labels["annotation_contract"]["path"])
    if labels["annotation_contract"]["sha256"] != sha256(contract_path):
        raise ValueError("annotation contract changed after labeling")
    if rules_freeze["status"] != "frozen":
        raise ValueError("surface rules are not frozen")
    rules_path = Path(rules_freeze["frozen_rules"]["path"])
    if rules_freeze["frozen_rules"]["sha256"] != sha256(rules_path):
        raise ValueError("surface rules changed after freeze")

    manifest_path = Path(selection["source_manifest"]["path"])
    if selection["source_manifest"]["sha256"] != sha256(manifest_path):
        raise ValueError("holdout source manifest changed after selection")
    manifest = UnifiedEvaluationManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    validate_labels(labels, selection, manifest)

    return {
        "freeze_version": FREEZE_VERSION,
        "status": "frozen",
        "frozen_at": "2026-09-04",
        "prediction_status": "not_generated_or_viewed",
        "model_call_count": 0,
        "files": {
            "labels": {
                "path": labels_path.as_posix(),
                "sha256": sha256(labels_path),
                "version": labels["labels_version"],
            },
            "selection": {
                "path": selection_path.as_posix(),
                "sha256": sha256(selection_path),
                "version": selection["selection_version"],
            },
            "rules_freeze": {
                "path": rules_freeze_path.as_posix(),
                "sha256": sha256(rules_freeze_path),
                "rules_sha256": rules_freeze["frozen_rules"]["sha256"],
                "extractor_version": rules_freeze["extractor_version"],
            },
            "annotation_contract": {
                "path": contract_path.as_posix(),
                "sha256": sha256(contract_path),
                "version": labels["contract_version"],
            },
            "source_manifest": {
                "path": manifest_path.as_posix(),
                "sha256": sha256(manifest_path),
                "version": selection["source_manifest"]["dataset_version"],
            },
        },
        "scope": labels["scope"],
        "gates": selection["protocol"]["gates"],
        "immutability_policy": (
            "Any labels or rules change requires new versioned files. The v1 holdout "
            "result must not be used to edit the frozen v1 labels or rules."
        ),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and freeze reviewed Unified JD surface holdout labels"
    )
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--rules-freeze", type=Path, default=DEFAULT_RULES_FREEZE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    receipt = build_receipt(
        labels_path=arguments.labels,
        selection_path=arguments.selection,
        rules_freeze_path=arguments.rules_freeze,
    )
    _write_immutable(
        arguments.output,
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
    )
    print(
        "surface holdout labels frozen "
        f"fixtures={receipt['scope']['fixture_count']} "
        f"output={arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
