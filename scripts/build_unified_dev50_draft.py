from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.build_unified_annotation_batch import build_annotation_batch
from src.evaluation.unified_models import UnifiedEvaluationManifest

DEFAULT_SKELETON = Path(
    "artifacts/evaluation/unified-jd-dev50-annotation-skeleton-v1-2026-09-03.json"
)
DEFAULT_LABELS = tuple(
    Path(
        "datasets/"
        f"unified_jd_dev50_draft_batch{index:02d}_v1_2026_09_03.json"
    )
    for index in range(1, 11)
)
DEFAULT_OUTPUT = Path(
    "artifacts/evaluation/unified-jd-dev50-draft-v1-2026-09-03.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def merge_annotation_batches(
    skeleton: dict[str, Any],
    label_batches: list[dict[str, Any]],
    *,
    source_skeleton_sha256: str | None = None,
) -> UnifiedEvaluationManifest:
    if not label_batches:
        raise ValueError("至少需要一个标注批次")

    skeleton_ids = [case["id"] for case in skeleton["cases"]]
    skeleton_id_set = set(skeleton_ids)
    annotations: dict[str, Any] = {}
    duplicate_ids: set[str] = set()

    for index, batch in enumerate(label_batches, start=1):
        if batch.get("annotation_status") != "draft":
            raise ValueError(f"标注批次 {index} 必须使用 annotation_status=draft")
        if (
            source_skeleton_sha256 is not None
            and batch.get("source_skeleton_sha256") != source_skeleton_sha256
        ):
            raise ValueError(f"标注批次 {index} 绑定的 source skeleton hash 不匹配")
        batch_cases = batch.get("cases")
        if not isinstance(batch_cases, dict) or not batch_cases:
            raise ValueError(f"标注批次 {index} 必须包含非空 cases 对象")
        for case_id, annotation in batch_cases.items():
            if case_id in annotations:
                duplicate_ids.add(case_id)
            else:
                annotations[case_id] = annotation

    if duplicate_ids:
        raise ValueError("标注批次包含重复 case: " + ", ".join(sorted(duplicate_ids)))
    unknown_ids = sorted(set(annotations) - skeleton_id_set)
    if unknown_ids:
        raise ValueError("标注批次包含未知 case: " + ", ".join(unknown_ids))
    missing_ids = sorted(skeleton_id_set - set(annotations))
    if missing_ids:
        raise ValueError("标注批次缺少 case: " + ", ".join(missing_ids))

    ordered_annotations = {case_id: annotations[case_id] for case_id in skeleton_ids}
    manifest = build_annotation_batch(
        skeleton,
        {
            "label_version": "unified-jd-dev50-draft-v1",
            "dataset_version": "unified-jd-dev50-draft-v1-2026-09-03",
            "annotation_status": "draft",
            "cases": ordered_annotations,
        },
    )
    payload = manifest.model_dump(mode="json")
    payload["purpose"] = (
        "Unified dev-50 完整机器辅助标注草稿；只用于人工逐条复核，"
        "评测运行器必须拒绝计算成绩。"
    )
    return UnifiedEvaluationManifest.model_validate(payload)


def write_dev50_draft(
    *,
    skeleton_path: Path,
    label_paths: list[Path],
    output_path: Path,
) -> UnifiedEvaluationManifest:
    skeleton_hash = _sha256(skeleton_path)
    skeleton = json.loads(skeleton_path.read_text(encoding="utf-8"))
    label_batches = [
        json.loads(path.read_text(encoding="utf-8")) for path in label_paths
    ]
    manifest = merge_annotation_batches(
        skeleton,
        label_batches,
        source_skeleton_sha256=skeleton_hash,
    )
    if len(manifest.cases) != 50:
        raise ValueError("dev-50 完整草稿必须包含 50 个 case")

    rendered = manifest.model_dump_json(indent=2) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"refusing to overwrite changed file: {output_path}")
    output_path.write_text(rendered, encoding="utf-8")
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge and validate all Unified dev-50 draft annotation batches"
    )
    parser.add_argument("--skeleton", type=Path, default=DEFAULT_SKELETON)
    parser.add_argument("--labels", type=Path, nargs="+", default=DEFAULT_LABELS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    manifest = write_dev50_draft(
        skeleton_path=arguments.skeleton,
        label_paths=list(arguments.labels),
        output_path=arguments.output,
    )
    print(
        "unified dev-50 draft validated "
        f"cases={len(manifest.cases)} "
        f"status={manifest.label_status} "
        f"output={arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
