from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.evaluate_unified_surface_holdout import build_holdout_report
from scripts.freeze_unified_surface_holdout_labels import (
    LABEL_STATUS,
    LABELS_VERSION,
    validate_labels,
)
from src.evaluation.unified_models import UnifiedEvaluationManifest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LABELS_PATH = (
    PROJECT_ROOT / "datasets" / "unified_jd_surface_holdout_labels_v1_2026-09-04.json"
)
SELECTION_PATH = (
    PROJECT_ROOT
    / "datasets"
    / "unified_jd_surface_holdout_selection_v1_2026-09-04.json"
)
FREEZE_PATH = (
    PROJECT_ROOT
    / "datasets"
    / "unified_jd_surface_holdout_label_freeze_v1_2026-09-04.json"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_surface_holdout_labels_are_balanced_anchored_and_selection_bound() -> None:
    labels = _load(LABELS_PATH)
    selection = _load(SELECTION_PATH)
    manifest_path = PROJECT_ROOT / selection["source_manifest"]["path"]
    manifest = UnifiedEvaluationManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )

    assert labels["labels_version"] == LABELS_VERSION
    assert labels["status"] == LABEL_STATUS
    assert labels["prediction_status_at_labeling"] == "not_generated_or_viewed"
    assert labels["model_call_count"] == 0
    assert (
        labels["selection"]["sha256"]
        == hashlib.sha256(SELECTION_PATH.read_bytes()).hexdigest()
    )
    assert Counter(item["category"] for item in labels["fixtures"]) == Counter(
        {"responsibility": 5, "skill": 5, "experience": 5, "capability": 5}
    )
    validate_labels(labels, selection, manifest)


def test_surface_holdout_label_freeze_hashes_all_inputs() -> None:
    freeze = _load(FREEZE_PATH)

    assert freeze["status"] == "frozen"
    assert freeze["prediction_status"] == "not_generated_or_viewed"
    assert freeze["model_call_count"] == 0
    assert freeze["scope"]["fixture_count"] == 20
    for frozen_file in freeze["files"].values():
        path = PROJECT_ROOT / frozen_file["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == frozen_file["sha256"]


def test_surface_holdout_replay_is_offline_and_uses_frozen_provenance() -> None:
    report = build_holdout_report(FREEZE_PATH)

    assert report["report_version"] == "unified-jd-surface-holdout-evaluation-v1"
    assert report["model_call_count"] == 0
    assert report["evaluation_scope"]["type"] == ("frozen_independent_surface_holdout")
    assert report["evaluation_scope"]["generalization_claim"] is True
    assert report["evaluation_scope"]["production_wiring"] is False
    assert report["surface_items"]["overall"]["comparison_count"] == 20
    assert report["examples"]["overall"]["comparison_count"] == 20
    assert report["unanchored_outputs"]["count"] == 0
    assert report["failure_analysis"]["rules_changed"] is False
    assert report["failure_analysis"]["labels_changed"] is False
    assert len(report["failure_analysis"]["root_cause_clusters"]) == 5
    assert report["decision"] in {
        "surface_gate_passed_canonicalizer_may_start",
        "surface_gate_failed_stop_before_canonicalizer",
    }
