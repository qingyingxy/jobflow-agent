import json
from types import SimpleNamespace
from typing import ClassVar

import pytest

from scripts.run_product_jd_paired_acceptance import (
    DATASET,
    EDUCATION_LABELS,
    RecordingClient,
    decision_metrics,
    pair_integrity,
    qualifications,
    run_paired,
    validate_inputs,
)
from src.config import Settings
from src.domain.education import EducationCondition
from src.domain.eligibility import CandidateProfileInput
from src.services.education_evaluator import evaluate_education


def decision(expected, actual):
    return {
        "expected": {"education": expected},
        "actual": {"education": actual} if actual else None,
    }


def test_unavailable_and_unknown_do_not_inflate_accuracy():
    result = decision_metrics(
        [
            decision("pass", "pass"),
            decision("pass", "fail"),
            decision("fail", "unknown"),
            decision("unknown", "pass"),
            decision("unknown", "unknown"),
            decision("pass", None),
        ],
        "education",
    )
    assert result["total"] == 6
    assert result["correct"] == 2
    assert result["accuracy"] == 2 / 6
    assert result["wrong_pass"] == 1
    assert result["wrong_fail"] == 1
    assert result["false_exclusion_rate"] == 1 / 3
    assert result["missed_determinate_as_unknown"] == 1
    assert result["expected_unknown_correct"] == 1
    assert result["unavailable"] == 1


def test_pair_integrity_rejects_missing_or_duplicate_modes():
    cases = [{"id": "one"}]
    rows = [{"case_id": "one", "mode": "single_call"}]
    assert pair_integrity(rows, cases)["complete"] is False
    rows.append({"case_id": "one", "mode": "two_stage"})
    assert pair_integrity(rows, cases)["complete"] is True
    assert pair_integrity(rows + rows[:1], cases)["complete"] is False


def test_failed_parser_has_no_candidate_decision():
    labels = [{"id": "one", "profile": {}, "education": "pass", "eligibility": "pass"}]
    assert qualifications(None, labels)[0]["actual"] is None


def test_preregistered_labels_are_valid_without_model_calls():
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    labels = json.loads(EDUCATION_LABELS.read_text(encoding="utf-8"))
    validate_inputs(dataset, labels)
    assert len(dataset["cases"]) == 100
    assert sum(len(c["qualifications"]) for c in labels["real_annotations"]) == 37
    assert sum(len(c["qualification_labels"]) for c in labels["synthetic_cases"]) == 27


def test_real_education_gold_matches_explicit_reference_predicates():
    """Check hand-authored gold using reference predicates, never model predictions."""

    def branch(
        level,
        operator,
        major_mode="not_specified",
        values=(),
        *,
        unresolved=False,
        status="any",
    ):
        return {
            "source_text": "reference qualification",
            "degree": {
                "operator": operator,
                "level": level,
                "source_text": "reference degree",
            },
            "major": {
                "mode": major_mode,
                "values": list(values),
                "source_text": "reference major",
            },
            "scope": "application",
            "scope_source_text": "reference qualification",
            "status": status,
            "unresolved": unresolved,
        }

    bachelor = branch("bachelor", "gte")
    refs = {
        "003": ([bachelor], "all_of", [2027]),
        "012": ([bachelor], "all_of", None),
        "017": (
            [branch("bachelor", "gte", "unknown", unresolved=True)],
            "all_of",
            None,
        ),
        "096": (
            [
                branch(
                    level,
                    "eq",
                    "related",
                    ["计算机", "软件工程"],
                    unresolved=True,
                    status="enrolled",
                )
                for level in ("bachelor", "master")
            ],
            "any_of",
            None,
        ),
        "105": (
            [
                branch(level, "eq", unresolved=True)
                for level in ("bachelor", "master", "doctor")
            ],
            "any_of",
            None,
        ),
        "174": ([bachelor], "all_of", [2027]),
        "179": (
            [
                branch(
                    "bachelor", "gte", "related", ["计算机科学", "软件工程", "人工智能"]
                )
            ],
            "all_of",
            [2027],
        ),
        "180": (
            [
                {
                    **bachelor,
                    "major": {
                        "mode": "any",
                        "values": [],
                        "source_text": "reference major",
                    },
                }
            ],
            "all_of",
            [2027],
        ),
    }
    labels = json.loads(EDUCATION_LABELS.read_text(encoding="utf-8"))
    for case in labels["real_annotations"]:
        branches, relation, years = refs[case["case_id"].removeprefix("campus-ai-")]
        condition = EducationCondition(relation=relation, branches=branches)
        for label in case["qualifications"]:
            result = evaluate_education(
                condition,
                CandidateProfileInput.model_validate(label["profile"]),
                graduation_years=years,
            )
            assert result.result == label["education"], (case["case_id"], label["id"])


@pytest.mark.asyncio
async def test_recording_preserves_whitelisted_http_details_only():
    class Error(Exception):
        code = "llm_response_error"
        details: ClassVar = {
            "status_code": 503,
            "usage": {"prompt_tokens": 2},
            "secret": "sensitive",
        }

    class Client:
        async def generate(self, request):
            raise Error()

    recorder = RecordingClient(Client())
    with pytest.raises(Error):
        await recorder.generate(SimpleNamespace(schema_name="schema"))
    assert recorder.calls[0]["error_details"] == {
        "status_code": 503,
        "usage": {"prompt_tokens": 2},
    }
    assert recorder.calls[0]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_failed_fake_outputs_still_complete_both_modes():
    # Invalid output is a controlled failed parse, never a dropped result.
    from unittest.mock import patch

    import scripts.run_product_jd_paired_acceptance as runner

    class Client:
        model = "test"
        model_name = "test"

        async def generate(self, request):
            return SimpleNamespace(
                output={},
                model="test",
                usage={},
                response_id=None,
                finish_reason="stop",
            )

    cases = [
        {
            "id": "one",
            "raw_content": "青河科技招聘工程师。任职要求：本科以上。工作地点上海。",
            "case_kind": "real_regression",
            "qualification_labels": [],
        }
    ]
    snapshots = []
    args = SimpleNamespace(concurrency=1, validation_retries=0, run_timeout=10)
    with patch.object(runner, "create_structured_model_client", return_value=Client()):
        rows = await run_paired(
            cases, Settings(), args, lambda rs: snapshots.append(list(rs))
        )
    assert len(rows) == 2
    assert all(r["failure_code"] is not None for r in rows)
    assert pair_integrity(rows, cases)["complete"]
    assert len(snapshots) == 2
