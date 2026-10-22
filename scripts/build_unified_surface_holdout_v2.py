from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.build_unified_surface_holdout import build_selection

DEFAULT_MANIFEST = Path(
    "artifacts/evaluation/unified-jd-dev50-frozen-v2-2026-09-04.json"
)
DEFAULT_RULES = Path("src/domain/unified_jd_surface_items_v2.py")
DEFAULT_FREEZE_RECEIPT = Path(
    "datasets/unified_jd_surface_rules_freeze_v2_2026-09-04.json"
)
DEFAULT_OUTPUT = Path(
    "datasets/unified_jd_surface_holdout_selection_v2_2026-09-04.json"
)
SELECTION_VERSION = "unified-jd-surface-holdout-selection-v2"


def _write_immutable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise FileExistsError(f"refusing to overwrite changed v2 selection: {path}")
    path.write_text(content, encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the deterministic v2 Unified JD surface holdout"
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    selection = build_selection(
        manifest_path=arguments.manifest,
        rules_path=arguments.rules,
        freeze_receipt_path=arguments.freeze_receipt,
        selection_version=SELECTION_VERSION,
        fixture_id_prefix="surface-holdout-v2",
        global_unique_assignment=True,
    )
    _write_immutable(
        arguments.output,
        json.dumps(selection, ensure_ascii=False, indent=2) + "\n",
    )
    print(
        "v2 surface holdout selection frozen "
        f"fixtures={len(selection['fixtures'])} "
        f"cases={len(selection['selected_case_ids'])} "
        f"output={arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
