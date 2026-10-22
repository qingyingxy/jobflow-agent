from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from src.evaluation.unified_models import UnifiedEvaluationManifest

DEFAULT_SOURCE = Path(
    "artifacts/evaluation/unified-jd-dev50-human-reviewed-v1-2026-09-04.json"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evaluation/unified-jd-dev50-frozen-v1-2026-09-04.json"
)
DEFAULT_RECEIPT = Path(
    "datasets/unified_jd_dev50_freeze_receipt_v1_2026_09_04.json"
)
EXPECTED_SOURCE_SHA256 = (
    "d3edc8b3dc448e499236987d61e322112ebca594a481320f28bd4ec61cc02b0f"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_immutable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise FileExistsError(f"refusing to overwrite changed file: {path}")
    path.write_text(content, encoding="utf-8")


def build_frozen_manifest(source_path: Path) -> UnifiedEvaluationManifest:
    actual_source_hash = _sha256(source_path)
    if actual_source_hash != EXPECTED_SOURCE_SHA256:
        raise ValueError(
            "human-reviewed labels changed after approval: "
            f"expected {EXPECTED_SOURCE_SHA256}, got {actual_source_hash}"
        )

    payload: dict[str, Any] = json.loads(source_path.read_text(encoding="utf-8"))
    reviewed = UnifiedEvaluationManifest.model_validate(payload)
    if reviewed.label_status != "human_reviewed":
        raise ValueError("freeze source must have label_status=human_reviewed")
    if len(reviewed.cases) != 50 or any(
        case.annotation_status != "human_reviewed" for case in reviewed.cases
    ):
        raise ValueError("freeze source must contain 50 human-reviewed cases")

    frozen = copy.deepcopy(payload)
    frozen["manifest_version"] = "unified-jd-dev50-frozen-v1"
    frozen["dataset_version"] = "unified-jd-dev50-frozen-v1-2026-09-04"
    frozen["purpose"] = (
        "Unified dev-50 两轮复核后冻结的 Parser 评测真值；"
        "只允许通过新版本修订，不得原地改写。"
    )
    frozen["label_status"] = "frozen"
    for case in frozen["cases"]:
        case["annotation_status"] = "frozen"
        case.setdefault("review_notes", []).append(
            "两轮复核完成后于 2026-09-04 冻结；后续修订必须新建版本。"
        )
    return UnifiedEvaluationManifest.model_validate(frozen)


def write_frozen_manifest(
    *,
    source_path: Path,
    output_path: Path,
    receipt_path: Path,
) -> UnifiedEvaluationManifest:
    manifest = build_frozen_manifest(source_path)
    rendered = manifest.model_dump_json(indent=2) + "\n"
    _write_immutable(output_path, rendered)

    receipt = {
        "freeze_version": "unified-jd-dev50-freeze-receipt-v1",
        "status": "frozen",
        "frozen_at": "2026-09-04",
        "case_count": len(manifest.cases),
        "schema_version": manifest.schema_version,
        "source": {
            "path": source_path.as_posix(),
            "sha256": _sha256(source_path),
            "label_status": "human_reviewed",
        },
        "frozen_artifact": {
            "path": output_path.as_posix(),
            "sha256": _sha256(output_path),
            "label_status": "frozen",
        },
        "immutability_policy": "修订时新建版本，不覆盖本文件引用的冻结标签。",
    }
    _write_immutable(
        receipt_path,
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
    )
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze the approved Unified dev-50 labels and write a receipt"
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    manifest = write_frozen_manifest(
        source_path=arguments.source,
        output_path=arguments.output,
        receipt_path=arguments.receipt,
    )
    print(
        "unified dev-50 labels frozen "
        f"cases={len(manifest.cases)} "
        f"sha256={_sha256(arguments.output)} "
        f"output={arguments.output} "
        f"receipt={arguments.receipt}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
