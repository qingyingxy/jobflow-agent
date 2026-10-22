from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from src.domain.skill_normalizer import SKILL_ONTOLOGY_VERSION
from src.evaluation.models import EvaluationManifest
from src.services.core_jd_parser import (
    CORE_MAX_OUTPUT_TOKENS,
    CORE_SCHEMA_VERSION,
    DEFAULT_CORE_PARSER_VERSION,
    DEFAULT_CORE_PROMPT_VERSION,
)

SOURCE_MANIFEST_PATH = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-manifest-core-v34-dev4-frozen-v1-2026-09-03.json"
)
LABEL_PATH = Path("datasets/ai_campus_v34_dev4_label_freeze_v1_2026_09_03.json")
CANARY_PATH = Path(
    "artifacts/evaluation/m11-core-v35-synthetic-canary-v1-2026-09-03.json"
)
COMPARISON_PATH = Path(
    "artifacts/evaluation/"
    "m11-ai-campus-manifest-core-v35-dev4-comparison-v1-2026-09-03.json"
)
FREEZE_PATH = Path("datasets/ai_campus_v35_execution_freeze_v1_2026_09_03.json")
RUN_POLICY_PATH = Path("artifacts/evaluation/v35-run-policy.env")
FROZEN_AT = "2026-09-03T10:19:00+08:00"

PARSER_FILES = (
    Path("src/config.py"),
    Path("src/services/core_jd_parser.py"),
    Path("src/domain/core_skill_semantics.py"),
    Path("src/domain/skill_normalizer.py"),
    Path("src/domain/job.py"),
    Path("src/infrastructure/llm_client.py"),
    Path("scripts/run_core_v35_evaluation.py"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def write_json(path: Path, payload: dict[str, Any], *, immutable: bool) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if immutable and path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise FileExistsError(f"refusing to overwrite changed freeze: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def build_canary() -> dict[str, Any]:
    payload = {
        "manifest_version": "m11-core-v35-synthetic-canary-v1",
        "dataset_version": "m11-core-v35-synthetic-canary-v1-2026-09-03",
        "split": "dev",
        "purpose": "Validate the v35 DeepSeek non-thinking structured-output path.",
        "source_policy": (
            "One synthetic JD contains no personal or third-party private data. "
            "Run once before the four-case public comparison."
        ),
        "fields": ["job_type", "locations", "required_skills"],
        "thresholds": {},
        "cases": [
            {
                "id": "synthetic-v35-canary-001",
                "split": "dev",
                "source": {
                    "kind": "synthetic",
                    "reference": "inline-synthetic-v35-canary-001",
                    "authorization": (
                        "User requested one short synthetic canary on 2026-09-03."
                    ),
                    "notes": "Transport canary; not part of dataset metrics.",
                },
                "input": {
                    "raw_content": (
                        "岗位名称：Python 开发工程师\n"
                        "招聘类型：校园招聘\n"
                        "工作地点：北京\n"
                        "任职要求：熟悉 Python。"
                    ),
                    "source_url": None,
                    "scenario": "v35_synthetic_transport_canary",
                },
                "candidate_evidence_ids": [],
                "expected": {
                    "fields": {
                        "job_type": "campus",
                        "locations": ["北京"],
                        "required_skills": ["Python"],
                    },
                    "skill_mentions": [],
                    "eligibility": None,
                    "evidence": {},
                    "failure_code": None,
                    "tags": ["synthetic", "v35", "transport_canary"],
                },
            }
        ],
    }
    return EvaluationManifest.model_validate(payload).model_dump(mode="json")


def build_comparison() -> dict[str, Any]:
    source = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    payload = copy.deepcopy(source)
    payload["manifest_version"] = "m11-ai-campus-v35-dev4-comparison-v1"
    payload["dataset_version"] = "m11-ai-v35-dev4-comparison-v1-2026-09-03"
    payload["purpose"] = (
        "Run Parser v35 once on the same four frozen, owner-reviewed public JDs "
        "to compare first-attempt reliability with v34."
    )
    payload["source_policy"] = (
        "Reuse the exact v34 frozen public JD inputs and labels. Send each JD once "
        "only after the v35 synthetic canary succeeds; do not overwrite v34 artifacts."
    )
    for case in payload["cases"]:
        case["source"]["authorization"] = (
            "User requested a v35 rerun of these same four public JDs on 2026-09-03."
        )
        case["input"]["scenario"] = "v35_same_four_frozen_label_comparison"
        tags = case["expected"].setdefault("tags", [])
        if "v35_same_four_comparison" not in tags:
            tags.append("v35_same_four_comparison")
    return EvaluationManifest.model_validate(payload).model_dump(mode="json")


def main() -> None:
    actual_contract = (
        DEFAULT_CORE_PARSER_VERSION,
        DEFAULT_CORE_PROMPT_VERSION,
        CORE_SCHEMA_VERSION,
        SKILL_ONTOLOGY_VERSION,
        CORE_MAX_OUTPUT_TOKENS,
    )
    expected_contract = (
        "jd-core-parser-v35",
        "jd-core-parser-prompt-v23",
        "core-job-fields-v10",
        "skill-ontology-v4",
        4096,
    )
    if actual_contract != expected_contract:
        raise ValueError("runtime parser contract no longer matches the v35 freeze")

    write_json(CANARY_PATH, build_canary(), immutable=True)
    write_json(COMPARISON_PATH, build_comparison(), immutable=True)

    freeze = {
        "freeze_version": "ai-campus-v35-execution-freeze-v1-2026-09-03",
        "frozen_at": FROZEN_AT,
        "purpose": "v35 transport canary followed by one same-four comparison",
        "frozen_contract": {
            "parser": DEFAULT_CORE_PARSER_VERSION,
            "prompt": DEFAULT_CORE_PROMPT_VERSION,
            "schema": CORE_SCHEMA_VERSION,
            "skill_ontology": SKILL_ONTOLOGY_VERSION,
            "response_format": "json_object",
            "thinking_mode": "disabled",
            "max_tokens": CORE_MAX_OUTPUT_TOKENS,
            "files": {path.as_posix(): file_record(path) for path in PARSER_FILES},
        },
        "labels": file_record(LABEL_PATH),
        "synthetic_canary_manifest": file_record(CANARY_PATH),
        "same_four_comparison_manifest": file_record(COMPARISON_PATH),
        "run_policy_environment": file_record(RUN_POLICY_PATH),
        "api_authorization": {
            "authorized_at": "2026-09-03",
            "destination": "configured DeepSeek API",
            "canary_run_limit": 1,
            "same_four_run_limit": 1,
            "comparison_condition": "synthetic canary succeeds",
        },
        "run_policy": {
            "concurrency": 1,
            "model_retries": 0,
            "parser_validation_repairs": 0,
            "http_timeout_seconds": 60,
            "case_timeout_seconds": 90,
            "checkpoint_resume": False,
            "retry_failures": False,
        },
        "prediction_status": "not_generated_at_freeze_time",
    }
    write_json(FREEZE_PATH, freeze, immutable=True)
    print(
        f"v35 frozen canary={sha256(CANARY_PATH)} "
        f"comparison={sha256(COMPARISON_PATH)} labels={sha256(LABEL_PATH)}"
    )


if __name__ == "__main__":
    main()
