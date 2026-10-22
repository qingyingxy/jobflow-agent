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
    DEFAULT_MANIFEST,
    DEFAULT_PREDICTIONS,
)
from src.evaluation.model_first_v3 import (
    build_model_first_v3_replay,
    evaluate_model_first_v3,
)
from src.evaluation.unified_models import (
    UnifiedEvaluationManifest,
    UnifiedPredictionFile,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/evaluation"
DEFAULT_RAW_REPLAY = (
    ARTIFACT_DIR / "unified-jd-model-first-v3-dev20-raw-replay-2026-09-05.json"
)
DEFAULT_NORMALIZED_REPLAY = (
    ARTIFACT_DIR / "unified-jd-model-first-v3-dev20-normalized-replay-2026-09-05.json"
)
DEFAULT_DERIVED_REPLAY = (
    ARTIFACT_DIR / "unified-jd-model-first-v3-dev20-derived-replay-2026-09-05.json"
)
DEFAULT_PROJECTION = (
    ARTIFACT_DIR / "unified-jd-model-first-v3-dev20-layer-projection-2026-09-05.json"
)
DEFAULT_REPORT = ARTIFACT_DIR / "unified-jd-model-first-v3-dev20-report-2026-09-05.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_new_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = (
        payload.model_dump_json(indent=2)  # type: ignore[attr-defined]
        if hasattr(payload, "model_dump_json")
        else json.dumps(payload, ensure_ascii=False, indent=2)
    )
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(rendered + "\n")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replay frozen model-first outputs as raw, normalized, and derived layers"
        )
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source-predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--raw-replay", type=Path, default=DEFAULT_RAW_REPLAY)
    parser.add_argument(
        "--normalized-replay", type=Path, default=DEFAULT_NORMALIZED_REPLAY
    )
    parser.add_argument("--derived-replay", type=Path, default=DEFAULT_DERIVED_REPLAY)
    parser.add_argument("--projection", type=Path, default=DEFAULT_PROJECTION)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    outputs = [
        arguments.raw_replay,
        arguments.normalized_replay,
        arguments.derived_replay,
        arguments.projection,
        arguments.report,
    ]
    existing = [str(path) for path in outputs if path.exists()]
    if existing:
        raise SystemExit(f"refusing to overwrite v3 artifacts: {existing}")

    started_at = datetime.now(UTC)
    started_clock = perf_counter()
    manifest = UnifiedEvaluationManifest.model_validate_json(
        arguments.manifest.read_text(encoding="utf-8")
    )
    source_predictions = UnifiedPredictionFile.model_validate_json(
        arguments.source_predictions.read_text(encoding="utf-8")
    )
    raw_replay, normalized_replay, derived_replay, projection = (
        build_model_first_v3_replay(manifest, source_predictions)
    )
    report = evaluate_model_first_v3(
        manifest,
        source_predictions,
        raw_replay,
        normalized_replay,
        derived_replay,
        projection,
    )
    report["inputs"] = {
        "manifest": {
            "path": arguments.manifest.as_posix(),
            "sha256": _sha256(arguments.manifest),
        },
        "source_predictions": {
            "path": arguments.source_predictions.as_posix(),
            "sha256": _sha256(arguments.source_predictions),
        },
    }
    report["run"] = {
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "duration_ms": round((perf_counter() - started_clock) * 1000, 2),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "model_api_called": False,
        "model_call_count": 0,
    }

    _write_new_json(arguments.raw_replay, raw_replay)
    _write_new_json(arguments.normalized_replay, normalized_replay)
    _write_new_json(arguments.derived_replay, derived_replay)
    _write_new_json(arguments.projection, projection)
    _write_new_json(arguments.report, report)
    stages = report["stages"]
    print(
        "model-first v3 offline replay complete "
        f"cases={report['case_count']} calls=0 "
        f"raw_facts_f1={stages['raw']['facts']['macro_f1']:.4f} "
        f"normalized_facts_f1={stages['normalized']['facts']['macro_f1']:.4f} "
        f"derived_facts_f1={stages['derived']['facts']['macro_f1']:.4f} "
        f"hard_gate={'passed' if report['hard_gate']['passed'] else 'failed'}"
    )
    print(f"raw_replay={arguments.raw_replay}")
    print(f"normalized_replay={arguments.normalized_replay}")
    print(f"derived_replay={arguments.derived_replay}")
    print(f"projection={arguments.projection}")
    print(f"report={arguments.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
