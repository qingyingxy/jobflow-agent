from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

CATEGORY_PREREGISTRATION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_category_vocabulary_admission_oracle_"
    "preregistration_v1_2026-09-06.json"
)
CATEGORY_PREREGISTRATION_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_category_vocabulary_admission_oracle_"
    "preregistration_freeze_v1_2026-09-06.json"
)
CATEGORY_SOURCE_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_category_vocabulary_admission_oracle_"
    "source_freeze_v1_2026-09-06.json"
)
ZERO_PREREGISTRATION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_zero_lower_bound_qualifier_oracle_"
    "preregistration_v1_2026-09-06.json"
)
ZERO_PREREGISTRATION_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_zero_lower_bound_qualifier_oracle_"
    "preregistration_freeze_v1_2026-09-06.json"
)
ZERO_SOURCE_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_3_zero_lower_bound_qualifier_oracle_"
    "source_freeze_v1_2026-09-06.json"
)

EXPECTED_HASHES = {
    CATEGORY_PREREGISTRATION: (
        "0e4dec9018463d255224044517b4e6ff0c48c06bb28984a4559688340df81d90"
    ),
    CATEGORY_PREREGISTRATION_FREEZE: (
        "f59256d262eedbdf10294bb4e190448a11dfba187957d30f73113eaf7ee36d94"
    ),
    ZERO_PREREGISTRATION: (
        "799bb850a726d1e1645b7d542bbce95acbdb7722695dd12d95ac26c5b73f969a"
    ),
    ZERO_PREREGISTRATION_FREEZE: (
        "a06cae5dcaa2dc813c84f948fca76551bbaf461777c91c3355e397a8d17f1579"
    ),
}

CATEGORY_SOURCES = {
    "oracle_evaluator": ROOT
    / "src/evaluation/model_first_v4_3_category_vocabulary_admission_oracle.py",
    "oracle_runner": ROOT
    / "scripts/run_unified_jd_flat_atomic_v4_3_category_vocabulary_admission_oracle.py",
    "focused_tests": ROOT
    / "tests/test_unified_jd_flat_atomic_v4_3_category_vocabulary_admission_oracle.py",
}
ZERO_SOURCES = {
    "oracle_adapter": ROOT
    / "src/services/unified_jd_flat_atomic_v4_3_zero_lower_bound_qualifier_oracle.py",
    "oracle_evaluator": ROOT
    / "src/evaluation/model_first_v4_3_zero_lower_bound_qualifier_oracle.py",
    "oracle_runner": ROOT
    / "scripts/run_unified_jd_flat_atomic_v4_3_zero_lower_bound_qualifier_oracle.py",
    "focused_tests": ROOT
    / "tests/test_unified_jd_flat_atomic_v4_3_zero_lower_bound_qualifier_oracle.py",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected object: {path}")
    return value


def _reference(path: Path) -> dict[str, str]:
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": _sha256(path)}


def _verify_references(entries: dict[str, Any]) -> None:
    for name, entry in entries.items():
        path = (ROOT / entry["path"]).resolve()
        if ROOT.resolve() not in path.parents:
            raise ValueError(f"frozen input escapes workspace: {name}")
        if not path.is_file() or _sha256(path) != entry["sha256"]:
            raise ValueError(f"frozen input hash mismatch: {name}")


def _freeze_payload(
    *,
    experiment_id: str,
    preregistration: Path,
    preregistration_freeze: Path,
    sources: dict[str, Path],
    frozen_at: str,
) -> dict[str, Any]:
    preregistration_value = _load(preregistration)
    freeze_value = _load(preregistration_freeze)
    _verify_references(preregistration_value["frozen_inputs"])
    _verify_references(freeze_value["artifacts"])
    return {
        "freeze_version": f"{experiment_id}-source-freeze-v1",
        "frozen_at": frozen_at,
        "status": "offline_oracle_runner_frozen_before_execution",
        "experiment_id": experiment_id,
        "preregistration": _reference(preregistration),
        "preregistration_freeze": _reference(preregistration_freeze),
        "artifacts": {name: _reference(path) for name, path in sources.items()},
        "frozen_inputs": preregistration_value["frozen_inputs"],
        "formal_execution_count_at_freeze": 0,
        "new_model_call_count_at_freeze": 0,
        "network_call_count_at_freeze": 0,
        "v4_3_modification_allowed": False,
        "other_oracle_output_allowed": False,
        "cross_oracle_treatment_accumulation_allowed": False,
        "immutability": (
            "Any implementation, test, input, treatment, control, threshold, or "
            "v4.3 change requires a new preregistration and source-freeze version."
        ),
    }


def _write_new(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)
        output.write("\n")


def main() -> int:
    outputs = (CATEGORY_SOURCE_FREEZE, ZERO_SOURCE_FREEZE)
    existing = [str(path) for path in outputs if path.exists()]
    if existing:
        raise FileExistsError(f"residual oracle source freeze already exists: {existing}")
    for path, expected_hash in EXPECTED_HASHES.items():
        if not path.is_file() or _sha256(path) != expected_hash:
            raise ValueError(f"preregistration hash mismatch: {path}")
    missing = [
        str(path)
        for path in (*CATEGORY_SOURCES.values(), *ZERO_SOURCES.values())
        if not path.is_file()
    ]
    if missing:
        raise FileNotFoundError(f"missing oracle implementation source: {missing}")
    frozen_at = datetime.now(UTC).isoformat()
    category = _freeze_payload(
        experiment_id="category-vocabulary-admission-oracle-v1",
        preregistration=CATEGORY_PREREGISTRATION,
        preregistration_freeze=CATEGORY_PREREGISTRATION_FREEZE,
        sources=CATEGORY_SOURCES,
        frozen_at=frozen_at,
    )
    zero = _freeze_payload(
        experiment_id="zero-lower-bound-qualifier-oracle-v1",
        preregistration=ZERO_PREREGISTRATION,
        preregistration_freeze=ZERO_PREREGISTRATION_FREEZE,
        sources=ZERO_SOURCES,
        frozen_at=frozen_at,
    )
    _write_new(CATEGORY_SOURCE_FREEZE, category)
    _write_new(ZERO_SOURCE_FREEZE, zero)
    print(
        json.dumps(
            {
                "category_source_freeze": _reference(CATEGORY_SOURCE_FREEZE),
                "zero_source_freeze": _reference(ZERO_SOURCE_FREEZE),
                "formal_execution_count_at_freeze": 0,
                "model_call_count": 0,
                "network_call_count": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
