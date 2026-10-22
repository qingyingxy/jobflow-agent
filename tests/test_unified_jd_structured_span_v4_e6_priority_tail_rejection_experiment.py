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
    / "artifacts/evaluation/unified-jd-structured-span-v4-e6-priority-tail-rejection-raw-v1-2026-09-04.json"
)
REPORT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e6-priority-tail-rejection-report-v1-2026-09-04.json"
)
FINDINGS_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e6-priority-tail-rejection-findings-v1-2026-09-04.md"
)

PARSER_SHA256 = "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094"
RULES_FREEZE_SHA256 = (
    "6a8a1d9ccce7c1069a483c7cc387221164de52800a133308922d57ff75ad6a12"
)
PREREGISTRATION_SHA256 = (
    "7acfbed9a61ec39c16136604d58b19c8b562dfe43ff256cc789e4e8ff2fb708e"
)
RAW_SHA256 = "bd8c4cf1df2ee72294337c6156f6c2094acd7bc2ba71757a481ea4e3c12403a2"
REPORT_SHA256 = "ca8699805ee11b049fed996df7266388ee488156632f7ecd03cee9bbcbfc68ea"
FINDINGS_SHA256 = "efd67682b4a9a2c6f50769d10dd7523b83197959175edcb78a2eb1cf4754cbb9"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_e6_uses_the_frozen_non_cumulative_baseline() -> None:
    raw = _load(RAW_PATH)

    assert raw["status"] == "revealed_development_causal_experiment"
    assert raw["experiment_id"] == "E6-priority-tail-rejection"
    assert raw["arms"] == ["e5_final_baseline", "priority_tail_rejection"]
    assert raw["preregistration_frozen_before_execution"] is True
    assert raw["baseline_source"] == "E5 toggle3_parent_ranked"
    assert raw["cumulative_treatment"] is False
    assert raw["v4_parser_executed"] is False
    assert raw["v5_implemented"] is False
    assert raw["fixture_count"] == 5
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


def test_e6_baselines_match_e5_final_byte_for_byte() -> None:
    raw = _load(RAW_PATH)
    e5_by_id = {item["id"]: item for item in _load(E5_RAW_PATH)["records"]}

    for record in raw["records"]:
        assert record["e5_final_baseline"] == e5_by_id[record["id"]][
            "toggle3_parent_ranked"
        ]


def test_e6_changes_only_006_and_removes_all_false_attachment_outputs() -> None:
    raw = _load(RAW_PATH)
    records = {item["id"]: item for item in raw["records"]}
    target = records["structured-corpus-external-v1-006"]
    event = target["eligibility_events"][0]

    assert target["e5_final_baseline"]["attachments"][0]["cue_span"] == {
        "text": "等",
        "start": 32,
        "end": 33,
    }
    assert event["complete_right_tail"] == {
        "text": "优先",
        "start": 33,
        "end": 35,
    }
    assert event["attachment_eligible"] is False
    assert target["priority_tail_rejection"]["attachments"] == []
    assert target["priority_tail_rejection"]["example_members"] == []
    assert target["priority_tail_rejection"]["example_items"] == []

    for fixture_id in (
        "structured-corpus-external-v1-002",
        "structured-corpus-external-v1-005",
        "structured-corpus-external-v1-019",
        "structured-corpus-external-v1-018",
    ):
        assert records[fixture_id]["priority_tail_rejection"] == records[fixture_id][
            "e5_final_baseline"
        ]


def test_e6_passes_all_four_frozen_criteria() -> None:
    report = _load(REPORT_PATH)
    decision = report["decision"]
    target = report["aggregate"]["targets"]["priority_tail_rejection"]

    assert report["scope"]["one_time_frozen_gate_decision"] is True
    assert report["scope"]["generalization_claim"] is False
    assert report["scope"]["production_rule_claim"] is False
    assert report["scope"]["v5_implemented"] is False
    assert decision["criterion_1_006_false_outputs_removed"] is True
    assert decision["criterion_2_019_discovery_preserved"] is True
    assert decision["criterion_3_all_controls_byte_identical"] is True
    assert decision["criterion_4_retained_attachment_spans_unchanged"] is True
    assert all(decision["control_byte_equality"].values())
    assert decision["accepted"] is True
    assert target["example_members"]["f1"] == 1.0
    assert target["attachment_edges"]["f1"] == 1.0
    assert target["example_projection"]["f1"] == 1.0


def test_e6_outputs_are_hash_pinned_and_do_not_claim_a_v5_rule() -> None:
    findings = FINDINGS_PATH.read_text(encoding="utf-8")

    assert _sha256(RAW_PATH) == RAW_SHA256
    assert _sha256(REPORT_PATH) == REPORT_SHA256
    assert _sha256(FINDINGS_PATH) == FINDINGS_SHA256
    assert "Decision: **accepted**" in findings
    assert "single-case" in findings
    assert "does not authorize v5 implementation" in findings
