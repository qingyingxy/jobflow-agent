from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.freeze_unified_surface_holdout_labels import (
    LABEL_STATUS,
    sha256,
    validate_labels,
)
from src.evaluation.unified_models import UnifiedEvaluationManifest

DEFAULT_LABELS = Path("datasets/unified_jd_surface_holdout_labels_v2_2026-09-04.json")
DEFAULT_SELECTION = Path(
    "datasets/unified_jd_surface_holdout_selection_v2_2026-09-04.json"
)
DEFAULT_RULES_FREEZE = Path(
    "datasets/unified_jd_surface_rules_freeze_v2_2026-09-04.json"
)
DEFAULT_OUTPUT = Path(
    "datasets/unified_jd_surface_holdout_label_freeze_v2_2026-09-04.json"
)
FREEZE_VERSION = "unified-jd-surface-holdout-label-freeze-v2"
LABELS_VERSION = "unified-jd-surface-holdout-labels-v2"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_immutable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise FileExistsError(f"refusing to overwrite changed v2 label freeze: {path}")
    path.write_text(content, encoding="utf-8")


def build_receipt(
    *,
    labels_path: Path,
    selection_path: Path,
    rules_freeze_path: Path,
) -> dict[str, Any]:
    labels = _load(labels_path)
    selection = _load(selection_path)
    rules_freeze = _load(rules_freeze_path)

    if labels["status"] != LABEL_STATUS:
        raise ValueError("v2 holdout labels must be frozen before prediction")
    if labels["selection"]["sha256"] != sha256(selection_path):
        raise ValueError("v2 labels are not bound to the current frozen selection")
    if labels["selection"]["version"] != selection["selection_version"]:
        raise ValueError("v2 labels and selection versions differ")
    contract_path = Path(labels["annotation_contract"]["path"])
    if labels["annotation_contract"]["sha256"] != sha256(contract_path):
        raise ValueError("annotation contract changed after v2 labeling")
    if rules_freeze["status"] != "frozen":
        raise ValueError("v2 surface rules are not frozen")
    rules_path = Path(rules_freeze["frozen_rules"]["path"])
    if rules_freeze["frozen_rules"]["sha256"] != sha256(rules_path):
        raise ValueError("v2 surface rules changed after freeze")

    manifest_path = Path(selection["source_manifest"]["path"])
    if selection["source_manifest"]["sha256"] != sha256(manifest_path):
        raise ValueError("v2 holdout source manifest changed after selection")
    manifest = UnifiedEvaluationManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    validate_labels(
        labels,
        selection,
        manifest,
        expected_labels_version=LABELS_VERSION,
    )

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
            "Any v2 labels or rules change requires new versioned files. The v2 "
            "holdout result must not be used to edit these frozen inputs."
        ),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate and freeze reviewed v2 surface holdout labels"
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
        "v2 surface holdout labels frozen "
        f"fixtures={receipt['scope']['fixture_count']} "
        f"output={arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
