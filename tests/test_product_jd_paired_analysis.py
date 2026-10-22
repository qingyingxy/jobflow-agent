import pytest

from scripts.analyze_product_jd_paired_acceptance import analyze, paired_latency


def row(case_id, mode, parsed, seconds, decision):
    return {
        "case_id": case_id,
        "case_kind": "real_regression",
        "mode": mode,
        "output": {} if parsed else None,
        "failure_code": None if parsed else "failed",
        "duration_ms": seconds * 1000,
        "calls": [],
        "qualifications": [
            {
                "id": "candidate",
                "expected": {"education": "pass", "eligibility": "pass"},
                "actual": {"education": decision, "eligibility": decision, "checks": []}
                if parsed
                else None,
            }
        ],
    }


def test_analysis_pairs_cases_and_keeps_failed_predictions():
    rows = [
        row("one", "single_call", True, 2, "pass"),
        row("two", "two_stage", True, 3, "fail"),
        row("one", "two_stage", True, 4, "pass"),
        row("two", "single_call", False, 6, None),
    ]
    cases = [{"id": key, "case_kind": "real_regression"} for key in ("one", "two")]
    result = analyze(rows, cases)
    real = result["groups"]["real_regression"]
    assert real["parse_success"] == {
        "both_correct": 1,
        "single_only": 0,
        "two_only": 1,
        "both_incorrect": 0,
    }
    assert real["candidate_decisions"]["eligibility"]["both_incorrect"] == 1
    assert real["latency_both_parsed"]["pairs"] == 1
    assert real["latency_including_failures"]["pairs"] == 2
    assert len(result["failure_catalog"]) == 1
    assert len(result["decision_mismatches"]) == 4
    assert result["model_call_count"] == 0


def test_final_analysis_rejects_incomplete_pairs():
    with pytest.raises(ValueError, match="complete"):
        analyze(
            [row("one", "single_call", True, 2, "pass")],
            [{"id": "one", "case_kind": "real_regression"}],
        )


def test_latency_compares_the_same_case():
    pairs = [
        {"single_call": {"duration_ms": 1000}, "two_stage": {"duration_ms": 2000}},
        {"single_call": {"duration_ms": 30000}, "two_stage": {"duration_ms": 10000}},
    ]
    result = paired_latency(pairs)
    assert result["single_faster_count"] == 1
    assert result["median_single_over_two_ratio"] == 1.75
    assert result["duration_sum_single_over_two_ratio"] == 31 / 12
