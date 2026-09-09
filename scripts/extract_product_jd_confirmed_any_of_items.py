from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_settings
from src.infrastructure.llm_client import (
    StructuredModelRequest,
    create_structured_model_client,
)

DEFAULT_REVIEW_QUEUE = (
    ROOT / "datasets" / "product_jd_test100_review_queue_v2_2026_09_08.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-test100-confirmed-any-of-items-terra-medium-v1-2026-09-09.json"
)

PROMPT_VERSION = "product-jd-human-confirmed-item-boundary-v1"
EXPECTED_GROUP_COUNT = 9
SUPPORTED_OPERATIONS = {
    "set_all_flagged_relations_any_of",
    "set_all_flagged_relations_to_any_of",
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["case_id", "source_text", "candidate_items"],
    "properties": {
        "case_id": {"type": "string"},
        "source_text": {"type": "string"},
        "candidate_items": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}

SYSTEM_PROMPT = """You only split item boundaries for job requirements that a human has
already confirmed use any-of semantics. Do not judge or change the relation. For the input:
- return the same case_id and source_text verbatim;
- return 2-12 candidate items;
- every item must be an exact, contiguous substring of source_text;
- use the smallest independently verifiable candidate without paraphrasing or adding words;
- preserve meaningful compound names such as ROS/ROS2 and RoboMaster/Robocon;
- remove duplicates that differ only by letter case;
- exclude shared wrapper words such as has, familiar with, etcetera, related experience,
  or preferred.
Return exactly one JSON object with only these keys: case_id, source_text,
candidate_items."""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def collect_confirmed_groups(review_queue: dict[str, Any]) -> list[dict[str, str]]:
    groups: list[dict[str, str]] = []
    for case in review_queue.get("cases", []):
        decision = case.get("decision") or {}
        if decision.get("operation") not in SUPPORTED_OPERATIONS:
            continue
        if decision.get("status") != "confirmed":
            raise ValueError(f"Review decision is not confirmed: {case.get('id')!r}")
        for issue in case.get("issues", []):
            if issue.get("code") != "relation_uncertain":
                continue
            groups.append(
                {
                    "case_id": case["id"],
                    "source_text": issue["source_text"],
                }
            )
    if len(groups) != EXPECTED_GROUP_COUNT:
        raise ValueError(
            f"Expected {EXPECTED_GROUP_COUNT} confirmed groups, found {len(groups)}"
        )
    return groups


def validate_boundary_group(
    requested: dict[str, str],
    returned: Any,
) -> dict[str, Any]:
    if not isinstance(returned, dict):
        raise TypeError("Boundary response must be an object")
    if returned.get("case_id") != requested["case_id"]:
        raise ValueError("Boundary response changed the case ID")
    if returned.get("source_text") != requested["source_text"]:
        raise ValueError("Boundary response changed source_text")
    items = returned.get("candidate_items")
    if not isinstance(items, list) or not 2 <= len(items) <= 12:
        raise ValueError("Each confirmed any_of group requires 2-12 candidate_items")
    if not all(isinstance(item, str) and item.strip() for item in items):
        raise ValueError("Boundary response contains an empty or non-string item")
    if not all(item in requested["source_text"] for item in items):
        raise ValueError("Boundary response contains an item without verbatim evidence")
    normalized_items = [item.strip() for item in items]
    keys = [item.casefold() for item in normalized_items]
    if len(keys) != len(set(keys)):
        raise ValueError("Boundary response contains duplicate casefold items")
    return {
        "case_id": requested["case_id"],
        "source_text": requested["source_text"],
        "items": normalized_items,
        "reason": "Human-confirmed any_of; API-extracted verbatim item boundaries.",
    }


async def extract_confirmed_any_of_items(
    *,
    review_queue_path: Path = DEFAULT_REVIEW_QUEUE,
    output_path: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    review_queue = json.loads(review_queue_path.read_text(encoding="utf-8"))
    if review_queue.get("review_status") != "human_review_complete":
        raise ValueError("The test-100 human review is not complete")
    if review_queue.get("confirmed_decision_count") != 28:
        raise ValueError("Expected all 28 review decisions to be confirmed")
    requested = collect_confirmed_groups(review_queue)

    client = create_structured_model_client(get_settings())
    semaphore = asyncio.Semaphore(3)

    async def run_group(
        requested_group: dict[str, str],
    ) -> tuple[dict[str, Any], Any]:
        async with semaphore:
            response = await client.generate(
                StructuredModelRequest(
                    schema_name="product_jd_confirmed_any_of_items",
                    json_schema=OUTPUT_SCHEMA,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(requested_group, ensure_ascii=False),
                        },
                    ],
                    prompt_version=PROMPT_VERSION,
                    max_output_tokens=1024,
                )
            )
            return validate_boundary_group(requested_group, response.output), response

    batches = await asyncio.gather(*(run_group(group) for group in requested))
    groups = [group for group, _response in batches]
    responses = [response for _group, response in batches]
    result = {
        "artifact_version": (
            "product-jd-test100-confirmed-any-of-items-v1-2026-09-09"
        ),
        "status": "api_boundary_extraction_complete",
        "generated_at": datetime.now(UTC).isoformat(),
        "review_queue": {
            "path": review_queue_path.relative_to(ROOT).as_posix(),
            "sha256": _sha256_file(review_queue_path),
            "version": review_queue["review_queue_version"],
        },
        "prompt_version": PROMPT_VERSION,
        "model": responses[0].model,
        "provider": responses[0].provider,
        "reasoning_effort": getattr(client, "reasoning_effort", None),
        "response_format": getattr(client, "response_format", None),
        "group_count": len(groups),
        "model_call_count": len(responses),
        "groups": groups,
        "diagnostics": [
            {
                "response_id": response.response_id,
                "finish_reason": response.finish_reason,
                "request_duration_ms": response.request_duration_ms,
                "usage": response.usage,
            }
            for response in responses
        ],
    }
    _write_json(output_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract item boundaries for human-confirmed test-100 any_of groups"
    )
    parser.add_argument("--review-queue", type=Path, default=DEFAULT_REVIEW_QUEUE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = asyncio.run(
        extract_confirmed_any_of_items(
            review_queue_path=args.review_queue,
            output_path=args.output,
        )
    )
    print(
        "product-jd-confirmed-any-of-items "
        f"groups={result['group_count']} "
        f"model={result['model']} "
        f"reasoning_effort={result['reasoning_effort']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
