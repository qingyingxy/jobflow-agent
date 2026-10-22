from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.evaluate_unified_surface_holdout_v2 import build_v2_holdout_report
from scripts.freeze_unified_surface_holdout_labels import validate_labels
from src.evaluation.unified_models import UnifiedEvaluationManifest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LABELS_PATH = (
    PROJECT_ROOT / "datasets" / "unified_jd_surface_holdout_labels_v2_2026-09-04.json"
)
SELECTION_PATH = (
    PROJECT_ROOT
    / "datasets"
    / "unified_jd_surface_holdout_selection_v2_2026-09-04.json"
)
FREEZE_PATH = (
    PROJECT_ROOT
    / "datasets"
    / "unified_jd_surface_holdout_label_freeze_v2_2026-09-04.json"
)
RULES_FREEZE_PATH = (
    PROJECT_ROOT / "datasets" / "unified_jd_surface_rules_freeze_v2_2026-09-04.json"
)
DEVELOPMENT_PATH = (
    PROJECT_ROOT / "datasets" / "unified_jd_surface_v2_development_v1_2026-09-04.json"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_v2_surface_holdout_labels_are_frozen_and_selection_bound() -> None:
    labels = _load(LABELS_PATH)
    selection = _load(SELECTION_PATH)
    manifest_path = PROJECT_ROOT / selection["source_manifest"]["path"]
    manifest = UnifiedEvaluationManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )

    assert labels["labels_version"] == "unified-jd-surface-holdout-labels-v2"
    assert labels["prediction_status_at_labeling"] == "not_generated_or_viewed"
    assert (
        labels["selection"]["sha256"]
        == hashlib.sha256(SELECTION_PATH.read_bytes()).hexdigest()
    )
    assert Counter(item["category"] for item in labels["fixtures"]) == Counter(
        {"responsibility": 5, "skill": 5, "experience": 5, "capability": 5}
    )
    validate_labels(
        labels,
        selection,
        manifest,
        expected_labels_version="unified-jd-surface-holdout-labels-v2",
    )


def test_v2_surface_holdout_freeze_hashes_all_inputs() -> None:
    freeze = _load(FREEZE_PATH)

    assert freeze["status"] == "frozen"
    assert freeze["prediction_status"] == "not_generated_or_viewed"
    assert freeze["model_call_count"] == 0
    for frozen_file in freeze["files"].values():
        path = PROJECT_ROOT / frozen_file["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == frozen_file["sha256"]


def test_v2_rules_freeze_binds_revealed_development_and_new_holdout() -> None:
    rules_freeze = _load(RULES_FREEZE_PATH)
    development = _load(DEVELOPMENT_PATH)
    selection = _load(SELECTION_PATH)

    assert rules_freeze["status"] == "frozen"
    assert rules_freeze["development_fixture"]["fixture_count"] == 40
    assert development["status"] == "development_only_revealed"
    assert len(development["scope"]["case_ids"]) == 25
    assert set(development["scope"]["case_ids"]) == set(
        selection["excluded_development_case_ids"]
    )
    assert not set(development["scope"]["case_ids"]) & set(
        selection["selected_case_ids"]
    )
    assert selection["assignment_method"].startswith(
        "deterministic maximum bipartite matching"
    )
    for name in ("frozen_rules", "contract", "development_fixture"):
        frozen_file = rules_freeze[name]
        path = PROJECT_ROOT / frozen_file["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == frozen_file["sha256"]


def test_v2_surface_holdout_replay_uses_frozen_offline_inputs() -> None:
    report = build_v2_holdout_report(FREEZE_PATH)

    assert report["report_version"] == "unified-jd-surface-holdout-evaluation-v2"
    assert report["model_call_count"] == 0
    assert report["evaluation_scope"]["type"] == ("frozen_independent_surface_holdout")
    assert report["evaluation_scope"]["generalization_claim"] is True
    assert report["surface_items"]["overall"]["comparison_count"] == 20
    assert report["examples"]["overall"]["comparison_count"] == 20
    assert report["unanchored_outputs"]["count"] == 0
    assert report["surface_items"]["overall"]["f1"] == 0.4748201438848921
    assert report["surface_items"]["overall"]["exact_set_rate"] == 0.15
    assert report["examples"]["overall"]["f1"] == 0.4
    assert report["gate"]["passed"] is False
    assert report["decision"] == "surface_gate_failed_stop_before_canonicalizer"
