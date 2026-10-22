"""Replay archived responses through current validation, compilation and matching.

No model or recruitment-site requests. Original outputs and reference labels are
read-only; a replay is not a fresh estimate of model accuracy or latency.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from scripts.run_product_jd_paired_acceptance import decision_metrics
from scripts.run_product_jd_unseen_acceptance import candidate_checks
from src.domain.job import RawJobDocument
from src.infrastructure.llm_client import ModelClientError, StructuredModelResponse
from src.services.discovery_matching import classify_discovery_job
from src.services.discovery_sources import JobStub
from src.services.jd_parser import JDParserError
from src.services.product_jd_execution import ProductJDExecutionParser


class ArchivedResponseClient:
    provider = "offline_replay"
    model_name = "archived-model-responses"

    def __init__(self, calls):
        self.calls = calls
        self.cursor = 0
        self.consumed = []

    async def generate(self, request):
        # A fixed-response replay skips archived transport failures. If new
        # control flow needs a response not recorded, it must remain unavailable.
        for index in range(self.cursor, len(self.calls)):
            call = self.calls[index]
            if call.get("schema_name") == request.schema_name and isinstance(
                call.get("output"), dict
            ):
                self.cursor = index + 1
                self.consumed.append(index)
                return StructuredModelResponse(
                    output=deepcopy(call["output"]),
                    model=self.model_name,
                    provider=self.provider,
                )
        raise ModelClientError(
            "offline_response_missing",
            "当前校验路径需要的响应未保存在原运行中",
            {"schema_name": request.schema_name},
        )


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def metrics(rows, mode, *, previous=False):
    checks = [
        {**check, "actual": check["previous_actual"] if previous else check["actual"]}
        for row in rows
        if row["mode"] == mode
        for check in row["candidate_checks"]
    ]
    return {
        field: decision_metrics(
            [check for check in checks if field in check["expected"]], field
        )
        for field in ("education", "eligibility")
    }


async def replay(root, destination):
    if destination.exists():
        raise ValueError("回放输出目录已经存在，不覆盖旧结果")
    manifest = read(root / "manifest.json")
    label_paths = [
        p for p in manifest["source_hashes"] if Path(p).name == "labels.json"
    ]
    if len(label_paths) != 1:
        raise ValueError("必须有唯一的冻结标签来源")
    label_path = root / "sources" / label_paths[0]
    if sha256(label_path) != manifest["source_hashes"][label_paths[0]]:
        raise ValueError("冻结标签哈希不一致")
    prediction_path = root / "predictions.json"
    frozen_paths = [prediction_path, label_path, root / "manifest.json"]
    cases = {case["id"]: case for case in read(label_path)["cases"]}
    review_path = root / "reference_review.json"
    if review_path.exists():
        review = read(review_path)
        if review["original_labels_sha256"] != sha256(label_path):
            raise ValueError("来源复核没有绑定当前冻结标签")
        frozen_paths.append(review_path)
        for correction in review["corrections"]:
            label = next(
                q
                for q in cases[correction["case_id"]]["qualification_labels"]
                if q["id"] == correction["candidate_id"]
            )
            label.update(correction["corrected_expected"])
    hashes = {str(path): sha256(path) for path in frozen_paths}
    originals = read(prediction_path)["results"]
    keys = [(r["case_id"], r["mode"], r["repeat"]) for r in originals]
    if len(set(keys)) != len(keys):
        raise ValueError("原运行包含重复键")
    rows = []
    for original in originals:
        case = cases[original["case_id"]]
        client = ArchivedResponseClient(original["calls"])
        parser = ProductJDExecutionParser(
            client, mode=original["mode"], validation_retries=1, transport_retries=0
        )
        doc = RawJobDocument(
            raw_content=case["raw_content"], source_url=case["source_url"]
        )
        job = failure = None
        diagnostics = {}
        try:
            parsed = await parser.parse(doc)
            job = parsed.structured_jd
        except JDParserError as error:
            failure, diagnostics = error.code, error.details
        previous = {c["id"]: c for c in original["candidate_checks"]}
        checks = candidate_checks(job, case["qualification_labels"])
        for check in checks:
            check["previous_actual"] = previous[check["id"]]["actual"]
        search_job = JobStub(
            source_id="archived_official_jd",
            source_job_id=case["source_job_id"],
            title=case["title"],
            company=case["company"],
            locations=[],
            job_type=case["official_job_type"],
            published_at=None,
            raw_content=case["raw_content"],
            detail_url=case["source_url"],
        )
        discovery = classify_discovery_job(search_job, query="2027届")
        rows.append(
            {
                "case_id": original["case_id"],
                "mode": original["mode"],
                "repeat": original["repeat"],
                "parser_version": parser.parser_version,
                "previous_available": original["structured_jd"] is not None,
                "previous_failure_code": original["failure_code"],
                "failure_code": failure,
                "diagnostics": diagnostics,
                "consumed_archived_response_indices": client.consumed,
                "structured_jd": job.model_dump(mode="json") if job else None,
                "candidate_checks": checks,
                "discovery_cohort": next(
                    c for c in discovery.checks if c["field"] == "graduation_year"
                ),
            }
        )
    if hashes != {str(path): sha256(path) for path in frozen_paths}:
        raise ValueError("原运行或冻结标签发生变化")
    source_paths = [
        "src/domain/graduation.py",
        "src/domain/education.py",
        "src/domain/analysis.py",
        "src/services/product_jd_runtime_guards.py",
        "src/services/product_jd_education_parser.py",
        "src/services/product_jd_execution.py",
        "src/services/discovery_matching.py",
        "src/services/eligibility_checker.py",
        "src/services/education_evaluator.py",
        "scripts/replay_product_jd_shared_validation.py",
    ]
    report = {
        "kind": "fixed_response_counterfactual_replay",
        "new_model_api_calls": 0,
        "runs": len(rows),
        "original_inputs_unchanged": True,
        "reference_review": str(review_path) if review_path.exists() else None,
        "modes": {
            mode: {
                "runs": sum(r["mode"] == mode for r in rows),
                "previous_parsed": sum(
                    r["mode"] == mode and r["previous_available"] for r in rows
                ),
                "replay_parsed": sum(
                    r["mode"] == mode and r["structured_jd"] is not None for r in rows
                ),
                "previous": metrics(rows, mode, previous=True),
                "replay": metrics(rows, mode),
            }
            for mode in ("single_call", "two_stage")
        },
        "limitations": [
            "Uses recorded outputs, including existing repairs; no new model inference or latency measurement.",
            "Skips transport failures; missing recorded responses remain unavailable.",
            "Synthetic candidates and assistant reference review; education/cohort only, not full suitability.",
            "Major/research-direction reference boundaries remain disputed; replay is development evidence, not a new benchmark.",
        ],
        "input_hashes": hashes,
        "source_hashes": {path: sha256(Path(path)) for path in source_paths},
    }
    destination.mkdir(parents=True)
    for name, data in (
        ("predictions.json", {"results": rows}),
        ("report.json", report),
    ):
        (destination / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "output": str(destination),
                "runs": len(rows),
                "modes": {
                    m: {
                        k: v
                        for k, v in values.items()
                        if k not in {"previous", "replay"}
                    }
                    for m, values in report["modes"].items()
                },
            },
            ensure_ascii=False,
        )
    )


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("baseline", type=Path)
    cli.add_argument("--output", required=True, type=Path)
    args = cli.parse_args()
    asyncio.run(replay(args.baseline, args.output))


if __name__ == "__main__":
    main()
