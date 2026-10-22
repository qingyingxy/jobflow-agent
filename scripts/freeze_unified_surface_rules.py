from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from src.domain.unified_jd_surface_items import SURFACE_ITEM_EXTRACTOR_VERSION

DEFAULT_RULES = Path("src/domain/unified_jd_surface_items.py")
DEFAULT_CONTRACT = Path("docs/CANONICAL_ITEMS_CONTRACT_V1.md")
DEFAULT_DEVELOPMENT_FIXTURE = Path(
    "datasets/unified_jd_canonical_items_contract_v1.json"
)
DEFAULT_DEVELOPMENT_REPORT = Path(
    "artifacts/evaluation/unified-jd-surface-items-prototype-v1-2026-09-04.json"
)
DEFAULT_RECEIPT = Path("datasets/unified_jd_surface_rules_freeze_v1_2026-09-04.json")
FREEZE_VERSION = "unified-jd-surface-rules-freeze-v1"
HOLDOUT_SELECTION_VERSION = "unified-jd-surface-holdout-selection-v1"
HOLDOUT_GATES: dict[str, float | int] = {
    "surface_items_f1_min": 0.85,
    "surface_exact_set_rate_min": 0.70,
    "examples_f1_min": 0.80,
    "unanchored_output_count_max": 0,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_immutable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise FileExistsError(f"refusing to overwrite changed freeze receipt: {path}")
    path.write_text(content, encoding="utf-8")


def build_receipt(
    *,
    rules_path: Path,
    contract_path: Path,
    development_fixture_path: Path,
    development_report_path: Path,
) -> dict[str, Any]:
    development_fixture = json.loads(
        development_fixture_path.read_text(encoding="utf-8")
    )
    development_report = json.loads(development_report_path.read_text(encoding="utf-8"))
    if development_report["extractor_version"] != SURFACE_ITEM_EXTRACTOR_VERSION:
        raise ValueError("development report does not use the rules being frozen")
    if development_report["model_call_count"] != 0:
        raise ValueError("surface-rule freeze requires an offline development report")
    if development_report["surface_items"]["overall"]["exact_set_rate"] != 1.0:
        raise ValueError("development fixtures must pass before freezing rules")

    return {
        "freeze_version": FREEZE_VERSION,
        "status": "frozen",
        "frozen_at": "2026-09-04",
        "extractor_version": SURFACE_ITEM_EXTRACTOR_VERSION,
        "frozen_rules": {
            "path": rules_path.as_posix(),
            "sha256": _sha256(rules_path),
        },
        "contract": {
            "path": contract_path.as_posix(),
            "sha256": _sha256(contract_path),
            "version": development_fixture["contract_version"],
        },
        "development_fixture": {
            "path": development_fixture_path.as_posix(),
            "sha256": _sha256(development_fixture_path),
            "case_ids": development_fixture["scope"]["case_ids"],
            "fixture_count": development_fixture["scope"]["fixture_count"],
        },
        "development_report": {
            "path": development_report_path.as_posix(),
            "sha256": _sha256(development_report_path),
            "surface_exact_set_rate": development_report["surface_items"]["overall"][
                "exact_set_rate"
            ],
            "examples_exact_set_rate": development_report["examples"]["overall"][
                "exact_set_rate"
            ],
        },
        "holdout_protocol": {
            "selection_version": HOLDOUT_SELECTION_VERSION,
            "fixture_count": 20,
            "fixtures_per_category": 5,
            "exclude_development_case_ids": True,
            "unique_case_per_fixture": True,
            "selection_method": (
                "SHA-256 rank of selection version, case id, clause index, and source "
                "content hash; category-balanced without replacement"
            ),
            "labels_visible_during_rule_development": False,
            "rules_may_change_after_selection": False,
            "gates": HOLDOUT_GATES,
        },
        "immutability_policy": (
            "Any rule change requires a new extractor and freeze version. The v1 "
            "holdout result must not be used to edit this frozen rules file."
        ),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze Unified JD surface-item rules")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument(
        "--development-fixture", type=Path, default=DEFAULT_DEVELOPMENT_FIXTURE
    )
    parser.add_argument(
        "--development-report", type=Path, default=DEFAULT_DEVELOPMENT_REPORT
    )
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    receipt = build_receipt(
        rules_path=arguments.rules,
        contract_path=arguments.contract,
        development_fixture_path=arguments.development_fixture,
        development_report_path=arguments.development_report,
    )
    _write_immutable(
        arguments.receipt,
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
    )
    print(
        "surface rules frozen "
        f"version={receipt['extractor_version']} "
        f"sha256={receipt['frozen_rules']['sha256']} "
        f"receipt={arguments.receipt}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
