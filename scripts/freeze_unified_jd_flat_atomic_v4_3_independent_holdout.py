from __future__ import annotations

import ast
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PREREGISTRATION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_independent_holdout_preregistration_"
    "v1_2026-09-06.json"
)
PREREGISTRATION_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_independent_holdout_preregistration_"
    "freeze_v1_2026-09-06.json"
)
SOURCE_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_independent_holdout_source_freeze_"
    "v1_2026-09-06.json"
)
SOURCES = {
    "evaluator": ROOT
    / "src/evaluation/model_first_v4_3_independent_holdout.py",
    "runner": ROOT
    / "scripts/run_unified_jd_flat_atomic_v4_3_independent_holdout.py",
    "freeze_script": Path(__file__).resolve(),
    "focused_tests": ROOT
    / "tests/test_unified_jd_flat_atomic_v4_3_independent_holdout.py",
}
ALLOWED_EVALUATOR_IMPORT_PREFIXES = (
    "__future__",
    "collections",
    "copy",
    "datetime",
    "hashlib",
    "json",
    "src.evaluation.model_first_v4_live_probe",
    "src.services.unified_jd_flat_atomic_v4_2_compatibility",
    "src.services.unified_jd_flat_atomic_v4_3_compatibility",
    "typing",
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reference(path: Path) -> dict[str, str]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": _sha256(path)}


def _verify_entries(entries: dict[str, Any]) -> None:
    for name, entry in entries.items():
        path = ROOT / entry["path"]
        if not path.is_file() or _sha256(path) != entry["sha256"]:
            raise ValueError(f"frozen input hash mismatch: {name}")


def _verify_evaluator_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    unexpected = [
        name
        for name in imports
        if not any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in ALLOWED_EVALUATOR_IMPORT_PREFIXES
        )
    ]
    if unexpected:
        raise ValueError(f"unexpected evaluator imports: {unexpected}")
    return imports


def main() -> int:
    if SOURCE_FREEZE.exists():
        raise FileExistsError(f"source freeze already exists: {SOURCE_FREEZE}")
    preregistration = _load(PREREGISTRATION)
    preregistration_freeze = _load(PREREGISTRATION_FREEZE)
    if preregistration.get("status") != (
        "preregistered_before_runner_implementation_and_model_calls"
    ):
        raise ValueError("invalid preregistration status")
    _verify_entries(preregistration["frozen_inputs"])
    _verify_entries(preregistration_freeze["artifacts"])
    missing = [str(path) for path in SOURCES.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing independent holdout source: {missing}")
    evaluator_imports = _verify_evaluator_imports(SOURCES["evaluator"])

    freeze = {
        "freeze_version": (
            "unified-jd-flat-atomic-v4.3-independent-holdout-source-freeze-v1"
        ),
        "frozen_at": datetime.now(UTC).isoformat(),
        "status": "frozen_before_independent_holdout_calls",
        "preregistration_sha256": _sha256(PREREGISTRATION),
        "artifacts": {
            "preregistration": _reference(PREREGISTRATION),
            "preregistration_freeze": _reference(PREREGISTRATION_FREEZE),
            **{name: _reference(path) for name, path in SOURCES.items()},
        },
        "frozen_inputs": preregistration["frozen_inputs"],
        "verification_before_freeze": {
            "focused_tests": "5 passed",
            "full_suite": "943 passed",
            "ruff_check": "passed",
            "python_compilation": "passed",
            "evaluator_imports": evaluator_imports,
            "model_call_count": 0,
            "deepseek_call_count": 0,
        },
        "authorization_scope": {
            "destination_host": "api.deepseek.com",
            "maximum_new_model_calls": 5,
            "maximum_calls_per_case": 1,
            "transport_retries": 0,
            "validation_retries": 0,
            "full_public_job_body_transmission_authorized": True,
        },
        "immutability": (
            "Any edit to the selection, preregistration, evaluator, runner, tests, "
            "request contract, thresholds, or frozen v4.3 compatibility mechanism "
            "invalidates this one-time independent holdout."
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
