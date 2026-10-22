from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from src.domain.unified_jd import UNIFIED_JD_GRANULARITY_VERSION
from src.evaluation.unified_models import UnifiedEvaluationManifest

DEFAULT_SOURCE = Path(
    "artifacts/evaluation/unified-jd-dev50-frozen-v1-2026-09-04.json"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evaluation/unified-jd-dev50-frozen-v2-2026-09-04.json"
)
DEFAULT_RECEIPT = Path(
    "datasets/unified_jd_dev50_freeze_receipt_v2_2026_09_04.json"
)
EXPECTED_SOURCE_SHA256 = (
    "d4d3959009825f4b36448434df0b01d5e0c73eae343df12aa2a62a6715d2cbe7"
)
ALIGNED_FIELDS = ("education_requirements", "major_requirements")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_immutable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise FileExistsError(f"refusing to overwrite changed file: {path}")
    path.write_text(content, encoding="utf-8")


def _ordered_clause_items(expected: dict[str, Any], field_name: str) -> list[str]:
    return list(
        dict.fromkeys(
            item
            for clause in expected["clauses"]
            if clause.get("fact_field") == field_name
            for item in clause["items"]
        )
    )


def build_granularity_v2_manifest(
    source_path: Path = DEFAULT_SOURCE,
) -> tuple[UnifiedEvaluationManifest, dict[str, Any]]:
    source_hash = _sha256(source_path)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise ValueError(
            "frozen v1 labels changed before granularity migration: "
            f"expected {EXPECTED_SOURCE_SHA256}, got {source_hash}"
        )

    source_payload: dict[str, Any] = json.loads(
        source_path.read_text(encoding="utf-8")
    )
    source = UnifiedEvaluationManifest.model_validate(source_payload)
    if source.label_status != "frozen" or len(source.cases) != 50:
        raise ValueError("granularity v2 source must be the frozen dev-50 v1 manifest")

    revised = copy.deepcopy(source_payload)
    revised["manifest_version"] = "unified-jd-dev50-frozen-v2"
    revised["dataset_version"] = "unified-jd-dev50-frozen-v2-2026-09-04"
    revised["annotation_guide_version"] = UNIFIED_JD_GRANULARITY_VERSION
    revised["purpose"] = (
        "Unified dev-50 粒度统一后的冻结 Parser 评测真值；学历与专业 facts "
        "按语义原子拆分，并与对应 fact clause items 完全一致。"
    )

    changed_by_field: dict[str, list[str]] = {field: [] for field in ALIGNED_FIELDS}
    changed_case_ids: list[str] = []
    for case in revised["cases"]:
        expected = case["expected"]
        changed_fields: list[str] = []
        for field_name in ALIGNED_FIELDS:
            previous = expected["facts"][field_name]
            if previous is None:
                continue
            aligned = _ordered_clause_items(expected, field_name)
            if not aligned:
                raise ValueError(
                    f"{case['id']}: populated {field_name} has no fact clause"
                )
            if previous != aligned:
                expected["facts"][field_name] = aligned
                changed_fields.append(field_name)
                changed_by_field[field_name].append(case["id"])
        if changed_fields:
            changed_case_ids.append(case["id"])
            case.setdefault("review_notes", []).append(
                "粒度 v2 确定性迁移：facts."
                + "、facts.".join(changed_fields)
                + " 改为复用已人工复核 fact clause 的原子 items；原文、证据、"
                "clause 语义和强度均未修改。"
            )

    manifest = UnifiedEvaluationManifest.model_validate(revised)
    summary = {
        "migration_version": UNIFIED_JD_GRANULARITY_VERSION,
        "case_count": len(manifest.cases),
        "changed_case_count": len(changed_case_ids),
        "changed_case_ids": changed_case_ids,
        "changed_fields": {
            field: {
                "case_count": len(case_ids),
                "case_ids": case_ids,
            }
            for field, case_ids in changed_by_field.items()
        },
    }
    return manifest, summary


def write_granularity_v2_manifest(
    *,
    source_path: Path = DEFAULT_SOURCE,
    output_path: Path = DEFAULT_OUTPUT,
    receipt_path: Path = DEFAULT_RECEIPT,
) -> tuple[UnifiedEvaluationManifest, dict[str, Any]]:
    manifest, summary = build_granularity_v2_manifest(source_path)
    _write_immutable(output_path, manifest.model_dump_json(indent=2) + "\n")
    receipt = {
        "freeze_version": "unified-jd-dev50-freeze-receipt-v2",
        "status": "frozen",
        "frozen_at": "2026-09-04",
        "schema_version": manifest.schema_version,
        "annotation_guide_version": manifest.annotation_guide_version,
        "source": {
            "path": source_path.as_posix(),
            "sha256": _sha256(source_path),
            "label_status": "frozen",
        },
        "frozen_artifact": {
            "path": output_path.as_posix(),
            "sha256": _sha256(output_path),
            "label_status": "frozen",
        },
        "migration_summary": summary,
        "immutability_policy": "粒度修订已新建 v2；不得覆盖 v1 或本 v2 文件。",
    }
    _write_immutable(
        receipt_path,
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
    )
    return manifest, summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build frozen dev-50 v2 labels with aligned fact granularity"
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    manifest, summary = write_granularity_v2_manifest(
        source_path=arguments.source,
        output_path=arguments.output,
        receipt_path=arguments.receipt,
    )
    print(
        "unified dev-50 granularity v2 frozen "
        f"cases={len(manifest.cases)} "
        f"changed_cases={summary['changed_case_count']} "
        f"sha256={_sha256(arguments.output)} "
        f"output={arguments.output} receipt={arguments.receipt}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
