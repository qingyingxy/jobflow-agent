from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from scripts.run_unified_jd_flat_atomic_v4_3_independent_holdout import main
from src.evaluation.model_first_v4_3_independent_holdout import (
    evaluate_independent_holdout_v4_3,
)

CASE_IDS = [f"independent-case-{index}" for index in range(5)]
LONG_SOURCE = "Build systems " + "with observable production context " * 10


def _payload_sha256(value: object) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _selection() -> dict[str, Any]:
    contents = ["Build systems", "Build systems", LONG_SOURCE, "Build systems", "Build systems"]
    return {
        "selected_case_ids": CASE_IDS,
        "cases": [
            {
                "case_id": case_id,
                "raw_content": content,
                "source_content_sha256": hashlib.sha256(
                    content.encode("utf-8")
                ).hexdigest(),
            }
            for case_id, content in zip(CASE_IDS, contents, strict=True)
        ],
    }


def _preregistration() -> dict[str, Any]:
    return {
        "acceptance_gates": {
            "G5-granularity-noncollapse": {
                "per_case_minimums": {case_id: 1 for case_id in CASE_IDS},
                "minimum_aggregate_primary_atom_count": 5,
                "maximum_aggregate_primary_atom_count": 20,
            }
        }
    }


def _atom(
    *,
    role: str = "item",
    category: str = "responsibility",
    semantic_item: str = "build reliable systems",
    surface_item: str = "Build systems",
    source_text: str = "Build systems",
) -> dict[str, Any]:
    return {
        "role": role,
        "category": category,
        "level": "mention",
        "relation": "all_of",
        "semantic_item": semantic_item,
        "surface_item": surface_item,
        "source_text": source_text,
        "group_name": None,
        "allow_other": False,
        "qualifier": None,
    }


def _raw(*, modes: dict[int, str] | None = None) -> dict[str, Any]:
    modes = modes or {}
    records = []
    for index, case_id in enumerate(CASE_IDS):
        mode = modes.get(index, "valid")
        facts: list[dict[str, Any]] = []
        first = _atom()
        if mode == "role":
            first = _atom(role="responsibility")
        elif mode == "ineligible_role":
            first = _atom(role="responsibility", category="skill")
        elif mode == "omission":
            facts.append(
                {
                    "field": "experience",
                    "raw_items": [],
                    "level": None,
                    "source_text": "",
                }
            )
        elif mode == "long":
            first = _atom(
                semantic_item="Build systems",
                surface_item="Build systems",
                source_text=LONG_SOURCE,
            )
        records.append(
            {
                "case_id": case_id,
                "input_sha256": _selection()["cases"][index][
                    "source_content_sha256"
                ],
                "request_sha256": f"request-{index}",
                "model_call_count": 1,
                "started_at": f"2026-09-06T01:00:0{index}+00:00",
                "finished_at": f"2026-09-06T01:00:1{index}+00:00",
                "failure_code": None,
                "raw_model_output": {
                    "fact_mentions": facts,
                    "clause_atoms": [first],
                },
            }
        )
    return {"model_call_count": 5, "records": records}


def _requests(selection: dict[str, Any]) -> dict[str, Any]:
    entries = []
    for case in selection["cases"]:
        request = {
            "messages": [
                {
                    "role": "user",
                    "content": f"<job>\n{case['raw_content']}\n</job>",
                }
            ]
        }
        entries.append(
            {
                "case_id": case["case_id"],
                "input_sha256": case["source_content_sha256"],
                "request_sha256": _payload_sha256(request),
                "request": request,
            }
        )
    return {
        "written_at": "2026-09-06T00:00:00+00:00",
        "destination_host": "api.deepseek.com",
        "maximum_new_model_calls": 5,
        "maximum_calls_per_case": 1,
        "transport_retries": 0,
        "validation_retries": 0,
        "requests": entries,
    }


def _checkpoint(raw: dict[str, Any]) -> dict[str, Any]:
    records = raw["records"]
    history = [
        {
            "record_count": index,
            "records_sha256": _payload_sha256(records[:index]),
            "written_at": f"2026-09-06T01:00:2{index}+00:00",
        }
        for index in range(1, len(records) + 1)
    ]
    return {
        "model_call_count": len(records),
        "checkpoint_write_count": len(history),
        "history": history,
        "records": records,
    }


def _evaluate(raw: dict[str, Any]) -> dict[str, Any]:
    selection = _selection()
    return evaluate_independent_holdout_v4_3(
        selection,
        _preregistration(),
        _requests(selection),
        _checkpoint(raw),
        raw,
        authorization_confirmed=True,
        destination_valid=True,
        independence_valid=True,
        frozen_inputs_valid=True,
        frozen_sources_valid=True,
        gold_unavailable_to_requests=True,
        raw_responses_retained=True,
    )


def test_independent_holdout_confirms_all_three_v4_3_mechanisms() -> None:
    report = _evaluate(_raw(modes={0: "role", 1: "omission", 2: "long"}))

    assert report["passed"] is True
    assert report["decision"] == "confirmed"
    causal = report["gates"]["G8-generalization-decision"]
    assert causal["activation_count"] == 3
    assert causal["activation_counts"] == {
        "normalized_responsibility_role_alias": 1,
        "omitted_empty_absent_fact_placeholder": 1,
        "normalized_long_self_sufficient_evidence": 1,
    }
    assert causal["baseline_schema_valid_case_count"] == 2
    assert causal["v4_3_schema_valid_case_count"] == 5
    assert causal["activated_cases_have_only_eligible_incompatibilities"] is True
    integrity = report["gates"]["G3-compatibility-intervention-integrity"]
    assert integrity["forward_exactly_equals_v4_2"] is True
    assert integrity["reverse_exactly_restores_raw"] is True


def test_independent_holdout_reports_non_regression_without_activation() -> None:
    report = _evaluate(_raw())

    assert report["passed"] is True
    assert report["decision"] == "supported_non_regression_only"
    assert report["gates"]["G3-compatibility-intervention-integrity"][
        "activation_count"
    ] == 0


def test_independent_holdout_fails_closed_for_ineligible_role() -> None:
    report = _evaluate(_raw(modes={0: "ineligible_role"}))

    assert report["passed"] is False
    assert report["decision"] == "failed"
    assert report["gates"]["G2-v4-3-strict-schema-restoration"]["passed"] is False


def test_independent_holdout_rejects_incomplete_checkpoint_history() -> None:
    raw = _raw()
    selection = _selection()
    checkpoint = _checkpoint(raw)
    checkpoint["history"].pop()

    report = evaluate_independent_holdout_v4_3(
        selection,
        _preregistration(),
        _requests(selection),
        checkpoint,
        raw,
        authorization_confirmed=True,
        destination_valid=True,
        independence_valid=True,
        frozen_inputs_valid=True,
        frozen_sources_valid=True,
        gold_unavailable_to_requests=True,
        raw_responses_retained=True,
    )

    assert report["passed"] is False
    assert report["gates"]["G1-raw-capture-completeness"]["passed"] is False


def test_independent_holdout_runner_requires_explicit_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv", ["run_unified_jd_flat_atomic_v4_3_independent_holdout.py"]
    )

    with pytest.raises(SystemExit, match="explicit authorization"):
        main()
