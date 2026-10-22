from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.evaluate_unified_surface_items import build_report
from src.domain.unified_jd_surface_items_v2 import (
    SURFACE_ITEM_EXTRACTOR_VERSION,
    extract_surface_items,
)

DEFAULT_FIXTURE = Path("datasets/unified_jd_surface_v2_development_v1_2026-09-04.json")
DEFAULT_OUTPUT = Path(
    "artifacts/evaluation/unified-jd-surface-items-v2-development-2026-09-04.json"
)


def build_v2_report(fixture: dict[str, Any], fixture_path: Path) -> dict[str, Any]:
    report = build_report(
        fixture,
        fixture_path,
        extractor=extract_surface_items,
        extractor_version=SURFACE_ITEM_EXTRACTOR_VERSION,
    )
    report["report_version"] = "unified-jd-surface-v2-development-evaluation-v1"
    report["evaluation_scope"] = {
        "type": "development_fit_with_promoted_v1_holdout",
        "generalization_claim": False,
        "production_wiring": False,
        "case_count": len(fixture["scope"]["case_ids"]),
        "note": (
            "The revealed v1 holdout is development data for v2 and cannot be reused "
            "as a v2 generalization test."
        ),
    }
    report["development_sources"] = fixture["sources"]
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate v2 surface grammar on revealed development fixtures"
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    fixture = json.loads(arguments.fixture.read_text(encoding="utf-8"))
    report = build_v2_report(fixture, arguments.fixture)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    surface = report["surface_items"]["overall"]
    examples = report["examples"]["overall"]
    print(
        "v2 development evaluation complete "
        f"surface_exact={surface['exact_set_count']}/{surface['comparison_count']} "
        f"examples_exact={examples['exact_set_count']}/{examples['comparison_count']} "
        f"output={arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
