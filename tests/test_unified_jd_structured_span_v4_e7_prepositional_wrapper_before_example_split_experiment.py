from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARSER_PATH = PROJECT_ROOT / "src/domain/unified_jd_structured_spans_v4.py"
RULES_FREEZE_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_rules_freeze_v4_2026-09-04.json"
)
PREREGISTRATION_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_v4_residual_experiments_preregistration_v1-2026-09-04.json"
)
E5_RAW_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e5-example-attachment-three-toggle-raw-v1-2026-09-04.json"
)
RAW_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e7-prepositional-wrapper-before-example-split-raw-v1-2026-09-04.json"
)
REPORT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e7-prepositional-wrapper-before-example-split-report-v1-2026-09-04.json"
)
FINDINGS_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e7-prepositional-wrapper-before-example-split-findings-v1-2026-09-04.md"
)

PARSER_SHA256 = "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094"
RULES_FREEZE_SHA256 = (
    "6a8a1d9ccce7c1069a483c7cc387221164de52800a133308922d57ff75ad6a12"
)
PREREGISTRATION_SHA256 = (
    "7acfbed9a61ec39c16136604d58b19c8b562dfe43ff256cc789e4e8ff2fb708e"
)
RAW_SHA256 = "ec20fb2492e5e0c1c47e3986c977e1be363aa73543a68f128dbb6e57038b2555"
REPORT_SHA256 = "7f479267ecb26d67f474e2c31f11d28fa3748bca6b006a2820cf551a283c2717"
FINDINGS_SHA256 = "e5ee508886b4f8e67076b5175726d3bdb842095d2046e39834cbbfde00947203"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_e7_uses_an_independent_e5_baseline_without_e6() -> None:
    raw = _load(RAW_PATH)

    assert raw["status"] == "revealed_development_causal_experiment"
    assert raw["experiment_id"] == (
        "E7-prepositional-wrapper-before-example-split"
    )
    assert raw["arms"] == [
        "e5_final_baseline",
        "prepositional_wrapper_before_example_split",
    ]
    assert raw["preregistration_frozen_before_execution"] is True
    assert raw["cumulative_treatment"] is False
    assert raw["e6_output_loaded"] is False
    assert raw["e6_treatment_included"] is False
    assert raw["v4_full_parser_executed"] is False
    assert raw["v5_implemented"] is False
    assert raw["fixture_count"] == 6
    assert raw["model_call_count"] == 0
    assert raw["network_call_count"] == 0
    assert raw["frozen_v4_source"] == {
        "path": "src/domain/unified_jd_structured_spans_v4.py",
        "sha256_before": PARSER_SHA256,
        "sha256_after": PARSER_SHA256,
        "modified": False,
    }
    assert _sha256(PARSER_PATH) == PARSER_SHA256
    assert _sha256(RULES_FREEZE_PATH) == RULES_FREEZE_SHA256
    assert _sha256(PREREGISTRATION_PATH) == PREREGISTRATION_SHA256


def test_e7_reuses_stored_e5_final_and_reconstructs_only_control_009() -> None:
    raw = _load(RAW_PATH)
    e5_by_id = {item["id"]: item for item in _load(E5_RAW_PATH)["records"]}

    for record in raw["records"]:
        if record["id"] == "structured-corpus-external-v1-009":
            assert record["baseline_origin"] == (
                "reconstructed_e5_final_from_frozen_baseline"
            )
            assert record["e5_final_baseline"]["attachments"] == []
            continue
        assert record["baseline_origin"] == "stored_e5_final"
        assert record["e5_final_baseline"] == e5_by_id[record["id"]][
            "toggle3_parent_ranked"
        ]


def test_e7_changes_exactly_the_registered_019_boundary() -> None:
    raw = _load(RAW_PATH)
    records = {item["id"]: item for item in raw["records"]}
    target = records["structured-corpus-external-v1-019"]
    baseline = target["e5_final_baseline"]
    treatment = target["prepositional_wrapper_before_example_split"]

    assert baseline["example_members"][0] == {
        "text": "对大模型评测",
        "start": 17,
        "end": 23,
    }
    assert treatment["example_members"][0] == {
        "text": "大模型评测",
        "start": 18,
        "end": 23,
    }
    assert treatment["attachments"][0]["example_spans"][0] == {
        "text": "大模型评测",
        "start": 18,
        "end": 23,
    }
    assert treatment["attachments"][0]["example_spans"][1:] == baseline[
        "attachments"
    ][0]["example_spans"][1:]
    assert treatment["attachments"][0]["cue_span"] == baseline["attachments"][0][
        "cue_span"
    ]
    assert treatment["attachments"][0]["parent_span"] == baseline[
        "attachments"
    ][0]["parent_span"]
    assert target["wrapper_boundary_events"] == [
        {
            "wrapper_marker_span": {"text": "对", "start": 17, "end": 18},
            "before_split_span": {
                "text": "对大模型评测",
                "start": 17,
                "end": 23,
            },
            "after_split_span": {
                "text": "大模型评测",
                "start": 18,
                "end": 23,
            },
        }
    ]


def test_e7_controls_are_unchanged_and_006_proves_no_accumulation() -> None:
    raw = _load(RAW_PATH)
    records = {item["id"]: item for item in raw["records"]}

    for fixture_id in (
        "structured-corpus-external-v1-002",
        "structured-corpus-external-v1-005",
        "structured-corpus-external-v1-006",
        "structured-corpus-external-v1-009",
        "structured-corpus-external-v1-018",
    ):
        assert records[fixture_id][
            "prepositional_wrapper_before_example_split"
        ] == records[fixture_id]["e5_final_baseline"]

    assert len(
        records["structured-corpus-external-v1-006"]["e5_final_baseline"][
            "attachments"
        ]
    ) == 1
    assert records["structured-corpus-external-v1-009"]["source_text"].startswith(
        "对"
    )
    assert records["structured-corpus-external-v1-009"][
        "wrapper_boundary_events"
    ] == []


def test_e7_passes_all_four_frozen_criteria() -> None:
    report = _load(REPORT_PATH)
    decision = report["decision"]
    treatment = "prepositional_wrapper_before_example_split"
    target = report["aggregate"]["targets"][treatment]

    assert report["scope"]["one_time_frozen_gate_decision"] is True
    assert report["scope"]["e6_treatment_included"] is False
    assert report["independence"]["e6_output_loaded"] is False
    assert report["independence"][
        "control_006_false_attachment_remains_in_both_arms"
    ] is True
    assert decision["criterion_1_exact_17_23_to_18_23_only"] is True
    assert decision["criterion_2_target_members_projection_edges_exact"] is True
    assert decision["criterion_3_cue_and_parent_unchanged"] is True
    assert decision["criterion_4_all_controls_and_counts_unchanged"] is True
    assert all(decision["control_byte_equality"].values())
    assert all(decision["control_attachment_count_unchanged"].values())
    assert decision["accepted"] is True
    assert target["example_members"]["f1"] == 1.0
    assert target["attachment_edges"]["f1"] == 1.0
    assert target["example_projection"]["f1"] == 1.0


def test_e7_outputs_are_hash_pinned_and_do_not_claim_a_v5_rule() -> None:
    findings = FINDINGS_PATH.read_text(encoding="utf-8")

    assert _sha256(RAW_PATH) == RAW_SHA256
    assert _sha256(REPORT_PATH) == REPORT_SHA256
    assert _sha256(FINDINGS_PATH) == FINDINGS_SHA256
    assert "Decision: **accepted**" in findings
    assert "E6 output was not loaded" in findings
    assert "does not authorize v5 implementation" in findings
