from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARSER_PATH = PROJECT_ROOT / "src/domain/unified_jd_structured_spans_v4.py"
RAW_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e2-wrapper-oracle-raw-v1-2026-09-04.json"
)
REPORT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e2-wrapper-oracle-report-v1-2026-09-04.json"
)
FINDINGS_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e2-wrapper-oracle-findings-v1-2026-09-04.md"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_e2_uses_two_offline_oracle_arms_without_running_v4() -> None:
    raw = _load(RAW_PATH)

    assert raw["status"] == "revealed_development_causal_experiment"
    assert raw["arms"] == ["metadata_only", "boundary_enforced"]
    assert raw["baseline_reused"] is True
    assert raw["v4_parser_executed"] is False
    assert raw["fixture_count"] == 10
    assert raw["model_call_count"] == 0
    assert raw["network_call_count"] == 0
    assert raw["frozen_v4_source"]["modified"] is False
    assert raw["frozen_v4_source"]["sha256_before"] == _sha256(PARSER_PATH)
    assert raw["frozen_v4_source"]["sha256_after"] == _sha256(PARSER_PATH)


def test_e2_accepts_boundary_contamination_without_topology_changes() -> None:
    report = _load(REPORT_PATH)

    assert report["decision"]["accepted"] is True
    assert report["decision"]["improved_target_count"] == 7
    assert report["decision"]["required_improved_target_count"] == 4
    assert set(report["decision"]["improved_target_ids"]) == {
        "structured-corpus-external-v1-001",
        "structured-corpus-external-v1-003",
        "structured-corpus-external-v1-004",
        "structured-corpus-external-v1-007",
        "structured-corpus-external-v1-008",
        "structured-corpus-external-v1-011",
        "structured-corpus-external-v1-020",
    }
    assert report["decision"]["metadata_only_downstream_unchanged"] is True
    assert report["decision"]["boundary_enforced_topology_unchanged"] is True
    assert report["decision"]["no_control_regression"] is True
    assert all(not values for values in report["decision"]["control_regressions"].values())


def test_e2_measures_member_scope_and_surface_contributions_separately() -> None:
    report = _load(REPORT_PATH)
    targets = report["aggregate"]["targets"]
    records = {item["id"]: item for item in report["records"]}

    assert targets["baseline"]["coordination_members"]["f1"] == pytest.approx(
        0.35
    )
    assert targets["boundary_enforced"]["coordination_members"][
        "f1"
    ] == pytest.approx(0.6)
    assert targets["baseline"]["shared_scope_edges"]["f1"] == pytest.approx(
        1 / 12
    )
    assert targets["boundary_enforced"]["shared_scope_edges"][
        "f1"
    ] == pytest.approx(1 / 6)
    assert targets["baseline"]["surface_projection"]["f1"] == pytest.approx(
        4 / 15
    )
    assert targets["boundary_enforced"]["surface_projection"][
        "f1"
    ] == pytest.approx(19 / 30)

    case_004 = records["structured-corpus-external-v1-004"]
    assert case_004["layer_difference_counts"]["surface_projection"] == {
        "baseline": 6,
        "metadata_only": 6,
        "boundary_enforced": 0,
    }
    case_020 = records["structured-corpus-external-v1-020"]
    assert {
        layer: values["boundary_enforced"]
        for layer, values in case_020["layer_difference_counts"].items()
    } == {
        "coordination_members": 0,
        "shared_scope_edges": 0,
        "surface_projection": 0,
    }
    case_016 = records["structured-corpus-external-v1-016"]
    assert case_016["member_or_surface_improved"] is False


def test_findings_keep_oracle_and_production_claims_separate() -> None:
    findings = FINDINGS_PATH.read_text(encoding="utf-8")

    assert "Decision: **accepted**" in findings
    assert "diagnostic oracle, not a production parser implementation" in findings
    assert "measured improvement is a lower bound" in findings
    assert "Do not copy gold-derived boundaries into v5" in findings
