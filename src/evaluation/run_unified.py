from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from src.evaluation.unified_metrics import evaluate_unified_manifest
from src.evaluation.unified_models import (
    UnifiedEvaluationManifest,
    UnifiedPredictionFile,
)


def main() -> int:
    arguments = _parse_args()
    started_at = datetime.now(UTC)
    started_clock = perf_counter()
    manifest = UnifiedEvaluationManifest.model_validate_json(
        Path(arguments.manifest).read_text(encoding="utf-8")
    )
    prediction_file = UnifiedPredictionFile.model_validate_json(
        Path(arguments.predictions).read_text(encoding="utf-8")
    )
    report = evaluate_unified_manifest(manifest, prediction_file.predictions)
    report["prediction_version"] = prediction_file.prediction_version
    report["prediction_generation"] = {
        "schema_version": prediction_file.schema_version,
        "parser_version": prediction_file.parser_version,
        "prompt_version": prediction_file.prompt_version,
        "model": prediction_file.model,
        "generated_at": prediction_file.generated_at,
    }
    report["run"] = {
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "duration_ms": round((perf_counter() - started_clock) * 1000, 2),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "model_api_called": False,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if arguments.output:
        output_path = Path(arguments.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")

    print(
        "unified-evaluation "
        f"dataset={report['dataset_version']} "
        f"split={report['split']} "
        f"cases={report['case_count']} "
        f"schema_valid={report['schema_valid_rate']:.4f} "
        f"parse_success={report['parse_success_rate']:.4f} "
        f"facts_f1={report['dimensions']['facts']['macro_f1']:.4f} "
        f"span_f1={report['dimensions']['evidence_spans']['all']['character_coverage']['f1']:.4f} "
        f"category_f1={report['dimensions']['category']['overall']['f1']:.4f} "
        f"level_f1={report['dimensions']['level']['overall']['f1']:.4f} "
        f"relation_f1={report['dimensions']['relation']['overall']['f1']:.4f} "
        f"canonical_items_f1={report['dimensions']['canonical_items']['overall']['f1']:.4f} "
        f"legacy_clause_exact_f1={report['clauses']['all']['f1']:.4f} "
        f"gate={'passed' if report['gate']['passed'] else 'failed'}"
    )
    if arguments.output:
        print(f"report={arguments.output}")
    if arguments.fail_on_gate and not report["gate"]["passed"]:
        return 2
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run deterministic Unified JD evaluation without model calls"
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--output")
    parser.add_argument(
        "--fail-on-gate",
        action="store_true",
        help="Return exit code 2 when any frozen acceptance threshold fails",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
