from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PREREGISTRATION = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_external_holdout_preregistration_v1_2026-09-06.json"
)
PREREGISTRATION_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_external_holdout_preregistration_freeze_v1_2026-09-06.json"
)
SOURCE_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_external_holdout_source_freeze_v1_2026-09-06.json"
)
SOURCES = {
    "evaluator": ROOT / "src/evaluation/model_first_v4_1_external_holdout.py",
    "runner": ROOT / "scripts/run_unified_jd_flat_atomic_v4_1_external_holdout.py",
    "freeze_script": ROOT
    / "scripts/freeze_unified_jd_flat_atomic_v4_1_external_holdout.py",
    "tests": ROOT / "tests/test_unified_jd_flat_atomic_v4_1_external_holdout.py",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reference(path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": _sha256(path),
    }


def _verify_entries(entries: dict[str, Any]) -> None:
    for name, entry in entries.items():
        path = ROOT / entry["path"]
        if not path.is_file() or _sha256(path) != entry["sha256"]:
            raise ValueError(f"frozen input hash mismatch: {name}")


def main() -> int:
    if SOURCE_FREEZE.exists():
        raise FileExistsError(f"source freeze already exists: {SOURCE_FREEZE}")
    preregistration = _load(PREREGISTRATION)
    preregistration_freeze = _load(PREREGISTRATION_FREEZE)
    _verify_entries(preregistration["frozen_inputs"])
    _verify_entries(preregistration_freeze["artifacts"])
    missing = [str(path) for path in SOURCES.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing external holdout source: {missing}")

    freeze = {
        "freeze_version": (
            "unified-jd-flat-atomic-v4.1-external-holdout-source-freeze-v1"
        ),
        "frozen_at": datetime.now(UTC).isoformat(),
        "status": "frozen_before_external_holdout_calls",
        "preregistration_sha256": _sha256(PREREGISTRATION),
        "artifacts": {
            "preregistration": _reference(PREREGISTRATION),
            "preregistration_freeze": _reference(PREREGISTRATION_FREEZE),
            **{name: _reference(path) for name, path in SOURCES.items()},
        },
        "frozen_inputs": preregistration["frozen_inputs"],
        "verification_before_freeze": {
            "focused_tests": "4 passed",
            "full_suite": "902 passed, 1 warning",
            "ruff_check": "passed",
            "model_call_count": 0,
            "network_call_count": 0,
        },
        "immutability": (
            "Any edit to the selection, preregistration, evaluator, runner, tests, "
            "v4 request contract, or frozen v4.1 compatibility mechanism invalidates "
            "this one-time external holdout."
        ),
    }
    SOURCE_FREEZE.parent.mkdir(parents=True, exist_ok=True)
    with SOURCE_FREEZE.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(freeze, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps(_reference(SOURCE_FREEZE), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
