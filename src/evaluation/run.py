from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.evaluation.metrics import evaluate_manifest
from src.evaluation.models import EvaluationManifest, PredictionFile


def main() -> int:
    arguments = _parse_args()
    manifest = _load_manifest(Path(arguments.manifest))
    prediction_file = _load_predictions(Path(arguments.predictions))
    report = evaluate_manifest(
        manifest,
        prediction_file.predictions,
        model=arguments.model,
        prompt_version=arguments.prompt_version,
        validator_version=arguments.validator_version,
    )
    report["prediction_version"] = prediction_file.prediction_version
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"

    if arguments.output:
        output_path = Path(arguments.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")
    print(
        "evaluation "
        f"dataset={report['dataset_version']} "
        f"split={report['split']} "
        f"cases={report['case_count']} "
        f"macro_f1={_display(report['validated']['macro_f1'])} "
        f"eligibility_accuracy={_display(report['validated']['eligibility_accuracy'])} "
        f"unsupported_claim_rate={_display(report['validated']['unsupported_claim_rate'])}"
    )
    if arguments.output:
        print(f"report={arguments.output}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic JobFlow evaluation")
    parser.add_argument("--manifest", required=True, help="Versioned evaluation manifest")
    parser.add_argument("--predictions", required=True, help="Model prediction JSON")
    parser.add_argument("--output", help="Optional machine-readable report path")
    parser.add_argument("--model", default=None)
    parser.add_argument("--prompt-version", default=None)
    parser.add_argument("--validator-version", default="evidence-boundary-v1")
    return parser.parse_args()


def _load_manifest(path: Path) -> EvaluationManifest:
    return EvaluationManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _load_predictions(path: Path) -> PredictionFile:
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return PredictionFile(prediction_version="unversioned", predictions=payload)
    return PredictionFile.model_validate(payload)


def _display(value: Any) -> str:
    return "undefined" if value is None else f"{value:.4f}"


if __name__ == "__main__":
    raise SystemExit(main())
