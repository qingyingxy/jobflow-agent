from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_product_jd_eval_dataset_v1 import (
    _display_path,
    _label_summary,
    _load_json,
    _sha256_file,
    _write_json,
    align_product_label_contract,
)

SOURCE_MANIFEST = ROOT / "datasets" / "product_jd_eval_split_v1_2026_09_06.json"
SOURCE_DEVELOPMENT = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-development70-v1-2026-09-06.json"
)
DEFAULT_MANIFEST = (
    ROOT / "datasets" / "product_jd_eval_split_v2_2026_09_06.json"
)
DEFAULT_DEVELOPMENT = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-development70-v2-2026-09-06.json"
)

DATASET_VERSION = "product-jd-eval-v2-2026-09-06"
LABEL_REVISION = "agent_contract_aligned_v2"


def build_development_revision(
    *,
    source_manifest_path: Path = SOURCE_MANIFEST,
    source_development_path: Path = SOURCE_DEVELOPMENT,
    manifest_path: Path = DEFAULT_MANIFEST,
    development_path: Path = DEFAULT_DEVELOPMENT,
) -> dict[str, Any]:
    """Revise development labels without opening or rewriting sealed content."""

    source_manifest = _load_json(source_manifest_path)
    source_development = _load_json(source_development_path)
    public_ids = [item["id"] for item in source_manifest["development"]["cases"]]
    development_ids = [item["id"] for item in source_development["cases"]]
    if public_ids != development_ids or len(development_ids) != 70:
        raise ValueError("Source development labels do not match the frozen manifest")

    revised_cases: list[dict[str, Any]] = []
    for case in source_development["cases"]:
        revised = deepcopy(case)
        revised["label_revision"] = LABEL_REVISION
        revised["expected"] = align_product_label_contract(
            case["expected"],
            case["raw_content"],
        )
        revised_cases.append(revised)

    development = {
        **source_development,
        "dataset_version": DATASET_VERSION,
        "label_revision": {
            "name": LABEL_REVISION,
            "method": "deterministic_contract_alignment",
            "human_reviewed": False,
        },
        "cases": revised_cases,
    }
    _write_json(development_path, development)

    manifest = deepcopy(source_manifest)
    manifest["dataset_version"] = DATASET_VERSION
    manifest["created_at"] = "2026-09-06"
    manifest["status"] = "selection_frozen_agent_label_revision_v2"
    manifest["label_revision"] = {
        "name": LABEL_REVISION,
        "human_reviewed": False,
        "changes": [
            "major_requirements contains hard constraints only",
            "preferred major text is retained as a preferred requirement",
            "generic standalone related-major values are removed",
            "fact values must be verbatim-supported by fact source_text",
        ],
        "sealed_test_policy": (
            "Sealed metadata is copied unchanged from the v1 public manifest. "
            "No sealed source text or labels are read or rewritten."
        ),
    }
    manifest["source_files"]["prior_product_manifest"] = {
        "path": _display_path(source_manifest_path),
        "sha256": _sha256_file(source_manifest_path),
    }
    manifest["source_files"]["prior_product_development"] = {
        "path": _display_path(source_development_path),
        "sha256": _sha256_file(source_development_path),
    }
    manifest["local_artifacts"]["development"] = {
        "path": _display_path(development_path),
        "sha256": _sha256_file(development_path),
    }
    manifest["development"]["label_summary"] = _label_summary(revised_cases)
    manifest["development"]["label_revision_status_counts"] = {
        LABEL_REVISION: 70,
        "human_reviewed_frozen": 0,
    }
    for item in manifest["development"]["cases"]:
        item["label_revision"] = LABEL_REVISION
    _write_json(manifest_path, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create Product JD development label revision v2"
    )
    parser.add_argument("--source-manifest", type=Path, default=SOURCE_MANIFEST)
    parser.add_argument("--source-development", type=Path, default=SOURCE_DEVELOPMENT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--development", type=Path, default=DEFAULT_DEVELOPMENT)
    args = parser.parse_args()
    manifest = build_development_revision(
        source_manifest_path=args.source_manifest,
        source_development_path=args.source_development,
        manifest_path=args.manifest,
        development_path=args.development,
    )
    print(
        json.dumps(
            {
                "dataset_version": manifest["dataset_version"],
                "development": manifest["development"]["case_count"],
                "sealed_test": manifest["sealed_test"]["case_count"],
                "sealed_source_read": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
