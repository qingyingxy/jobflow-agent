from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from scripts.run_unified_jd_model_first_v1 import (
    DEFAULT_CANONICAL,
    DEFAULT_MANIFEST,
    DEFAULT_PREDICTIONS,
)
from src.evaluation.model_first import (
    ModelFirstCanonicalFile,
    evaluate_model_first_manifest,
)
from src.evaluation.unified_models import (
    UnifiedEvaluationManifest,
    UnifiedPredictionFile,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = (
    ROOT
    / "artifacts/evaluation/unified-jd-model-first-v1-dev20-report-v1-2026-09-05.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate model-first v1 with independent output dimensions"
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--fail-on-hard-gate", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    if arguments.output.exists():
        raise SystemExit(f"refusing to overwrite report: {arguments.output}")
    started_at = datetime.now(UTC)
    started_clock = perf_counter()
    manifest = UnifiedEvaluationManifest.model_validate_json(
        arguments.manifest.read_text(encoding="utf-8")
    )
    predictions = UnifiedPredictionFile.model_validate_json(
        arguments.predictions.read_text(encoding="utf-8")
    )
    canonical = ModelFirstCanonicalFile.model_validate_json(
        arguments.canonical.read_text(encoding="utf-8")
    )
    report = evaluate_model_first_manifest(manifest, predictions, canonical)
    report["inputs"] = {
        "manifest": {
            "path": arguments.manifest.as_posix(),
            "sha256": _sha256(arguments.manifest),
        },
        "predictions": {
            "path": arguments.predictions.as_posix(),
            "sha256": _sha256(arguments.predictions),
        },
        "canonical": {
            "path": arguments.canonical.as_posix(),
            "sha256": _sha256(arguments.canonical),
        },
    }
    report["run"] = {
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "duration_ms": round((perf_counter() - started_clock) * 1000, 2),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "model_api_called": False,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    dimensions = report["primary_dimensions"]
    print(
        "model-first evaluation "
        f"cases={report['case_count']} "
        f"facts_f1={dimensions['facts']['macro_f1']:.4f} "
        f"category_f1={dimensions['category']['overall']['f1']:.4f} "
        f"level_f1={dimensions['level']['overall']['f1']:.4f} "
        f"relation_f1={dimensions['relation']['overall']['f1']:.4f} "
        f"canonical_items_f1={dimensions['canonical_items']['overall']['f1']:.4f} "
        f"hard_gate={'passed' if report['hard_gate']['passed'] else 'failed'}"
    )
    print(f"report={arguments.output}")
    if arguments.fail_on_hard_gate and not report["hard_gate"]["passed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
