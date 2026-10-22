from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-06"
PREREGISTRATION = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_compatibility_preregistration_v1_2026-09-06.json"
)
PREREGISTRATION_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_compatibility_preregistration_freeze_v1_2026-09-06.json"
)
SOURCE_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_compatibility_source_freeze_v1_2026-09-06.json"
)
SOURCES = {
    "compatibility_adapter": (
        ROOT / "src/services/unified_jd_flat_atomic_v4_compatibility.py"
    ),
    "compatibility_evaluator": (
        ROOT / "src/evaluation/model_first_v4_1_compatibility.py"
    ),
    "gate_runner": (
        ROOT / "scripts/evaluate_unified_jd_flat_atomic_v4_1_compatibility_gates.py"
    ),
    "tests": ROOT / "tests/test_unified_jd_flat_atomic_v4_compatibility.py",
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


def _verify_references(entries: dict[str, Any]) -> None:
    for name, entry in entries.items():
        path = ROOT / entry["path"]
        if not path.is_file() or _sha256(path) != entry["sha256"]:
            raise ValueError(f"frozen input hash mismatch: {name}")


def main() -> int:
    if SOURCE_FREEZE.exists():
        raise FileExistsError(f"source freeze already exists: {SOURCE_FREEZE}")
    missing = [str(path) for path in SOURCES.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing implementation source: {missing}")
    preregistration = _load(PREREGISTRATION)
    preregistration_freeze = _load(PREREGISTRATION_FREEZE)
    _verify_references(preregistration["frozen_inputs"])
    _verify_references(preregistration_freeze["artifacts"])
    freeze = {
        "freeze_version": (
            "unified-jd-flat-atomic-v4.1-compatibility-source-freeze-v1"
        ),
        "frozen_at": datetime.now(UTC).isoformat(),
        "status": "frozen_before_formal_gate_execution",
        "preregistration_sha256": _sha256(PREREGISTRATION),
        "artifacts": {
            name: _reference(path) for name, path in SOURCES.items()
        },
        "frozen_inputs": preregistration["frozen_inputs"],
        "new_model_call_count": 0,
        "network_call_count": 0,
        "immutability": (
            "Any source, test, input, intervention, or threshold change invalidates "
            "the one-time v4.1 compatibility gate execution."
        ),
    }
    SOURCE_FREEZE.parent.mkdir(parents=True, exist_ok=True)
    with SOURCE_FREEZE.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(freeze, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(f"source_freeze={SOURCE_FREEZE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
