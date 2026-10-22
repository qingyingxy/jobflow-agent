from __future__ import annotations

from typing import Any

from src.evaluation.model_first_v4_live_probe import analyze_live_response_v4


def evaluate_zero_lower_bound_qualifier_pair(
    baseline_output: object,
    treatment_output: object,
    source_content: str,
) -> dict[str, dict[str, Any]]:
    """Evaluate both arms with the unchanged frozen v4 strict evaluator."""

    return {
        "baseline": analyze_live_response_v4(baseline_output, source_content),
        "treatment": analyze_live_response_v4(treatment_output, source_content),
    }
