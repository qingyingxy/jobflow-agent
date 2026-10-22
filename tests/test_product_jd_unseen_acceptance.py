"""Checks for probe scoring and keeping unavailable cases in denominators."""

from scripts.analyze_product_jd_unseen_acceptance import probe_kind, transport_recovery
from scripts.run_product_jd_unseen_acceptance import relation_checks, summarize


def test_language_examples_are_separate_from_closed_alternatives():
    assert (
        probe_kind(
            {"relation": "any_of", "source_text": "one language such as Python or Go"}
        )
        == "example_or_open_range"
    )
    assert (
        probe_kind({"relation": "any_of", "source_text": "one of Python or Go"})
        == "explicit_or_shared_requirement"
    )


def test_scheduled_retry_is_not_automatically_a_successful_recovery():
    failed = {
        "output": None,
        "diagnostics": {
            "attempts": [
                {
                    "status": "model_error",
                    "transport_attempt": 1,
                    "retry_scheduled": True,
                },
                {"status": "model_error", "transport_attempt": 2},
            ]
        },
    }
    assert transport_recovery(failed) == {
        "scheduled_retries": 1,
        "requests_recovered": 0,
        "parse_succeeded_after_retry": False,
    }


def test_shared_python_requirement_is_not_satisfied_inside_an_alternative():
    probes = [
        {
            "source_text": "Strong Python",
            "relation": "all_of",
            "level": "required",
            "options": [],
        },
        {
            "source_text": "one of C++ / Go",
            "relation": "any_of",
            "level": "required",
            "options": ["C++", "Go"],
        },
    ]
    wrong = {
        "requirements": [
            {
                "source_text": "Strong Python plus one of C++ / Go",
                "relation": "any_of",
                "level": "required",
                "items": ["Python", "C++", "Go"],
            }
        ]
    }
    assert [c["passed"] for c in relation_checks(wrong, probes)] == [False, True]
    correct = {
        "requirements": [
            {
                "source_text": "Strong Python",
                "relation": "all_of",
                "level": "required",
                "items": ["Strong Python"],
            },
            {
                "source_text": "one of C++ / Go",
                "relation": "any_of",
                "level": "required",
                "items": ["C++", "Go"],
            },
        ]
    }
    assert all(c["passed"] for c in relation_checks(correct, probes))


def test_one_combined_item_cannot_pass_distinct_alternatives_probe():
    probe = {
        "source_text": "Python or Go",
        "relation": "any_of",
        "level": "required",
        "options": ["Python", "Go"],
    }
    output = {
        "requirements": [
            {
                "source_text": "Python or Go",
                "relation": "any_of",
                "level": "required",
                "items": ["Python or Go"],
            }
        ]
    }
    assert not relation_checks(output, [probe])[0]["passed"]


def test_unavailable_parse_remains_in_candidate_and_relation_denominators():
    rows = [
        {
            "mode": mode,
            "output": None,
            "duration_ms": 1000,
            "calls": [{}],
            "failure_code": "model_timeout",
            "diagnostics": {},
            "relation_checks": [{"passed": False}],
            "candidate_checks": [
                {
                    "expected": {"education": "pass", "eligibility": "pass"},
                    "actual": None,
                }
            ],
        }
        for mode in ("single_call", "two_stage")
    ]
    for data in summarize(rows).values():
        assert data["parsed"] == 0
        assert data["relation_probes"] == {"total": 1, "correct": 0}
        assert data["candidate_decisions"]["education"]["unavailable"] == 1
        assert data["candidate_decisions"]["education"]["total"] == 1
