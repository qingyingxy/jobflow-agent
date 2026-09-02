from __future__ import annotations

import pytest

from src.evaluation.merge_predictions import merge_predictions
from src.evaluation.models import (
    EvaluationCase,
    EvaluationInput,
    EvaluationManifest,
    ExpectedLabels,
    PredictionFile,
    PredictionRecord,
    SourceMetadata,
)


def _manifest(*case_ids: str) -> EvaluationManifest:
    return EvaluationManifest(
        manifest_version="manifest-v1",
        dataset_version="dataset-v1",
        split="dev",
        purpose="test prediction shard merging",
        source_policy="synthetic test data only",
        fields=["job_type"],
        cases=[
            EvaluationCase(
                id=case_id,
                split="dev",
                source=SourceMetadata(
                    kind="synthetic",
                    reference=case_id,
                    authorization="test fixture",
                ),
                input=EvaluationInput(raw_content="Synthetic job description for tests."),
                expected=ExpectedLabels(fields={"job_type": "campus"}),
            )
            for case_id in case_ids
        ],
    )


def _predictions(*case_ids: str, model: str = "deepseek") -> PredictionFile:
    return PredictionFile(
        prediction_version="shard-v1",
        predictions=[
            PredictionRecord(case_id=case_id, fields={"job_type": "campus"})
            for case_id in case_ids
        ],
        model=model,
        prompt_version="prompt-v1",
        generation_duration_ms=12.0,
    )


def test_merge_predictions_follows_manifest_order() -> None:
    merged = merge_predictions(
        _manifest("case-a", "case-b", "case-c"),
        [_predictions("case-c"), _predictions("case-a", "case-b")],
        prediction_version="merged-v1",
    )

    assert [item.case_id for item in merged.predictions] == [
        "case-a",
        "case-b",
        "case-c",
    ]
    assert merged.prediction_failure_count == 0
    assert merged.generation_duration_ms == 24.0


@pytest.mark.parametrize(
    ("shards", "message"),
    [
        ([_predictions("case-a"), _predictions("case-a", "case-b")], "duplicate"),
        ([_predictions("case-a")], "coverage mismatch"),
        (
            [_predictions("case-a"), _predictions("case-b", model="other")],
            "one model",
        ),
    ],
)
def test_merge_predictions_rejects_invalid_shards(
    shards: list[PredictionFile],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        merge_predictions(
            _manifest("case-a", "case-b"),
            shards,
            prediction_version="merged-v1",
        )
