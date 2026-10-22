from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARSER_PATH = PROJECT_ROOT / "src/domain/unified_jd_structured_spans_v4.py"
RULES_FREEZE_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_rules_freeze_v4_2026-09-04.json"
)
RAW_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e4-scope-candidate-application-raw-v1-2026-09-04.json"
)
REPORT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e4-scope-candidate-application-report-v1-2026-09-04.json"
)
FINDINGS_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e4-scope-candidate-application-findings-v1-2026-09-04.md"
)

PARSER_SHA256 = "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094"
RULES_FREEZE_SHA256 = (
    "6a8a1d9ccce7c1069a483c7cc387221164de52800a133308922d57ff75ad6a12"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _span_key(span: dict[str, Any]) -> tuple[int, int, str]:
    return (span["start"], span["end"], span["text"])


def _edge_key(edge: dict[str, Any]) -> tuple[Any, ...]:
    return (
        edge["kind"],
        _span_key(edge["scope_span"]),
        _span_key(edge["member_span"]),
    )


def _candidate_edges(candidate: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [
        (candidate["kind"], _span_key(candidate["span"]), _span_key(member))
        for member in candidate["member_spans"]
    ]


def test_e4_is_an_offline_boundary_controlled_experiment() -> None:
    raw = _load(RAW_PATH)
    freeze = _load(RULES_FREEZE_PATH)

    assert raw["status"] == "revealed_development_causal_experiment"
    assert raw["experiment_id"] == "E4-scope-candidate-versus-application"
    assert raw["arms"] == ["topology_only", "compatibility"]
    assert raw["fixture_count"] == 8
    assert raw["v4_parser_executed"] is False
    assert raw["model_call_count"] == 0
    assert raw["network_call_count"] == 0
    assert raw["gold_wrapper_nuisance_count"] == 15
    assert raw["gold_member_boundary_nuisance_count"] == 16
    assert raw["gold_scope_edge_injection_count"] == 0
    assert raw["gold_projection_injection_count"] == 0
    assert raw["frozen_v4_source"] == {
        "path": "src/domain/unified_jd_structured_spans_v4.py",
        "sha256_before": PARSER_SHA256,
        "sha256_after": PARSER_SHA256,
        "modified": False,
    }
    assert _sha256(PARSER_PATH) == PARSER_SHA256
    assert _sha256(RULES_FREEZE_PATH) == RULES_FREEZE_SHA256
    assert freeze["parser"]["sha256"] == PARSER_SHA256


def test_e4_arms_share_candidates_and_differ_only_on_application() -> None:
    raw = _load(RAW_PATH)
    candidates = [
        candidate
        for record in raw["records"]
        for candidate in record["scope_candidates"]
    ]

    assert raw["scope_candidate_count"] == 10
    assert raw["compatibility_judgment_count"] == 10
    assert len(candidates) == 10
    assert Counter(item["compatibility_applied"] for item in candidates) == Counter(
        {True: 5, False: 5}
    )

    for record in raw["records"]:
        source = record["source_text"]
        topology_expected: list[tuple[Any, ...]] = []
        compatibility_expected: list[tuple[Any, ...]] = []
        for candidate in record["scope_candidates"]:
            assert candidate["topology_applied"] is True
            span = candidate["span"]
            assert source[span["start"] : span["end"]] == span["text"]
            topology_expected.extend(_candidate_edges(candidate))
            if candidate["compatibility_applied"]:
                compatibility_expected.extend(_candidate_edges(candidate))

        assert Counter(
            map(_edge_key, record["topology_only"]["shared_scope_edges"])
        ) == Counter(topology_expected)
        assert Counter(
            map(_edge_key, record["compatibility"]["shared_scope_edges"])
        ) == Counter(compatibility_expected)


def test_e4_passes_the_minimal_pair_and_singleton_checks() -> None:
    raw = _load(RAW_PATH)
    records = {item["id"]: item for item in raw["records"]}

    case_017 = records["structured-corpus-external-v1-017"]
    case_020 = records["structured-corpus-external-v1-020"]
    candidate_017 = case_017["scope_candidates"][0]
    candidate_020 = case_020["scope_candidates"][0]
    assert candidate_017["span"]["text"] == "\u80fd\u529b"
    assert candidate_020["span"]["text"] == "\u80fd\u529b"
    assert candidate_017["topology_applied"] is True
    assert candidate_020["topology_applied"] is True
    assert candidate_017["compatibility_applied"] is False
    assert candidate_020["compatibility_applied"] is True

    case_016 = records["structured-corpus-external-v1-016"]
    assert len(case_016["topology_only"]["shared_scope_edges"]) == 1
    assert case_016["compatibility"]["shared_scope_edges"] == []


def test_e4_is_rejected_by_the_registered_per_fixture_gate() -> None:
    report = _load(REPORT_PATH)
    decision = report["decision"]
    targets = report["aggregate"]["targets"]

    assert decision["topology_treats_017_020_same"] is True
    assert decision["compatibility_distinguishes_017_020"] is True
    assert decision["singleton_016_scope_avoided"] is True
    assert decision["improved_target_count"] == 3
    assert decision["required_improved_target_count"] == 4
    assert set(decision["improved_target_ids"]) == {
        "structured-corpus-external-v1-012",
        "structured-corpus-external-v1-016",
        "structured-corpus-external-v1-017",
    }
    assert decision["no_control_regression"] is True
    assert all(not values for values in decision["control_regressions"].values())
    assert decision["accepted"] is False

    assert targets["topology_only"]["shared_scope_edges"]["f1"] == pytest.approx(
        13 / 15
    )
    assert targets["compatibility"]["shared_scope_edges"]["f1"] == 1.0
    assert targets["topology_only"]["false_shared_scope_edge_count"] == 4
    assert targets["compatibility"]["false_shared_scope_edge_count"] == 0
    assert targets["topology_only"]["surface_projection"]["f1"] == pytest.approx(
        14 / 17
    )
    assert targets["compatibility"]["surface_projection"]["f1"] == 1.0


def test_e4_findings_do_not_promote_aggregate_or_oracle_success() -> None:
    findings = FINDINGS_PATH.read_text(encoding="utf-8")

    assert "Decision: **rejected**" in findings
    assert "improves only 3/6 targets" in findings
    assert "below the frozen 4/6 gate" in findings
    assert "diagnostic oracle, not a production rule" in findings
    assert "does not justify encoding these revealed judgments" in findings
