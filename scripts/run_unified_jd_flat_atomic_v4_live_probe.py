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

from src.config import get_settings
from src.evaluation.model_first_v4_live_probe import (
    UnifiedJDFlatAtomicLiveResponseV4,
    evaluate_live_probe_v4,
)
from src.infrastructure.llm_client import (
    ChatMessage,
    ModelClientError,
    StructuredModelClient,
    StructuredModelRequest,
    create_structured_model_client,
)

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-06"

DEFAULT_SELECTION = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_live_probe_selection_v1_2026-09-06.json"
)
DEFAULT_PREREGISTRATION = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_live_probe_preregistration_v1_2026-09-06.json"
)
DEFAULT_PREREGISTRATION_FREEZE = ROOT / (
    "datasets/"
    "unified_jd_flat_atomic_v4_live_probe_preregistration_freeze_v1_2026-09-06.json"
)
DEFAULT_SOURCE_FREEZE = ROOT / (
    "datasets/unified_jd_flat_atomic_v4_live_probe_source_freeze_v1_2026-09-06.json"
)
DEFAULT_REQUESTS = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-live-probe-requests-v1-2026-09-06.json"
)
DEFAULT_CHECKPOINT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-live-probe-raw-responses-v1-2026-09-06.checkpoint.json"
)
DEFAULT_RAW_RESPONSES = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-live-probe-raw-responses-v1-2026-09-06.json"
)
DEFAULT_REPORT = ROOT / (
    "artifacts/evaluation/"
    "unified-jd-flat-atomic-v4-live-probe-report-v1-2026-09-06.json"
)

MAX_NEW_MODEL_CALLS = 5


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
        output.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _replace_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with temporary.open("w", encoding="utf-8", newline="\n") as output:
        output.write(rendered)
    os.replace(temporary, path)


def _resolve(entry: dict[str, Any]) -> Path:
    relative = entry.get("path")
    if not isinstance(relative, str):
        raise TypeError("frozen entry requires path")
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


def build_live_probe_requests(
    selection: dict[str, Any],
    preregistration: dict[str, Any],
) -> list[tuple[str, str, StructuredModelRequest]]:
    contract = preregistration["request_contract"]
    system_prompt = contract["system_prompt"]
    if _payload_text_sha256(system_prompt) != contract["system_prompt_sha256"]:
        raise ValueError("frozen system prompt hash mismatch")
    cases = selection.get("cases")
    if not isinstance(cases, list):
        raise TypeError("selection cases must be a list")

    requests: list[tuple[str, str, StructuredModelRequest]] = []
    for case in cases:
        case_id = case.get("case_id")
        raw_content = case.get("raw_content")
        input_sha256 = case.get("source_content_sha256")
        if not isinstance(case_id, str) or not isinstance(raw_content, str):
            raise TypeError("selection case requires case_id and raw_content")
        if _payload_text_sha256(raw_content) != input_sha256:
            raise ValueError(f"selection input hash mismatch: {case_id}")
        user_prompt = contract["user_prompt_template"].format(
            raw_content=raw_content
        )
        request = StructuredModelRequest(
            schema_name=contract["schema_name"],
            json_schema=UnifiedJDFlatAtomicLiveResponseV4.model_json_schema(),
            messages=[
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_prompt),
            ],
            prompt_version=contract["prompt_version"],
            max_output_tokens=contract["max_output_tokens"],
        )
        requests.append((case_id, input_sha256, request))
    if [item[0] for item in requests] != selection.get("selected_case_ids"):
        raise ValueError("request order does not match frozen selection")
    return requests


async def execute_live_probe(
    requests: list[tuple[str, str, StructuredModelRequest]],
    client: StructuredModelClient,
    *,
    existing_records: list[dict[str, Any]] | None = None,
    checkpoint_path: Path | None = None,
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
        if checkpoint_path is not None:
            _replace_json(
                checkpoint_path,
                {
                    "checkpoint_version": (
                        "unified-jd-flat-atomic-v4-live-probe-checkpoint-v1"
                    ),
                    "maximum_new_model_calls": MAX_NEW_MODEL_CALLS,
                    "model_call_count": len(records),
                    "records": records,
                },
            )
        if transport_stopped:
            break
    return {
        "response_version": "unified-jd-flat-atomic-v4-live-probe-raw-v1",
        "maximum_new_model_calls": MAX_NEW_MODEL_CALLS,
        "model_call_count": len(records),
        "transport_stopped": transport_stopped,
        "records": records,
    }


def _payload_text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request_artifact(
    requests: list[tuple[str, str, StructuredModelRequest]],
    *,
    destination_host: str,
) -> dict[str, Any]:
    return {
        "request_version": "unified-jd-flat-atomic-v4-live-probe-requests-v1",
        "authorization": (
            "Execution requires --authorized-full-body-transmission after explicit "
            "user approval in the active task."
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the frozen five-call flat atomic v4 DeepSeek probe"
    )
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    parser.add_argument(
        "--preregistration-freeze",
        type=Path,
        default=DEFAULT_PREREGISTRATION_FREEZE,
    )
    parser.add_argument("--source-freeze", type=Path, default=DEFAULT_SOURCE_FREEZE)
    parser.add_argument("--requests", type=Path, default=DEFAULT_REQUESTS)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--raw-responses", type=Path, default=DEFAULT_RAW_RESPONSES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--authorized-full-body-transmission", action="store_true")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    if not arguments.authorized_full_body_transmission:
        raise SystemExit(
            "explicit authorization flag is required before transmitting full job bodies"
        )
    final_outputs = (arguments.raw_responses, arguments.report)
    existing_final = [str(path) for path in final_outputs if path.exists()]
    if existing_final:
        raise SystemExit(f"refusing to repeat frozen live probe: {existing_final}")
    if arguments.resume:
        if not arguments.requests.is_file() or not arguments.checkpoint.is_file():
            raise SystemExit("--resume requires frozen request and checkpoint artifacts")
    else:
        existing_initial = [
            str(path)
            for path in (arguments.requests, arguments.checkpoint)
            if path.exists()
        ]
        if existing_initial:
            raise SystemExit(
                f"existing partial probe requires --resume: {existing_initial}"
            )

    preregistration = _load(arguments.preregistration)
    preregistration_freeze = _load(arguments.preregistration_freeze)
    source_freeze = _load(arguments.source_freeze)
    if preregistration.get("status") != (
        "preregistered_before_live_runner_implementation_and_calls"
    ):
        raise SystemExit("invalid live preregistration status")
    if source_freeze.get("status") != "frozen_before_live_probe_calls":
        raise SystemExit("live runner and evaluator have not been frozen")
    _verify_entries(preregistration["frozen_inputs"])
    _verify_entries(preregistration_freeze["artifacts"])
    _verify_entries(source_freeze["artifacts"])
    if _sha256(arguments.preregistration) != source_freeze.get(
        "preregistration_sha256"
    ):
        raise SystemExit("source freeze points to a different preregistration")

    selection = _load(arguments.selection)
    requests = build_live_probe_requests(selection, preregistration)
    settings = get_settings()
    hostname = urlparse(settings.llm_base_url or "").hostname
    if hostname != "api.deepseek.com":
        raise SystemExit(
            "live probe is authorized only for api.deepseek.com; "
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
        raise SystemExit("live probe requires the configured DeepSeek client")

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
        execute_live_probe(
            requests,
            client,
            existing_records=existing_records,
            checkpoint_path=arguments.checkpoint,
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

    report = evaluate_live_probe_v4(
        selection,
        preregistration,
        raw_responses,
        authorization_confirmed=True,
        destination_valid=True,
        frozen_inputs_valid=True,
        frozen_sources_valid=True,
        gold_unavailable_to_requests=(
            "expected" not in json.dumps(request_artifact, ensure_ascii=False)
        ),
    )
    report["inputs"] = {
        "selection": {
            "path": arguments.selection.as_posix(),
            "sha256": _sha256(arguments.selection),
        },
        "preregistration": {
            "path": arguments.preregistration.as_posix(),
            "sha256": _sha256(arguments.preregistration),
        },
        "source_freeze": {
            "path": arguments.source_freeze.as_posix(),
            "sha256": _sha256(arguments.source_freeze),
        },
        "requests": {
            "path": arguments.requests.as_posix(),
            "sha256": _sha256(arguments.requests),
        },
        "raw_responses": {
            "path": arguments.raw_responses.as_posix(),
            "sha256": _sha256(arguments.raw_responses),
        },
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
        "flat atomic v4 live probe complete "
        f"passed={report['passed']} calls={report['model_call_count']}/5"
    )
    print(f"raw_responses={arguments.raw_responses}")
    print(f"report={arguments.report}")
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
