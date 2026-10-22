from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-revealed-error-analysis-v1-2026-09-04.json"
)
FINDINGS_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-revealed-error-analysis-v1-2026-09-04.md"
)
PARSER_PATH = PROJECT_ROOT / "src/domain/unified_jd_structured_spans_v4.py"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_analysis_is_revealed_development_only_and_does_not_run_v4() -> None:
    analysis = _load(ANALYSIS_PATH)

    assert analysis["scope"] == {
        "status": "revealed_development_diagnosis_only",
        "fixture_count": 20,
        "generalization_claim": False,
        "threshold_selection_allowed": False,
        "parser_modified": False,
        "parser_executed": False,
        "model_call_count": 0,
        "network_call_count": 0,
    }
    assert analysis["inputs"]["frozen_v4_parser"]["sha256"] == _sha256(
        PARSER_PATH
    )


def test_analysis_pins_observed_error_counts() -> None:
    analysis = _load(ANALYSIS_PATH)

    assert analysis["routing_summary"]["fallback_translation_count"] == 16
    assert analysis["routing_summary"]["native_v4_count"] == 4
    assert analysis["layer_summary"]["wrappers"]["failed_fixture_count"] == 18
    assert (
        analysis["layer_summary"]["shared_scope_edges"]["failed_fixture_count"]
        == 15
    )
    assert (
        analysis["layer_summary"]["example_attachment_edges"][
            "failed_fixture_count"
        ]
        == 3
    )
    assert analysis["connector_summary"]["error_count"] == 9
    assert analysis["connector_summary"]["failed_fixture_count"] == 6
    assert analysis["dependency_finding"]["surface_failure_count"] == 19
    assert analysis["dependency_finding"]["projection_only_failure_count"] == 0


def test_hypotheses_are_isolated_and_predeclare_controls_and_stops() -> None:
    analysis = _load(ANALYSIS_PATH)
    experiments = analysis["causal_experiment_plan"]

    assert [item["order"] for item in experiments] == [1, 2, 3, 4, 5]
    assert len({item["id"] for item in experiments}) == 5
    for experiment in experiments:
        assert experiment["target_fixture_ids"]
        assert experiment["control_fixture_ids"]
        assert experiment["primary_outcomes"]
        assert experiment["acceptance"]
        assert experiment["falsification"]
        assert not (
            set(experiment["target_fixture_ids"])
            & set(experiment["control_fixture_ids"])
        )

    assert analysis["decision"]["v5_implementation_allowed"] is False
    assert analysis["decision"]["canonicalizer_allowed"] is False
    assert analysis["decision"]["new_holdout_required_after_v5_freeze"] is True


def test_human_findings_state_the_non_constraint_conclusion() -> None:
    findings = FINDINGS_PATH.read_text(encoding="utf-8")

    assert "architectural coverage, not a missing isolated constraint" in findings
    assert "zero projection-only failures" in findings
    assert "Do not implement v5 yet" in findings
