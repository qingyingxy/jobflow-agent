from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from scripts.evaluate_unified_structured_span_v4_corpus_external_holdout import (
    _attachment_edge_keys,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARSER_PATH = PROJECT_ROOT / "src/domain/unified_jd_structured_spans_v4.py"
RULES_FREEZE_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_rules_freeze_v4_2026-09-04.json"
)
BASELINE_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-corpus-external-raw-v1-2026-09-04.json"
)
RAW_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e3-connector-role-oracle-raw-v1-2026-09-04.json"
)
REPORT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e3-connector-role-oracle-report-v1-2026-09-04.json"
)
FINDINGS_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e3-connector-role-oracle-findings-v1-2026-09-04.md"
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


def _member_keys(items: list[dict[str, Any]]) -> Counter[tuple[Any, ...]]:
    return Counter((item["role"], *_span_key(item["span"])) for item in items)


def _baseline_member_keys(record: dict[str, Any]) -> Counter[tuple[Any, ...]]:
    return Counter(
        (group["role"], *_span_key(member["span"]))
        for group in record["parsed_clause"]["coordinations"]
        for member in group["members"]
    )


def _edge_key(edge: list[list[Any]]) -> tuple[tuple[Any, ...], ...]:
    return tuple(tuple(span) for span in edge)


def test_e3_is_offline_and_preserves_both_v4_freezes() -> None:
    raw = _load(RAW_PATH)
    freeze = _load(RULES_FREEZE_PATH)

    assert raw["status"] == "revealed_development_causal_experiment"
    assert raw["experiment_id"] == "E3-region-first-connector-role-oracle"
    assert raw["baseline_reused"] is True
    assert raw["v4_parser_executed"] is False
    assert raw["fixture_count"] == 8
    assert raw["model_call_count"] == 0
    assert raw["network_call_count"] == 0
    assert raw["gold_member_boundary_injection_count"] == 0
    assert raw["gold_attachment_injection_count"] == 0
    assert raw["frozen_v4_source"] == {
        "path": "src/domain/unified_jd_structured_spans_v4.py",
        "sha256_before": PARSER_SHA256,
        "sha256_after": PARSER_SHA256,
        "modified": False,
    }
    assert _sha256(PARSER_PATH) == PARSER_SHA256
    assert _sha256(RULES_FREEZE_PATH) == RULES_FREEZE_SHA256
    assert freeze["parser"]["sha256"] == PARSER_SHA256


def test_e3_changes_exactly_the_nine_registered_connector_roles() -> None:
    raw = _load(RAW_PATH)
    records = {item["id"]: item for item in raw["records"]}
    changes = [change for item in raw["records"] for change in item["role_changes"]]

    assert raw["connector_role_intervention_count"] == len(changes) == 9
    assert Counter(
        (item["predicted_role"], item["expected_role"]) for item in changes
    ) == Counter(
        {
            ("none", "surface"): 4,
            ("surface", "embedded"): 2,
            ("surface", "example"): 2,
            ("surface", "quantifier"): 1,
        }
    )
    assert set(records) == {
        "structured-corpus-external-v1-001",
        "structured-corpus-external-v1-003",
        "structured-corpus-external-v1-007",
        "structured-corpus-external-v1-008",
        "structured-corpus-external-v1-010",
        "structured-corpus-external-v1-011",
        "structured-corpus-external-v1-018",
        "structured-corpus-external-v1-019",
    }
    assert records["structured-corpus-external-v1-008"]["role_changes"] == []
    assert records["structured-corpus-external-v1-011"]["role_changes"] == []
    for record in raw["records"]:
        source = record["source_text"]
        for change in record["role_changes"]:
            span = change["span"]
            assert source[span["start"] : span["end"]] == span["text"]


def test_e3_control_reconstructs_the_stored_baseline_exactly() -> None:
    raw = _load(RAW_PATH)
    baseline_by_id = {item["id"]: item for item in _load(BASELINE_PATH)["records"]}

    for record in raw["records"]:
        baseline = baseline_by_id[record["id"]]
        control = record["control"]
        treatment = record["treatment"]
        baseline_roles = {
            (*_span_key(item["span"]), item["role"])
            for item in baseline["parsed_clause"]["connector_labels"]
        }
        control_roles = {
            (*_span_key(item["span"]), item["role"])
            for item in control["connector_labels"]
        }

        assert control_roles == baseline_roles
        assert _member_keys(control["coordination_members"]) == (
            _baseline_member_keys(baseline)
        )
        assert control["surface_items"] == baseline["items"]
        assert Counter(map(_edge_key, control["example_attachment_edges"])) == Counter(
            _attachment_edge_keys(baseline, gold=False)
        )
        assert treatment["example_attachment_edges"] == control[
            "example_attachment_edges"
        ]
        assert record["nuisance_state_held_fixed"] == {
            "wrappers": baseline["parsed_clause"]["wrappers"],
            "shared_scopes": baseline["parsed_clause"]["shared_scopes"],
        }


def test_e3_accepts_member_and_surface_effect_but_not_attachment() -> None:
    report = _load(REPORT_PATH)
    decision = report["decision"]
    targets = report["aggregate"]["targets"]
    records = {item["id"]: item for item in report["records"]}

    assert decision["accepted"] is True
    assert decision["improved_target_count"] == 4
    assert decision["required_improved_target_count"] == 4
    assert set(decision["improved_target_ids"]) == {
        "structured-corpus-external-v1-007",
        "structured-corpus-external-v1-010",
        "structured-corpus-external-v1-018",
        "structured-corpus-external-v1-019",
    }
    assert decision["no_control_regression"] is True
    assert all(not values for values in decision["control_regressions"].values())
    assert report["aggregate"]["controls"]["control"] == report["aggregate"][
        "controls"
    ]["treatment"]

    assert targets["control"]["coordination_members"]["f1"] == pytest.approx(
        2 / 7
    )
    assert targets["treatment"]["coordination_members"]["f1"] == pytest.approx(
        0.44
    )
    assert targets["control"]["surface_projection"]["f1"] == pytest.approx(
        7 / 24
    )
    assert targets["treatment"]["surface_projection"]["f1"] == pytest.approx(
        18 / 47
    )
    assert targets["control"]["example_attachment_edges"]["f1"] == 0.0
    assert targets["treatment"]["example_attachment_edges"]["f1"] == 0.0
    assert decision["attachment_improved"] is False

    assert records["structured-corpus-external-v1-001"]["regressed_outcomes"] == [
        "coordination_members"
    ]
    assert records["structured-corpus-external-v1-003"]["regressed_outcomes"] == [
        "coordination_members"
    ]


def test_e3_findings_keep_the_oracle_scope_explicit() -> None:
    findings = FINDINGS_PATH.read_text(encoding="utf-8")

    assert "Revealed development data only; no generalization claim." in findings
    assert "No gold member boundaries or attachment parents are injected." in findings
    assert "Role correction alone does not create missing attachment edges" in findings
    assert "run E4 scope candidate/application before combining mechanisms" in findings
