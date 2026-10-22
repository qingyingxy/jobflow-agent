from __future__ import annotations

import argparse
from pathlib import Path

from src.evaluation.unified_models import (
    UnifiedEvaluationManifest,
    UnifiedEvaluationThresholds,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = (
    ROOT / "artifacts/evaluation/unified-jd-dev50-frozen-v2-2026-09-04.json"
)
DEFAULT_OUTPUT = (
    ROOT / "artifacts/evaluation/unified-jd-model-first-v1-dev20-2026-09-05.json"
)
SELECTED_CASE_IDS = (
    "campus-ai-001",
    "campus-ai-008",
    "campus-ai-015",
    "campus-ai-023",
    "campus-ai-024",
    "campus-ai-027",
    "campus-ai-029",
    "campus-ai-032",
    "campus-ai-037",
    "campus-ai-078",
    "campus-ai-080",
    "campus-ai-097",
    "campus-ai-102",
    "campus-ai-116",
    "campus-ai-121",
    "campus-ai-011",
    "campus-ai-069",
    "campus-ai-072",
    "campus-ai-085",
    "campus-ai-091",
)


def build_manifest(source: UnifiedEvaluationManifest) -> UnifiedEvaluationManifest:
    cases_by_id = {case.id: case for case in source.cases}
    missing = sorted(set(SELECTED_CASE_IDS) - cases_by_id.keys())
    if missing:
        raise ValueError(f"source manifest is missing selected cases: {missing}")
    selected = [cases_by_id[case_id] for case_id in SELECTED_CASE_IDS]
    return UnifiedEvaluationManifest.model_validate(
        source.model_copy(
            update={
                "manifest_version": "unified-jd-model-first-v1-dev20",
                "dataset_version": "unified-jd-model-first-v1-dev20-2026-09-05",
                "purpose": (
                    "Revealed development baseline for the full-JD model-first parser. "
                    "Five cases cover the frozen canonical-item contract and fifteen "
                    "additional cases preserve broad category, level, relation, and "
                    "experience-qualifier coverage."
                ),
                "source_policy": (
                    "Derived without relabeling from the frozen dev-50 manifest. This is "
                    "development data only and makes no holdout or generalization claim."
                ),
                "thresholds": UnifiedEvaluationThresholds(
                    schema_valid_rate_min=1.0,
                    parse_success_rate_min=1.0,
                    unsupported_critical_fact_count_max=0,
                    evidence_localization_rate_min=1.0,
                ),
                "cases": selected,
            }
        ).model_dump(mode="python")
    )


def _write_new_or_identical(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise FileExistsError(f"refusing to overwrite changed manifest: {path}")
        return
    path.write_text(content, encoding="utf-8", newline="\n")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build model-first v1 dev-20 manifest")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    source = UnifiedEvaluationManifest.model_validate_json(
        arguments.source.read_text(encoding="utf-8")
    )
    manifest = build_manifest(source)
    _write_new_or_identical(
        arguments.output,
        manifest.model_dump_json(indent=2) + "\n",
    )
    print(f"model-first dev manifest built cases={len(manifest.cases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
