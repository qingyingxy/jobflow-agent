from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.build_unified_structured_span_v4_e1_e5_synthesis_preregistration import (
    build_artifacts,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARSER_PATH = PROJECT_ROOT / "src/domain/unified_jd_structured_spans_v4.py"
RULES_FREEZE_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_rules_freeze_v4_2026-09-04.json"
)
SYNTHESIS_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e1-e5-synthesis-v1-2026-09-04.json"
)
FINDINGS_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e1-e5-synthesis-findings-v1-2026-09-04.md"
)
PREREGISTRATION_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_v4_residual_experiments_preregistration_v1-2026-09-04.json"
)

PARSER_SHA256 = "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094"
RULES_FREEZE_SHA256 = (
    "6a8a1d9ccce7c1069a483c7cc387221164de52800a133308922d57ff75ad6a12"
)
SYNTHESIS_SHA256 = "d7206f33d1af47d84f989aeea11a32b05972a609fefe3604879d8e13b389e073"
FINDINGS_SHA256 = "703ee252d901fa4fb1072c443d3c2bb5ee3ff0f5a9ff3dbbbdcafad2705b1d89"
PREREGISTRATION_SHA256 = (
    "7acfbed9a61ec39c16136604d58b19c8b562dfe43ff256cc789e4e8ff2fb708e"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_synthesis_retains_only_e2_and_e3() -> None:
    synthesis = _load(SYNTHESIS_PATH)
    decisions = {
        item["experiment_id"]: item["decision"]
        for item in synthesis["experiment_summary"]
    }

    assert synthesis["scope"]["status"] == "revealed_development_causal_synthesis"
    assert synthesis["scope"]["generalization_claim"] is False
    assert synthesis["scope"]["v5_implemented"] is False
    assert synthesis["scope"]["model_call_count"] == 0
    assert synthesis["scope"]["network_call_count"] == 0
    assert [
        item["experiment_id"] for item in synthesis["retained_mechanisms"]
    ] == [
        "E2-wrapper-boundary-oracle",
        "E3-region-first-connector-role-oracle",
    ]
    assert decisions == {
        "E1-dispatch-only": "rejected",
        "E2-wrapper-boundary-oracle": "accepted",
        "E3-region-first-connector-role-oracle": "accepted",
        "E4-scope-candidate-versus-application": "rejected",
        "E5-example-attachment-three-toggle": "rejected",
    }
    assert {
        item["experiment_id"] for item in synthesis["rejected_mechanisms"]
    } == {
        "E1-dispatch-only",
        "E4-scope-candidate-versus-application",
        "E5-example-attachment-three-toggle",
    }


def test_e6_is_a_single_case_priority_tail_experiment() -> None:
    preregistration = _load(PREREGISTRATION_PATH)
    e6 = next(
        item
        for item in preregistration["experiments"]
        if item["id"] == "E6-priority-tail-rejection"
    )

    assert e6["status"] == "preregistered_not_executed"
    assert e6["single_changed_variable"] == "priority_tail_attachment_eligibility"
    assert e6["target_fixture_ids"] == ["structured-corpus-external-v1-006"]
    assert e6["control_fixture_ids"] == [
        "structured-corpus-external-v1-002",
        "structured-corpus-external-v1-005",
        "structured-corpus-external-v1-019",
        "structured-corpus-external-v1-018",
    ]
    assert e6["baseline"]["target_observation"]["cue_span"] == {
        "text": "等",
        "start": 32,
        "end": 33,
    }
    assert e6["baseline"]["target_observation"]["right_tail_span"] == {
        "text": "优先",
        "start": 33,
        "end": 35,
    }
    assert e6["acceptance_gate"] == "accept_only_if_all_four_criteria_pass"
    assert len(e6["acceptance_criteria"]) == 4
    assert "single-case revealed-development causality" in e6["interpretation_limit"]


def test_e7_is_independent_and_changes_only_the_019_leading_boundary() -> None:
    preregistration = _load(PREREGISTRATION_PATH)
    guards = preregistration["global_guards"]
    e7 = next(
        item
        for item in preregistration["experiments"]
        if item["id"] == "E7-prepositional-wrapper-before-example-split"
    )
    observation = e7["baseline"]["target_observation"]

    assert guards["experiments_are_independent"] is True
    assert guards["e7_must_not_include_e6_treatment"] is True
    assert "E6 treatment is absent" in e7["baseline"]["source"]
    assert observation["first_example_before"] == {
        "text": "对大模型评测",
        "start": 17,
        "end": 23,
    }
    assert observation["first_example_expected"] == {
        "text": "大模型评测",
        "start": 18,
        "end": 23,
    }
    assert observation["cue_span"] == {"text": "等", "start": 33, "end": 34}
    assert observation["parent_span"] == {
        "text": "领域",
        "start": 34,
        "end": 36,
    }
    assert e7["control_fixture_ids"] == [
        "structured-corpus-external-v1-002",
        "structured-corpus-external-v1-005",
        "structured-corpus-external-v1-006",
        "structured-corpus-external-v1-009",
        "structured-corpus-external-v1-018",
    ]
    assert e7["acceptance_gate"] == "accept_only_if_all_four_criteria_pass"
    assert len(e7["acceptance_criteria"]) == 4


def test_builder_is_deterministic_and_artifacts_are_hash_pinned() -> None:
    synthesis, preregistration, findings = build_artifacts()
    expected_synthesis = json.dumps(synthesis, ensure_ascii=False, indent=2) + "\n"
    expected_preregistration = (
        json.dumps(preregistration, ensure_ascii=False, indent=2) + "\n"
    )

    assert SYNTHESIS_PATH.read_text(encoding="utf-8") == expected_synthesis
    assert PREREGISTRATION_PATH.read_text(encoding="utf-8") == expected_preregistration
    assert FINDINGS_PATH.read_text(encoding="utf-8") == findings
    assert _sha256(SYNTHESIS_PATH) == SYNTHESIS_SHA256
    assert _sha256(FINDINGS_PATH) == FINDINGS_SHA256
    assert _sha256(PREREGISTRATION_PATH) == PREREGISTRATION_SHA256


def test_frozen_v4_and_scope_are_unchanged() -> None:
    preregistration = _load(PREREGISTRATION_PATH)
    scope = preregistration["scope"]

    assert _sha256(PARSER_PATH) == PARSER_SHA256
    assert _sha256(RULES_FREEZE_PATH) == RULES_FREEZE_SHA256
    assert preregistration["status"] == "frozen_before_execution"
    assert scope["data_status"] == "revealed_development_only"
    assert scope["generalization_claim"] is False
    assert scope["v4_modification_allowed"] is False
    assert scope["v5_implementation_allowed"] is False
    assert scope["canonicalizer_work_allowed"] is False
    assert scope["model_calls_allowed"] is False
    assert scope["network_calls_allowed"] is False
