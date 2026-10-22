from __future__ import annotations

from pathlib import Path

import pytest

from scripts.build_unified_dev50_granularity_v2 import (
    build_granularity_v2_manifest,
)
from src.evaluation.predict_unified import generate_unified_predictions
from src.evaluation.unified_models import UnifiedEvaluationManifest
from src.infrastructure.llm_client import FakeModelClient, StructuredModelRequest


class CountingFakeModelClient(FakeModelClient):
    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.call_count = 0

    async def generate(self, request: StructuredModelRequest):  # type: ignore[no-untyped-def]
        self.call_count += 1
        return await super().generate(request)


def _one_case_manifest() -> UnifiedEvaluationManifest:
    manifest, _ = build_granularity_v2_manifest()
    return manifest.model_copy(update={"cases": [manifest.cases[0]]})


@pytest.mark.asyncio
async def test_unified_predictions_make_one_call_and_keep_valid_output() -> None:
    manifest = _one_case_manifest()
    expected = manifest.cases[0].expected
    assert expected is not None
    client = CountingFakeModelClient(output=expected.model_dump(mode="json"))

    prediction_file = await generate_unified_predictions(manifest, client=client)

    assert client.call_count == 1
    assert len(prediction_file.predictions) == 1
    prediction = prediction_file.predictions[0]
    assert prediction.model_call_count == 1
    assert prediction.failure_code is None
    assert prediction.output == expected.model_dump(mode="json")


@pytest.mark.asyncio
async def test_unified_predictions_can_opt_into_extraction_compiler() -> None:
    manifest = _one_case_manifest()
    extraction = {"fact_mentions": [], "clauses": []}
    client = CountingFakeModelClient(output=extraction)

    prediction_file = await generate_unified_predictions(
        manifest,
        client=client,
        parser_mode="extraction_v2",
    )

    assert client.call_count == 1
    assert prediction_file.parser_version == "unified-jd-parser-extraction-v5"
    prediction = prediction_file.predictions[0]
    assert prediction.failure_code is None
    assert prediction.output["facts"]["job_type"] is None
    assert prediction.output["clauses"] == []
    assert prediction.diagnostics["raw_model_output"] == extraction
    assert {
        item["code"] for item in prediction.diagnostics["compilation_diagnostics"]
    } == {
        "locally_backfilled_fact",
        "uncovered_requirement_evidence_line",
        "uncovered_responsibility_evidence_line",
    }


@pytest.mark.asyncio
async def test_unified_predictions_keep_invalid_raw_output_without_repair() -> None:
    manifest = _one_case_manifest()
    client = CountingFakeModelClient(output={"facts": {}})

    prediction_file = await generate_unified_predictions(manifest, client=client)

    assert client.call_count == 1
    prediction = prediction_file.predictions[0]
    assert prediction.output == {"facts": {}}
    assert prediction.failure_code == "unified_output_invalid"
    assert prediction.model_call_count == 1
    assert prediction.diagnostics["validation_errors"]


@pytest.mark.asyncio
async def test_unified_prediction_resume_never_repeats_checkpointed_case(
    tmp_path: Path,
) -> None:
    manifest = _one_case_manifest()
    expected = manifest.cases[0].expected
    assert expected is not None
    checkpoint = tmp_path / "checkpoint.json"
    first_client = CountingFakeModelClient(output=expected.model_dump(mode="json"))
    await generate_unified_predictions(
        manifest,
        client=first_client,
        checkpoint_path=checkpoint,
    )
    assert first_client.call_count == 1

    resume_client = CountingFakeModelClient(
        error=AssertionError("resume must not repeat a completed case")
    )
    prediction_file = await generate_unified_predictions(
        manifest,
        client=resume_client,
        checkpoint_path=checkpoint,
        resume=True,
    )

    assert resume_client.call_count == 0
    assert len(prediction_file.predictions) == 1
    assert prediction_file.predictions[0].failure_code is None


@pytest.mark.asyncio
async def test_unified_prediction_can_probe_only_next_pending_case(
    tmp_path: Path,
) -> None:
    manifest = build_granularity_v2_manifest()[0].model_copy(
        update={"cases": _one_case_manifest().cases * 2}
    )
    manifest.cases[1] = manifest.cases[1].model_copy(update={"id": "second-case"})
    expected = manifest.cases[0].expected
    assert expected is not None
    checkpoint = tmp_path / "checkpoint.json"
    client = CountingFakeModelClient(output=expected.model_dump(mode="json"))

    prediction_file = await generate_unified_predictions(
        manifest,
        client=client,
        checkpoint_path=checkpoint,
        max_new_cases=1,
    )

    assert client.call_count == 1
    assert [item.case_id for item in prediction_file.predictions] == [
        manifest.cases[0].id
    ]


@pytest.mark.asyncio
async def test_unified_prediction_model_call_budget_includes_checkpointed_calls(
    tmp_path: Path,
) -> None:
    manifest = build_granularity_v2_manifest()[0].model_copy(
        update={"cases": _one_case_manifest().cases * 2}
    )
    manifest.cases[1] = manifest.cases[1].model_copy(update={"id": "second-case"})
    checkpoint = tmp_path / "checkpoint.json"
    first_client = CountingFakeModelClient(output={"facts": {}})

    first = await generate_unified_predictions(
        manifest,
        client=first_client,
        checkpoint_path=checkpoint,
        max_new_cases=1,
        max_model_calls=1,
        validation_retries=1,
    )

    assert first_client.call_count == 1
    assert len(first.predictions) == 1
    assert first.predictions[0].failure_code == "unified_output_invalid"
    assert first.predictions[0].model_call_count == 1

    resume_client = CountingFakeModelClient(
        error=AssertionError("exhausted call budget must prevent another request")
    )
    resumed = await generate_unified_predictions(
        manifest,
        client=resume_client,
        checkpoint_path=checkpoint,
        resume=True,
        max_model_calls=1,
        validation_retries=1,
    )

    assert resume_client.call_count == 0
    assert [item.case_id for item in resumed.predictions] == [manifest.cases[0].id]


@pytest.mark.asyncio
async def test_unified_prediction_stops_before_next_case_after_failure() -> None:
    manifest = build_granularity_v2_manifest()[0].model_copy(
        update={"cases": _one_case_manifest().cases * 2}
    )
    manifest.cases[1] = manifest.cases[1].model_copy(update={"id": "second-case"})
    client = CountingFakeModelClient(output={"facts": {}})

    prediction_file = await generate_unified_predictions(
        manifest,
        client=client,
        stop_on_failure=True,
    )

    assert client.call_count == 1
    assert [item.case_id for item in prediction_file.predictions] == [
        manifest.cases[0].id
    ]
    assert prediction_file.predictions[0].failure_code == "unified_output_invalid"
