from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_DATASET = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-development70-v2-2026-09-06.json"
)
DEFAULT_PREDICTIONS = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-development70-baseline-predictions-v5.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-any-of-review-candidates-v2.json"
)


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _interval(raw_content: str, source_text: str) -> tuple[int, int]:
    start = raw_content.find(source_text)
    if start < 0:
        raise ValueError(f"Source text is absent from development JD: {source_text!r}")
    return start, start + len(source_text)


def _overlap(left: tuple[int, int], right: tuple[int, int]) -> int:
    return max(0, min(left[1], right[1]) - max(left[0], right[0]))


def _best_overlap(
    raw_content: str,
    source_text: str,
    candidates: list[dict[str, Any]],
) -> tuple[int, dict[str, Any] | None]:
    source_interval = _interval(raw_content, source_text)
    ranked = [
        (_overlap(source_interval, _interval(raw_content, item["source_text"])), item)
        for item in candidates
    ]
    return max(ranked, key=lambda item: item[0], default=(0, None))


def _same_items(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return {_normalize(item) for item in left["items"]} == {
        _normalize(item) for item in right["items"]
    }


def analyze_disagreements(
    dataset: dict[str, Any],
    prediction_file: dict[str, Any],
) -> dict[str, Any]:
    predictions = {
        item["case_id"]: item for item in prediction_file["predictions"]
    }
    gold_any_of_disagreements: list[dict[str, Any]] = []
    predicted_any_of_disagreements: list[dict[str, Any]] = []
    sanitizer_downgrades: list[dict[str, Any]] = []
    missing_prediction_case_ids: list[str] = []
    failed_prediction_case_ids: list[str] = []
    gold_any_of_count = 0
    predicted_any_of_count = 0

    for case in dataset["cases"]:
        prediction = predictions.get(case["id"])
        if prediction is None:
            missing_prediction_case_ids.append(case["id"])
            continue
        prediction_output = prediction.get("output")
        if not isinstance(prediction_output, dict):
            failed_prediction_case_ids.append(case["id"])
            continue
        gold_requirements = case["expected"]["requirements"]
        predicted_requirements = prediction_output["requirements"]
        gold_any_of_count += sum(
            item["relation"] == "any_of" for item in gold_requirements
        )
        predicted_any_of_count += sum(
            item["relation"] == "any_of" for item in predicted_requirements
        )
        for gold in gold_requirements:
            if gold["relation"] != "any_of":
                continue
            overlap, matched = _best_overlap(
                case["raw_content"],
                gold["source_text"],
                predicted_requirements,
            )
            if (
                matched is not None
                and overlap > 0
                and matched["relation"] == "any_of"
                and _same_items(gold, matched)
            ):
                continue
            gold_any_of_disagreements.append(
                {
                    "case_id": case["id"],
                    "annotation_status": case["annotation_status"],
                    "gold": gold,
                    "best_prediction": matched if overlap > 0 else None,
                    "overlap_characters": overlap,
                }
            )

        for predicted in predicted_requirements:
            if predicted["relation"] != "any_of":
                continue
            overlap, matched = _best_overlap(
                case["raw_content"],
                predicted["source_text"],
                gold_requirements,
            )
            if matched is not None and overlap > 0 and matched["relation"] == "any_of":
                continue
            predicted_any_of_disagreements.append(
                {
                    "case_id": case["id"],
                    "annotation_status": case["annotation_status"],
                    "prediction": predicted,
                    "best_gold": matched if overlap > 0 else None,
                    "overlap_characters": overlap,
                }
            )

        clean_any_sources = {
            item["source_text"]
            for item in predicted_requirements
            if item["relation"] == "any_of"
        }
        raw_output = prediction.get("raw_output")
        if not isinstance(raw_output, dict):
            continue
        for raw_requirement in raw_output.get("requirements", []):
            if (
                isinstance(raw_requirement, dict)
                and raw_requirement.get("relation") == "any_of"
                and raw_requirement.get("source_text") not in clean_any_sources
            ):
                sanitizer_downgrades.append(
                    {
                        "case_id": case["id"],
                        "raw_requirement": raw_requirement,
                    }
                )

    return {
        "analysis_version": "product-jd-any-of-review-v2",
        "dataset_version": dataset["dataset_version"],
        "prediction_version": prediction_file["prediction_version"],
        "source_split": dataset.get("split"),
        "sealed_test_read": dataset.get("split") == "sealed_test",
        "missing_prediction_case_ids": missing_prediction_case_ids,
        "failed_prediction_case_ids": failed_prediction_case_ids,
        "summary": {
            "gold_any_of_count": gold_any_of_count,
            "predicted_any_of_count": predicted_any_of_count,
            "gold_any_of_disagreement_count": len(gold_any_of_disagreements),
            "predicted_any_of_disagreement_count": len(
                predicted_any_of_disagreements
            ),
            "sanitizer_downgrade_count": len(sanitizer_downgrades),
        },
        "gold_any_of_disagreements": gold_any_of_disagreements,
        "predicted_any_of_disagreements": predicted_any_of_disagreements,
        "sanitizer_downgrades": sanitizer_downgrades,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build Product JD any_of human-review candidates"
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
    result = analyze_disagreements(dataset, predictions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
