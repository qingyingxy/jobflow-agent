from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
LABELS_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_mechanism_development_labels_v1_2026-09-04.json"
)
LABEL_FREEZE_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_mechanism_development_label_freeze_v1_2026-09-04.json"
)
BASELINE_RAW_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "unified-jd-structured-span-v5-mechanism-development-v4-baseline-raw-v1-2026-09-04.json"
)
BASELINE_REPORT_PATH = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "unified-jd-structured-span-v5-mechanism-development-v4-baseline-report-v1-2026-09-04.json"
)
PREREGISTRATION_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_preregistration_v1_2026-09-04.json"
)
PREREGISTRATION_FREEZE_PATH = (
    ROOT
    / "datasets"
    / "unified_jd_structured_span_v5_preregistration_freeze_v1_2026-09-04.json"
)
V4_PATH = ROOT / "src" / "domain" / "unified_jd_structured_spans_v4.py"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v4_baseline_was_run_only_after_label_freeze() -> None:
    label_freeze = load(LABEL_FREEZE_PATH)
    raw = load(BASELINE_RAW_PATH)
    report = load(BASELINE_REPORT_PATH)

    assert label_freeze["artifacts"]["labels"]["sha256"] == sha256(LABELS_PATH)
    assert raw["status"] == "post_label_freeze_revealed_development_baseline"
    assert raw["label_freeze_sha256"] == sha256(LABEL_FREEZE_PATH)
    assert raw["gold_sha256"] == sha256(LABELS_PATH)
    assert len(raw["records"]) == 20
    assert raw["model_call_count"] == raw["network_call_count"] == 0
    assert raw["v4_modified"] is False
    assert raw["v4_source_sha256_before"] == raw["v4_source_sha256_after"]
    assert raw["v4_source_sha256_after"] == sha256(V4_PATH)

    assert report["status"] == "frozen_baseline_for_v5_preregistration"
    assert report["inputs"]["raw"]["sha256"] == sha256(BASELINE_RAW_PATH)
    assert report["scope"]["generalization_claim"] is False
    assert report["scope"]["threshold_selection_allowed_after_this_report"] is False


def test_frozen_baseline_metrics_are_layer_separated() -> None:
    metrics = load(BASELINE_REPORT_PATH)["baseline_metrics"]
    assert metrics["fixture_count"] == 20
    assert metrics["structure_validation_error_count"] == 0
    assert metrics["wrapper_span_f1"] == pytest.approx(0.46846846846846846)
    assert metrics["connector_classification_accuracy"] == pytest.approx(
        0.3617021276595745
    )
    assert metrics["coordination_member_f1"] == pytest.approx(0.2570281124497992)
    assert metrics["shared_scope_edge_f1"] == 0.0
    assert metrics["example_attachment_parent_f1"] == pytest.approx(
        0.058823529411764705
    )
    assert metrics["example_attachment_edge_f1"] == pytest.approx(
        0.03669724770642202
    )
    assert metrics["surface_projection_f1"] == pytest.approx(0.3017241379310345)
    assert metrics["example_projection_f1"] == pytest.approx(0.44036697247706424)
    assert load(BASELINE_REPORT_PATH)["unanchored_output_count"] == 0


def test_preregistered_pipeline_uses_only_supported_mechanisms() -> None:
    plan = load(PREREGISTRATION_PATH)
    retained = {
        item["id"] for item in plan["causal_basis"]["retained_mechanisms"]
    }
    excluded = {
        item["id"] for item in plan["causal_basis"]["excluded_mechanisms"]
    }
    assert retained == {
        "E2-wrapper-boundary",
        "E3-region-first-connector-role",
        "E6-priority-tail-rejection",
        "E7-prepositional-wrapper-before-example-split",
    }
    assert excluded == {
        "E1-category-neutral-dispatch",
        "E4-scope-candidate-versus-application",
        "E5-example-attachment-three-toggle",
    }

    stages = plan["combined_v5_rule"]["ordered_stages"]
    assert [stage["order"] for stage in stages] == list(range(1, 9))
    assert [stage["name"] for stage in stages] == [
        "protect_and_segment",
        "resolve_wrapper_boundaries",
        "form_attachment_regions",
        "reject_preference_only_postposed_parent",
        "exclude_local_prepositional_wrapper",
        "classify_connectors_by_innermost_region",
        "construct_members_and_explicit_scopes",
        "project_from_graph",
    ]
    assert "independent explicit 如" in stages[3]["rule"]
    assert "Never strip 对 globally" in stages[4]["rule"]
    assert "rejected E4" in stages[6]["e4_exclusion"]


def test_preregistered_thresholds_equal_frozen_baseline_and_are_conjunctive() -> None:
    plan = load(PREREGISTRATION_PATH)
    baseline = load(BASELINE_REPORT_PATH)
    aggregate = baseline["baseline_metrics"]
    gates = plan["development_acceptance_gates"]

    assert plan["evaluation_protocol"]["all_criteria_conjunctive"] is True
    assert (
        plan["evaluation_protocol"][
            "post_hoc_threshold_or_exception_changes_forbidden"
        ]
        is True
    )
    assert gates["G1-aggregate-non-regression"] == {
        "wrapper_span_f1_min": aggregate["wrapper_span_f1"],
        "connector_classification_accuracy_min": aggregate[
            "connector_classification_accuracy"
        ],
        "coordination_member_f1_min": aggregate["coordination_member_f1"],
        "shared_scope_edge_f1_min": aggregate["shared_scope_edge_f1"],
        "example_attachment_parent_f1_min": aggregate[
            "example_attachment_parent_f1"
        ],
        "example_attachment_edge_f1_min": aggregate[
            "example_attachment_edge_f1"
        ],
        "surface_projection_f1_min": aggregate["surface_projection_f1"],
        "example_projection_f1_min": aggregate["example_projection_f1"],
    }
    assert gates["G2-E2-wrapper-boundary"]["required_improved_fixture_count"] == 3
    assert (
        gates["G3-E3-region-first-connector-role"][
            "required_improved_fixture_count"
        ]
        == 4
    )


def test_e6_e7_and_regression_boundaries_are_explicit() -> None:
    plan = load(PREREGISTRATION_PATH)
    gates = plan["development_acceptance_gates"]
    e6 = gates["G4-E6-priority-tail"]
    e7 = gates["G5-E7-prepositional-boundary"]

    assert any("only attachment is cue 如" in item for item in e6["target_011"])
    assert any("attachment count == 0" in item for item in e6["target_012"])
    assert "matched_controls_013_015" in e6
    assert e7["first_example_spans"] == {
        "structured-v5-mechanism-dev-v1-016": "人机交互",
        "structured-v5-mechanism-dev-v1-017": "商业分析",
        "structured-v5-mechanism-dev-v1-018": "供应链计划",
        "structured-v5-mechanism-dev-v1-019": "系统分层",
        "structured-v5-mechanism-dev-v1-020": "外呼的销售策略",
    }
    assert any("none starts with 对" in item for item in e7["requirements"])

    regression = gates["G6-regression"]
    assert len(regression) == 4
    assert any("legacy v4 development gold" in item for item in regression)
    assert any("revealed corpus-external" in item for item in regression)
    assert any("60/60" in item for item in regression)
    assert plan["post_development_protocol"][
        "canonicalizer_unlock_condition"
    ].startswith("Only a one-time pass")


def test_preregistration_freeze_hashes_match() -> None:
    plan = load(PREREGISTRATION_PATH)
    freeze = load(PREREGISTRATION_FREEZE_PATH)

    assert plan["status"] == "frozen_before_v5_implementation"
    assert freeze["status"] == "frozen_before_v5_implementation"
    assert freeze["artifacts"]["preregistration"]["sha256"] == sha256(
        PREREGISTRATION_PATH
    )
    assert freeze["artifacts"]["frozen_v4_parser"]["sha256"] == sha256(V4_PATH)
    assert freeze["checks"]["only_e2_e3_e6_e7_retained"] is True
    assert freeze["checks"]["e1_e4_e5_excluded"] is True
    assert freeze["checks"]["canonicalizer_existed_at_freeze"] is False
    assert freeze["checks"]["model_call_count"] == 0
