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
from src.evaluation.model_first_v2 import (
    build_model_first_v2_replay,
    evaluate_model_first_v2,
)
from src.evaluation.unified_models import (
    UnifiedEvaluationManifest,
    UnifiedPredictionFile,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPLAY = (
    ROOT / "artifacts/evaluation/unified-jd-model-first-v2-dev20-replay-2026-09-05.json"
)
DEFAULT_PROJECTION = (
    ROOT / "artifacts/evaluation/"
    "unified-jd-model-first-v2-dev20-surface-canonical-2026-09-05.json"
)
DEFAULT_REPORT = (
    ROOT / "artifacts/evaluation/unified-jd-model-first-v2-dev20-report-2026-09-05.json"
)


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
        description="Replay frozen model-first raw outputs with the conservative v2 compiler"
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source-predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--replay", type=Path, default=DEFAULT_REPLAY)
    parser.add_argument("--projection", type=Path, default=DEFAULT_PROJECTION)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    outputs = [arguments.replay, arguments.projection, arguments.report]
    existing = [str(path) for path in outputs if path.exists()]
    if existing:
        raise SystemExit(f"refusing to overwrite v2 artifacts: {existing}")

    started_at = datetime.now(UTC)
    started_clock = perf_counter()
    manifest = UnifiedEvaluationManifest.model_validate_json(
        arguments.manifest.read_text(encoding="utf-8")
    )
    source_predictions = UnifiedPredictionFile.model_validate_json(
        arguments.source_predictions.read_text(encoding="utf-8")
    )
    replay, projection = build_model_first_v2_replay(manifest, source_predictions)
    report = evaluate_model_first_v2(
        manifest,
        source_predictions,
        replay,
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

    _write_new_json(arguments.replay, replay)
    _write_new_json(arguments.projection, projection)
    _write_new_json(arguments.report, report)
    facts = report["facts"]["metrics"]
    clauses = report["clause_semantics"]
    surface = report["surface_items"]
    canonical = report["canonical_items"]["gold_exact_metrics"]["overall"]
    print(
        "model-first v2 offline replay complete "
        f"cases={report['case_count']} calls=0 "
        f"facts_f1={facts['macro_f1']:.4f} "
        f"category_f1={clauses['category']['overall']['f1']:.4f} "
        f"level_f1={clauses['level']['overall']['f1']:.4f} "
        f"relation_f1={clauses['relation']['overall']['f1']:.4f} "
        f"surface_exact={surface['exact_count']}/{surface['model_item_count']} "
        f"canonical_f1={canonical['f1']:.4f} "
        f"hard_gate={'passed' if report['hard_gate']['passed'] else 'failed'}"
    )
    print(f"replay={arguments.replay}")
    print(f"projection={arguments.projection}")
    print(f"report={arguments.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
