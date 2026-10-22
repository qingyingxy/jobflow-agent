from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARSER_PATH = PROJECT_ROOT / "src/domain/unified_jd_structured_spans_v4.py"
BASELINE_RAW_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-corpus-external-raw-v1-2026-09-04.json"
)
TREATMENT_RAW_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e1-dispatch-only-raw-v1-2026-09-04.json"
)
REPORT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e1-dispatch-only-report-v1-2026-09-04.json"
)
FINDINGS_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e1-dispatch-only-findings-v1-2026-09-04.md"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _comparable(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record[key]
        for key in ("error", "items", "examples", "rule_ids", "parsed_clause")
    }


def test_e1_is_an_in_memory_revealed_development_intervention() -> None:
    raw = _load(TREATMENT_RAW_PATH)

    assert raw["status"] == "revealed_development_causal_experiment"
    assert raw["baseline_reused"] is True
    assert raw["baseline_v4_rerun"] is False
    assert raw["treatment_execution_count"] == 1
    assert raw["model_call_count"] == 0
    assert raw["network_call_count"] == 0
    assert raw["fixture_count"] == 8
    assert raw["frozen_v4_source"]["modified"] is False
    assert raw["frozen_v4_source"]["sha256_before"] == _sha256(PARSER_PATH)
    assert raw["frozen_v4_source"]["sha256_after"] == _sha256(PARSER_PATH)

    guards = raw["intervention"]["removed_guards"]
    assert len(guards) == 4
    assert {item["function"] for item in guards} == {
        "_parse_responsibility_v4",
        "_parse_skill_v4",
        "_parse_experience_v4",
        "_parse_capability_v4",
    }


def test_e1_controls_are_serialized_identically_to_reused_baseline() -> None:
    baseline = _load(BASELINE_RAW_PATH)
    treatment = _load(TREATMENT_RAW_PATH)
    baseline_by_id = {item["id"]: item for item in baseline["records"]}
    treatment_by_id = {item["id"]: item for item in treatment["records"]}
    control_ids = {
        "structured-corpus-external-v1-002",
        "structured-corpus-external-v1-012",
        "structured-corpus-external-v1-019",
    }

    for fixture_id in control_ids:
        assert _comparable(treatment_by_id[fixture_id]) == _comparable(
            baseline_by_id[fixture_id]
        )


def test_e1_is_rejected_by_the_registered_per_fixture_gate() -> None:
    report = _load(REPORT_PATH)
    records = {item["id"]: item for item in report["records"]}

    assert report["decision"]["accepted"] is False
    assert report["decision"]["improved_target_count"] == 2
    assert report["decision"]["required_improved_target_count"] == 3
    assert set(report["decision"]["improved_target_ids"]) == {
        "structured-corpus-external-v1-008",
        "structured-corpus-external-v1-016",
    }
    assert report["decision"]["no_target_structure_errors"] is True
    assert all(report["decision"]["control_unchanged"].values())
    assert {
        fixture_id: records[fixture_id]["structural_difference_delta"]
        for fixture_id in report["target_fixture_ids"]
    } == {
        "structured-corpus-external-v1-004": 0,
        "structured-corpus-external-v1-006": 2,
        "structured-corpus-external-v1-008": -8,
        "structured-corpus-external-v1-011": 0,
        "structured-corpus-external-v1-016": -1,
    }

    assert (
        report["aggregate"]["targets"]["treatment"]["surface_projection"]["f1"]
        > report["aggregate"]["targets"]["baseline"]["surface_projection"]["f1"]
    )
    assert "does not support" in report["decision"]["conclusion"]


def test_findings_do_not_promote_average_metric_gain_to_acceptance() -> None:
    findings = FINDINGS_PATH.read_text(encoding="utf-8")

    assert "Improved targets: 2/5 (required: 3/5)" in findings
    assert "Decision: **rejected**" in findings
    assert "do not implement unconditional dispatch in v5" in findings
