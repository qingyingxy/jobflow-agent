from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

DEFAULT_CONTRACT = Path("datasets/unified_jd_canonical_items_contract_v1.json")
DEFAULT_PROMOTED_HOLDOUT = Path(
    "datasets/unified_jd_surface_holdout_labels_v1_2026-09-04.json"
)
DEFAULT_PROMOTED_FREEZE = Path(
    "datasets/unified_jd_surface_holdout_label_freeze_v1_2026-09-04.json"
)
DEFAULT_PROMOTED_REPORT = Path(
    "artifacts/evaluation/unified-jd-surface-holdout-v1-2026-09-04.json"
)
DEFAULT_OUTPUT = Path("datasets/unified_jd_surface_v2_development_v1_2026-09-04.json")
DEVELOPMENT_VERSION = "unified-jd-surface-v2-development-v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_immutable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise FileExistsError(
            f"refusing to overwrite changed v2 development set: {path}"
        )
    path.write_text(content, encoding="utf-8")


def build_development_set(
    *,
    contract_path: Path,
    promoted_holdout_path: Path,
    promoted_freeze_path: Path,
    promoted_report_path: Path,
) -> dict[str, Any]:
    contract: dict[str, Any] = json.loads(contract_path.read_text(encoding="utf-8"))
    promoted: dict[str, Any] = json.loads(
        promoted_holdout_path.read_text(encoding="utf-8")
    )
    promoted_freeze: dict[str, Any] = json.loads(
        promoted_freeze_path.read_text(encoding="utf-8")
    )
    promoted_report: dict[str, Any] = json.loads(
        promoted_report_path.read_text(encoding="utf-8")
    )

    if promoted_freeze["files"]["labels"]["sha256"] != _sha256(promoted_holdout_path):
        raise ValueError("promoted holdout labels differ from their freeze")
    if promoted_report["gate"]["passed"]:
        raise ValueError("only a failed revealed holdout should be promoted")
    if promoted_report["provenance"]["label_freeze"]["sha256"] != _sha256(
        promoted_freeze_path
    ):
        raise ValueError("promoted holdout report does not match its label freeze")

    fixtures = [*contract["fixtures"], *promoted["fixtures"]]
    case_ids = sorted({item["case_id"] for item in fixtures})
    categories = sorted({item["category"] for item in fixtures})
    category_counts = Counter(item["category"] for item in fixtures)
    if len(fixtures) != 40 or len(case_ids) != 25:
        raise ValueError("v2 development set must contain 40 fixtures from 25 cases")
    if set(category_counts.values()) != {10}:
        raise ValueError("v2 development set must contain 10 fixtures per category")

    return {
        "development_version": DEVELOPMENT_VERSION,
        "contract_version": contract["contract_version"],
        "status": "development_only_revealed",
        "built_at": "2026-09-04",
        "model_call_count": 0,
        "sources": {
            "original_contract": {
                "path": contract_path.as_posix(),
                "sha256": _sha256(contract_path),
                "fixture_count": len(contract["fixtures"]),
            },
            "promoted_v1_holdout_labels": {
                "path": promoted_holdout_path.as_posix(),
                "sha256": _sha256(promoted_holdout_path),
                "fixture_count": len(promoted["fixtures"]),
            },
            "promoted_v1_holdout_freeze": {
                "path": promoted_freeze_path.as_posix(),
                "sha256": _sha256(promoted_freeze_path),
            },
            "promoted_v1_holdout_report": {
                "path": promoted_report_path.as_posix(),
                "sha256": _sha256(promoted_report_path),
                "gate_passed": promoted_report["gate"]["passed"],
            },
        },
        "scope": {
            "case_ids": case_ids,
            "categories": categories,
            "fixture_count": len(fixtures),
            "fixtures_per_category": dict(sorted(category_counts.items())),
        },
        "fixtures": fixtures,
        "evaluation_policy": (
            "This revealed set may be used for v2 development but must not be used "
            "as the v2 generalization holdout."
        ),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the revealed 40-fixture v2 surface development set"
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument(
        "--promoted-holdout", type=Path, default=DEFAULT_PROMOTED_HOLDOUT
    )
    parser.add_argument("--promoted-freeze", type=Path, default=DEFAULT_PROMOTED_FREEZE)
    parser.add_argument("--promoted-report", type=Path, default=DEFAULT_PROMOTED_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    development_set = build_development_set(
        contract_path=arguments.contract,
        promoted_holdout_path=arguments.promoted_holdout,
        promoted_freeze_path=arguments.promoted_freeze,
        promoted_report_path=arguments.promoted_report,
    )
    _write_immutable(
        arguments.output,
        json.dumps(development_set, ensure_ascii=False, indent=2) + "\n",
    )
    print(
        "v2 surface development set built "
        f"fixtures={development_set['scope']['fixture_count']} "
        f"cases={len(development_set['scope']['case_ids'])} "
        f"output={arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
