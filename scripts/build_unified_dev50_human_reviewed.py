from __future__ import annotations

import argparse
import copy
from pathlib import Path

from scripts.build_unified_dev50_review_candidate import (
    _apply_change,
    _load_json_object,
    _sha256,
)
from src.evaluation.unified_models import UnifiedEvaluationManifest

DEFAULT_CANDIDATE = Path(
    "artifacts/evaluation/"
    "unified-jd-dev50-review-candidate-v1-2026-09-04.json"
)
DEFAULT_DECISIONS = Path(
    "datasets/unified_jd_dev50_human_review_round2_decisions_v1_2026_09_04.json"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evaluation/unified-jd-dev50-human-reviewed-v1-2026-09-04.json"
)

ROUND2_REVIEW_NOTE = (
    "第二轮独立语义复核已完成；按项目负责人授权，"
    "无争议项由既有标注规则直接确认。"
)


def build_human_reviewed_manifest(
    *,
    candidate_path: Path,
    decisions_path: Path,
) -> UnifiedEvaluationManifest:
    actual_candidate_hash = _sha256(candidate_path)
    candidate = _load_json_object(candidate_path)
    review = _load_json_object(decisions_path)

    if review.get("source_candidate_sha256") != actual_candidate_hash:
        raise ValueError(
            "round-2 decisions are bound to a different candidate: "
            f"expected {review.get('source_candidate_sha256')}, "
            f"got {actual_candidate_hash}"
        )
    if review.get("status") != "round2_complete":
        raise ValueError("round-2 decision file must have status=round2_complete")
    if review.get("user_confirmation_required") != []:
        raise ValueError("round-2 review still contains unresolved decisions")
    if candidate.get("label_status") != "draft":
        raise ValueError("round-2 source candidate must have label_status=draft")

    cases = candidate.get("cases")
    reviewed_case_ids = review.get("reviewed_case_ids")
    changes = review.get("changes")
    if not isinstance(cases, list) or not isinstance(reviewed_case_ids, list):
        raise TypeError("candidate cases and reviewed_case_ids must be present")
    if not isinstance(changes, dict):
        raise TypeError("round-2 changes must be an object")

    case_ids = [case["id"] for case in cases]
    if len(case_ids) != 50 or len(case_ids) != len(set(case_ids)):
        raise ValueError("Unified dev-50 candidate must contain 50 unique cases")
    if len(reviewed_case_ids) != len(set(reviewed_case_ids)):
        raise ValueError("round-2 reviewed_case_ids must be unique")
    if set(reviewed_case_ids) != set(case_ids):
        missing = sorted(set(case_ids) - set(reviewed_case_ids))
        extra = sorted(set(reviewed_case_ids) - set(case_ids))
        raise ValueError(
            f"round-2 review coverage mismatch: missing={missing}, extra={extra}"
        )
    unknown_change_ids = sorted(set(changes) - set(case_ids))
    if unknown_change_ids:
        raise ValueError(f"round-2 changes contain unknown cases: {unknown_change_ids}")

    manifest = copy.deepcopy(candidate)
    manifest["manifest_version"] = "unified-jd-dev50-human-reviewed-v1"
    manifest["dataset_version"] = "unified-jd-dev50-human-reviewed-v1-2026-09-04"
    manifest["purpose"] = (
        "Unified dev-50 两轮语义复核完成的 human-reviewed 标签；"
        "冻结前只用于标签校验，不得作为 frozen 基准。"
    )
    manifest["label_status"] = "human_reviewed"

    cases_by_id = {case["id"]: case for case in manifest["cases"]}
    for case_id in case_ids:
        case = cases_by_id[case_id]
        for change in changes.get(case_id, []):
            if not isinstance(change, dict):
                raise TypeError(f"{case_id} round-2 change must be an object")
            _apply_change(case, change)
        case["annotation_status"] = "human_reviewed"
        case.setdefault("review_notes", []).append(ROUND2_REVIEW_NOTE)

    return UnifiedEvaluationManifest.model_validate(manifest)


def write_human_reviewed_manifest(
    *,
    candidate_path: Path,
    decisions_path: Path,
    output_path: Path,
) -> UnifiedEvaluationManifest:
    manifest = build_human_reviewed_manifest(
        candidate_path=candidate_path,
        decisions_path=decisions_path,
    )
    rendered = manifest.model_dump_json(indent=2) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"refusing to overwrite changed file: {output_path}")
    output_path.write_text(rendered, encoding="utf-8")
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply round-2 decisions and build human-reviewed dev-50 labels"
    )
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    manifest = write_human_reviewed_manifest(
        candidate_path=arguments.candidate,
        decisions_path=arguments.decisions,
        output_path=arguments.output,
    )
    print(
        "unified dev-50 human-reviewed labels validated "
        f"cases={len(manifest.cases)} "
        f"status={manifest.label_status} "
        f"sha256={_sha256(arguments.output)} "
        f"output={arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
