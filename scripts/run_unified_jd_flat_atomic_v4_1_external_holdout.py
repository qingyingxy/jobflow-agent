from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from scripts.run_unified_jd_flat_atomic_v4_live_probe import (
    build_live_probe_requests,
)
from src.config import get_settings
from src.evaluation.model_first_v4_1_external_holdout import (
    evaluate_external_holdout_v4_1,
)
from src.infrastructure.llm_client import (
    ModelClientError,
    StructuredModelClient,
    StructuredModelRequest,
    create_structured_model_client,
)

ROOT = Path(__file__).resolve().parents[1]
MAX_NEW_MODEL_CALLS = 5

DEFAULT_SELECTION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_1_external_holdout_selection_v1_2026-09-06.json"
)
DEFAULT_PREREGISTRATION = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_external_holdout_preregistration_v1_2026-09-06.json"
)
DEFAULT_PREREGISTRATION_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_external_holdout_preregistration_freeze_v1_2026-09-06.json"
)
DEFAULT_SOURCE_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_1_external_holdout_source_freeze_v1_2026-09-06.json"
)
DEFAULT_REQUEST_CONTRACT = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_live_probe_preregistration_v1_2026-09-06.json"
)
DEFAULT_REQUESTS = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-1-external-holdout-requests-v1-2026-09-06.json"
)
DEFAULT_CHECKPOINT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-1-external-holdout-raw-v1-2026-09-06.checkpoint.json"
)
DEFAULT_RAW = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-1-external-holdout-raw-v1-2026-09-06.json"
)
DEFAULT_REPORT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-1-external-holdout-report-v1-2026-09-06.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _payload_sha256(value: object) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected object: {path}")
    return value


def _write_new_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)
        output.write("\n")


def _replace_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)
        output.write("\n")
    os.replace(temporary, path)


def _reference(path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": _sha256(path),
    }


def _verify_entries(entries: dict[str, Any]) -> None:
    for name, entry in entries.items():
        if not isinstance(entry, dict):
            raise TypeError(f"invalid frozen entry: {name}")
        relative = entry.get("path")
        expected = entry.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise TypeError(f"invalid frozen reference: {name}")
        path = (ROOT / relative).resolve()
        if ROOT.resolve() not in path.parents:
            raise ValueError(f"frozen path escapes workspace: {path}")
        if not path.is_file() or _sha256(path) != expected:
            raise ValueError(f"frozen file hash mismatch: {name}")


def _request_artifact(
    requests: list[tuple[str, str, StructuredModelRequest]],
    *,
    destination_host: str,
) -> dict[str, Any]:
    return {
        "request_version": ("unified-jd-flat-atomic-v4.1-external-holdout-requests-v1"),
        "authorization": (
            "Execution requires --authorized-full-body-transmission after explicit "
            "user approval naming these five bodies, api.deepseek.com, and five calls."
        ),
        "destination_host": destination_host,
        "maximum_new_model_calls": MAX_NEW_MODEL_CALLS,
        "maximum_calls_per_case": 1,
        "transport_retries": 0,
        "validation_retries": 0,
        "requests": [
            {
                "case_id": case_id,
                "input_sha256": input_sha256,
                "request_sha256": _payload_sha256(request.model_dump(mode="json")),
                "request": request.model_dump(mode="json"),
            }
            for case_id, input_sha256, request in requests
        ],
    }


async def _execute(
    requests: list[tuple[str, str, StructuredModelRequest]],
    client: StructuredModelClient,
    *,
    checkpoint_path: Path,
    existing_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    records = list(existing_records or [])
    attempted_ids = {record["case_id"] for record in records}
    if len(records) > MAX_NEW_MODEL_CALLS or len(attempted_ids) != len(records):
        raise ValueError("checkpoint violates one-call-per-case budget")

    transport_stopped = False
    for case_id, input_sha256, request in requests:
        if case_id in attempted_ids:
            continue
        if len(records) >= MAX_NEW_MODEL_CALLS:
            break
        started_at = datetime.now(UTC)
        started_clock = perf_counter()
        try:
            response = await client.generate(request)
        except ModelClientError as error:
            record = {
                "case_id": case_id,
                "input_sha256": input_sha256,
                "request_sha256": _payload_sha256(request.model_dump(mode="json")),
                "model_call_count": 1,
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(UTC).isoformat(),
                "duration_ms": round((perf_counter() - started_clock) * 1000, 2),
                "model": client.model_name,
                "provider": client.provider,
                "failure_code": error.code,
                "error": str(error),
                "error_details": error.details,
                "raw_model_output": None,
                "response_diagnostics": {},
            }
            records.append(record)
            transport_stopped = True
        else:
            record = {
                "case_id": case_id,
                "input_sha256": input_sha256,
                "request_sha256": _payload_sha256(request.model_dump(mode="json")),
                "model_call_count": 1,
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(UTC).isoformat(),
                "duration_ms": round((perf_counter() - started_clock) * 1000, 2),
                "model": response.model,
                "provider": response.provider,
                "failure_code": None,
                "error": None,
                "error_details": {},
                "raw_model_output": response.output,
                "response_diagnostics": {
                    **response.diagnostics,
                    "response_id": response.response_id,
                    "finish_reason": response.finish_reason,
                    "request_duration_ms": response.request_duration_ms,
                    "usage": response.usage,
                },
            }
            records.append(record)
        attempted_ids.add(case_id)
        _replace_json(
            checkpoint_path,
            {
                "checkpoint_version": (
                    "unified-jd-flat-atomic-v4.1-external-holdout-checkpoint-v1"
                ),
                "maximum_new_model_calls": MAX_NEW_MODEL_CALLS,
                "model_call_count": len(records),
                "records": records,
            },
        )
        if transport_stopped:
            break
    return {
        "response_version": ("unified-jd-flat-atomic-v4.1-external-holdout-raw-v1"),
        "maximum_new_model_calls": MAX_NEW_MODEL_CALLS,
        "model_call_count": len(records),
        "transport_stopped": transport_stopped,
        "records": records,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen five-call v4.1 external holdout"
    )
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    parser.add_argument(
        "--preregistration-freeze",
        type=Path,
        default=DEFAULT_PREREGISTRATION_FREEZE,
    )
    parser.add_argument("--source-freeze", type=Path, default=DEFAULT_SOURCE_FREEZE)
    parser.add_argument(
        "--request-contract", type=Path, default=DEFAULT_REQUEST_CONTRACT
    )
    parser.add_argument("--requests", type=Path, default=DEFAULT_REQUESTS)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--raw-responses", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--authorized-full-body-transmission", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    if not arguments.authorized_full_body_transmission:
        raise SystemExit(
            "explicit authorization is required before transmitting the five full bodies"
        )
    final_outputs = (arguments.raw_responses, arguments.report)
    existing_final = [str(path) for path in final_outputs if path.exists()]
    if existing_final:
        raise SystemExit(f"refusing to repeat frozen holdout: {existing_final}")
    if arguments.resume:
        if not arguments.requests.is_file() or not arguments.checkpoint.is_file():
            raise SystemExit("--resume requires saved request and checkpoint artifacts")
    else:
        existing_partial = [
            str(path)
            for path in (arguments.requests, arguments.checkpoint)
            if path.exists()
        ]
        if existing_partial:
            raise SystemExit(
                f"existing partial holdout requires --resume: {existing_partial}"
            )

    preregistration = _load(arguments.preregistration)
    preregistration_freeze = _load(arguments.preregistration_freeze)
    source_freeze = _load(arguments.source_freeze)
    request_contract = _load(arguments.request_contract)
    if preregistration.get("status") != (
        "preregistered_before_external_holdout_runner_implementation_and_calls"
    ):
        raise SystemExit("invalid external holdout preregistration status")
    if source_freeze.get("status") != "frozen_before_external_holdout_calls":
        raise SystemExit("external holdout runner and evaluator are not frozen")
    _verify_entries(preregistration["frozen_inputs"])
    _verify_entries(preregistration_freeze["artifacts"])
    _verify_entries(source_freeze["artifacts"])
    if _sha256(arguments.preregistration) != source_freeze.get(
        "preregistration_sha256"
    ):
        raise SystemExit("source freeze points to a different preregistration")

    selection = _load(arguments.selection)
    requests = build_live_probe_requests(selection, request_contract)
    settings = get_settings()
    hostname = urlparse(settings.llm_base_url or "").hostname
    if hostname != "api.deepseek.com":
        raise SystemExit(
            "holdout is authorized only for api.deepseek.com; "
            f"configured host={hostname!r}"
        )
    one_attempt_settings = settings.model_copy(
        update={"llm_max_retries": 0, "llm_thinking_mode": "disabled"}
    )
    try:
        client = create_structured_model_client(one_attempt_settings)
    except ModelClientError as error:
        raise SystemExit(f"cannot create DeepSeek client: {error}") from error
    if client.provider == "fake":
        raise SystemExit("external holdout requires the configured DeepSeek client")

    request_artifact = _request_artifact(requests, destination_host=hostname)
    if arguments.resume:
        if _load(arguments.requests) != request_artifact:
            raise SystemExit("saved requests do not match deterministic rebuild")
        checkpoint = _load(arguments.checkpoint)
        existing_records = checkpoint.get("records")
        if not isinstance(existing_records, list):
            raise SystemExit("invalid checkpoint records")
    else:
        _write_new_json(arguments.requests, request_artifact)
        existing_records = []

    started_at = datetime.now(UTC)
    started_clock = perf_counter()
    raw_responses = asyncio.run(
        _execute(
            requests,
            client,
            checkpoint_path=arguments.checkpoint,
            existing_records=existing_records,
        )
    )
    raw_responses.update(
        {
            "destination_host": hostname,
            "selection_sha256": _sha256(arguments.selection),
            "requests_sha256": _sha256(arguments.requests),
        }
    )
    _write_new_json(arguments.raw_responses, raw_responses)

    report = evaluate_external_holdout_v4_1(
        selection,
        preregistration,
        raw_responses,
        authorization_confirmed=True,
        destination_valid=True,
        frozen_inputs_valid=True,
        frozen_sources_valid=True,
        gold_unavailable_to_requests=(
            "expected" not in json.dumps(request_artifact, ensure_ascii=False)
            and "gold" not in json.dumps(request_artifact, ensure_ascii=False).lower()
        ),
    )
    report["inputs"] = {
        "selection": _reference(arguments.selection),
        "preregistration": _reference(arguments.preregistration),
        "preregistration_freeze": _reference(arguments.preregistration_freeze),
        "source_freeze": _reference(arguments.source_freeze),
        "request_contract": _reference(arguments.request_contract),
        "requests": _reference(arguments.requests),
        "raw_responses": _reference(arguments.raw_responses),
    }
    report["run"] = {
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "duration_ms": round((perf_counter() - started_clock) * 1000, 2),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "model": client.model_name,
        "provider": client.provider,
        "destination_host": hostname,
        "transport_retries": 0,
        "validation_retries": 0,
    }
    _write_new_json(arguments.report, report)
    print(
        "v4.1 external holdout complete "
        f"decision={report['decision']} calls={report['model_call_count']}/5"
    )
    print(f"raw_responses={arguments.raw_responses}")
    print(f"report={arguments.report}")
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
