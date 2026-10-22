from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from src.evaluation.unified_models import UnifiedEvaluationManifest

DEFAULT_SKELETON = Path(
    "artifacts/evaluation/unified-jd-dev50-annotation-skeleton-v1-2026-09-03.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_annotation_batch(
    skeleton: dict[str, Any],
    labels: dict[str, Any],
) -> UnifiedEvaluationManifest:
    if labels.get("annotation_status") != "draft":
        raise ValueError("机器辅助标签文件必须使用 annotation_status=draft")
    skeleton_by_id = {case["id"]: case for case in skeleton["cases"]}
    labels_by_id = labels.get("cases")
    if not isinstance(labels_by_id, dict) or not labels_by_id:
        raise ValueError("标签文件必须包含非空 cases 对象")
    unknown_ids = sorted(set(labels_by_id) - set(skeleton_by_id))
    if unknown_ids:
        raise ValueError("标签包含未知 case: " + ", ".join(unknown_ids))

    cases = []
    for case_id, annotation in labels_by_id.items():
        source_case = skeleton_by_id[case_id]
        cases.append(
            {
                **source_case,
                "annotation_status": "draft",
                "expected": annotation["expected"],
                "coverage_tags": annotation.get("coverage_tags", []),
                "review_notes": annotation.get("review_notes", []),
            }
        )
    return UnifiedEvaluationManifest.model_validate(
        {
            **skeleton,
            "manifest_version": labels["label_version"],
            "dataset_version": labels["dataset_version"],
            "purpose": (
                "Unified dev-50 机器辅助标注草稿批次；只用于逐条复核，"
                "评测运行器必须拒绝计算成绩。"
            ),
            "label_status": "draft",
            "cases": cases,
        }
    )


def write_batch_manifest(
    *,
    skeleton_path: Path,
    labels_path: Path,
    output_path: Path,
) -> UnifiedEvaluationManifest:
    if _sha256(skeleton_path) != json.loads(
        labels_path.read_text(encoding="utf-8")
    ).get("source_skeleton_sha256"):
        raise ValueError("标签文件绑定的 source skeleton hash 不匹配")
    skeleton = json.loads(skeleton_path.read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    manifest = build_annotation_batch(skeleton, labels)
    rendered = manifest.model_dump_json(indent=2) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"refusing to overwrite changed file: {output_path}")
    output_path.write_text(rendered, encoding="utf-8")
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate one Unified dev-50 draft annotation batch"
    )
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skeleton", type=Path, default=DEFAULT_SKELETON)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    manifest = write_batch_manifest(
        skeleton_path=arguments.skeleton,
        labels_path=arguments.labels,
        output_path=arguments.output,
    )
    print(
        "unified annotation batch validated "
        f"cases={len(manifest.cases)} "
        f"status={manifest.label_status} "
        f"output={arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
