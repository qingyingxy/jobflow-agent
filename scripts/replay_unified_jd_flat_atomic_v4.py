from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from src.evaluation.model_first_v4 import (
    audit_flat_atomic_v4_runtime_sources,
    build_flat_atomic_v4_projection,
    evaluate_flat_atomic_v4,
)

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-05"

DEFAULT_PREREGISTRATION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_preregistration_v1_2026-09-05.json"
)
DEFAULT_PREREGISTRATION_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_preregistration_freeze_v1_2026-09-05.json"
)
DEFAULT_SOURCE_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_source_freeze_v1_2026-09-05.json"
)
DEFAULT_RAW_OUTPUT = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-dev20-raw-v1-2026-09-05.json"
)
DEFAULT_REPORT = ROOT / (
    "artifacts/evaluation/unified-jd-flat-atomic-v4-dev20-report-v1-2026-09-05.json"
)

RUNTIME_AUDIT_PATHS = (
    ROOT / "src/domain/unified_jd_flat_atomic_v4.py",
    ROOT / "src/services/unified_jd_flat_atomic_v4.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected object: {path}")
    return value


def _resolve(entry: dict[str, Any]) -> Path:
    relative = entry.get("path")
    if not isinstance(relative, str):
        raise TypeError("frozen file entry requires path")
    path = (ROOT / relative).resolve()
    if ROOT.resolve() not in path.parents:
        raise ValueError(f"frozen path escapes workspace: {path}")
    return path


def _verify_entries(entries: dict[str, Any]) -> None:
    for name, entry in entries.items():
        if not isinstance(entry, dict):
            raise TypeError(f"invalid frozen entry: {name}")
        path = _resolve(entry)
        if not path.is_file() or _sha256(path) != entry.get("sha256"):
            raise ValueError(f"frozen file hash mismatch: {name}")


def _write_new_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = (
        payload.model_dump_json(indent=2)  # type: ignore[attr-defined]
        if hasattr(payload, "model_dump_json")
        else json.dumps(payload, ensure_ascii=False, indent=2)
    )
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(rendered + "\n")


def _run_frozen_tests() -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_unified_model_first_v3.py",
        "tests/test_unified_jd_flat_atomic_v4.py",
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    return {
        "passed": completed.returncode == 0,
        "exit_code": completed.returncode,
        "command": command[1:],
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute the preregistered flat atomic v4 offline gates once"
    )
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    parser.add_argument(
        "--preregistration-freeze",
        type=Path,
        default=DEFAULT_PREREGISTRATION_FREEZE,
    )
    parser.add_argument("--source-freeze", type=Path, default=DEFAULT_SOURCE_FREEZE)
    parser.add_argument("--raw-output", type=Path, default=DEFAULT_RAW_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    existing = [
        str(path) for path in (arguments.raw_output, arguments.report) if path.exists()
    ]
    if existing:
        raise SystemExit(f"refusing to overwrite v4 gate artifacts: {existing}")

    started_at = datetime.now(UTC)
    started_clock = perf_counter()
    preregistration = _load(arguments.preregistration)
    preregistration_freeze = _load(arguments.preregistration_freeze)
    source_freeze = _load(arguments.source_freeze)
    if preregistration.get("status") != "preregistered_before_implementation":
        raise SystemExit("invalid preregistration status")
    if source_freeze.get("status") != "frozen_before_gate_execution":
        raise SystemExit("implementation source is not frozen for gate execution")

    _verify_entries(preregistration["frozen_inputs"])
    _verify_entries(preregistration_freeze["artifacts"])
    _verify_entries(source_freeze["artifacts"])
    preregistration_entry = preregistration_freeze["artifacts"]["preregistration"]
    if _resolve(preregistration_entry) != arguments.preregistration.resolve():
        raise SystemExit("preregistration freeze points to a different file")
    if _sha256(arguments.preregistration) != source_freeze.get(
        "preregistration_sha256"
    ):
        raise SystemExit("source freeze was created for a different preregistration")

    frozen_inputs = preregistration["frozen_inputs"]
    manifest = _load(_resolve(frozen_inputs["development_manifest"]))
    predictions = _load(_resolve(frozen_inputs["v1_predictions_with_raw_responses"]))
    v3_projection = _load(_resolve(frozen_inputs["v3_layer_projection"]))
    v3_report = _load(_resolve(frozen_inputs["v3_layer_report"]))
    nested_probe = _load(_resolve(frozen_inputs["nested_v3_case121_raw_response"]))

    projection = build_flat_atomic_v4_projection(
        manifest,
        predictions,
        v3_projection,
    )
    _write_new_json(arguments.raw_output, projection)

    test_result = _run_frozen_tests()
    static_audit = audit_flat_atomic_v4_runtime_sources(list(RUNTIME_AUDIT_PATHS))
    report = evaluate_flat_atomic_v4(
        manifest,
        predictions,
        v3_projection,
        v3_report,
        nested_probe,
        projection,
        frozen_inputs_valid=True,
        frozen_sources_valid=True,
        static_audit=static_audit,
        tests_passed=test_result["passed"],
    )
    report["inputs"] = {
        "preregistration": {
            "path": arguments.preregistration.as_posix(),
            "sha256": _sha256(arguments.preregistration),
        },
        "preregistration_freeze": {
            "path": arguments.preregistration_freeze.as_posix(),
            "sha256": _sha256(arguments.preregistration_freeze),
        },
        "source_freeze": {
            "path": arguments.source_freeze.as_posix(),
            "sha256": _sha256(arguments.source_freeze),
        },
    }
    report["test_execution"] = test_result
    report["run"] = {
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "duration_ms": round((perf_counter() - started_clock) * 1000, 2),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "model_api_called": False,
        "model_call_count": 0,
        "network_call_count": 0,
    }
    _write_new_json(arguments.report, report)
    print(
        "flat atomic v4 gates complete "
        f"passed={report['passed']} cases={report['case_count']} "
        "model_calls=0 network_calls=0"
    )
    print(f"raw_output={arguments.raw_output}")
    print(f"report={arguments.report}")
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
