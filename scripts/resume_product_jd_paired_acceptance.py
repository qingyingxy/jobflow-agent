"""Resume complete missing pairs without editing the frozen original driver."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from urllib.parse import urlsplit

from scripts.run_product_jd_paired_acceptance import (
    DATASET,
    MODES,
    build_report,
    file_hash,
    pair_integrity,
    run_paired,
    write_json,
)
from src.config import Settings


def missing_pairs(cases, rows):
    keys = [(r["case_id"], r["mode"]) for r in rows]
    expected = {(c["id"], mode) for c in cases for mode in MODES}
    if len(keys) != len(set(keys)) or not set(keys) <= expected:
        raise ValueError("Saved results contain duplicate or unknown mode runs")
    pending = []
    for index, case in enumerate(cases):
        present = {mode for mode in MODES if (case["id"], mode) in keys}
        if not present:
            if index % 2 != len(pending) % 2:
                raise ValueError(
                    "Recovery would change the frozen alternating mode order"
                )
            pending.append(case)
        elif present != set(MODES):
            raise ValueError("This recovery driver supports wholly missing pairs only")
    return pending


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("directory", type=Path)
    cli.add_argument("--live", action="store_true")
    args = cli.parse_args()
    root = args.directory
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    cases = json.loads((root / "cases.json").read_text(encoding="utf-8"))["cases"]
    original = json.loads((root / "predictions.json").read_text(encoding="utf-8"))[
        "results"
    ]
    pending = missing_pairs(cases, original)
    if not all(file_hash(Path(p)) == h for p, h in manifest["source_hashes"].items()):
        cli.error("Frozen implementation or inputs changed; cannot resume")
    settings = Settings(llm_max_retries=0).model_copy(
        update={"llm_timeout_seconds": manifest["request_timeout"]}
    )
    for field, actual in {
        "model": settings.llm_model,
        "provider": settings.structured_model_provider,
        "reasoning_effort": settings.llm_reasoning_effort,
        "response_format": settings.llm_response_format,
    }.items():
        if manifest[field] != actual:
            cli.error(f"Configured {field} changed; cannot resume")
    if not args.live:
        print(
            json.dumps(
                {
                    "completed": len(original),
                    "pending": 2 * len(pending),
                    "frozen_files_match": True,
                }
            )
        )
        return
    if (
        not pending
        or (root / "report.json").exists()
        or (root / "resume_manifest.json").exists()
    ):
        cli.error("No pending pairs or recovery already started")
    write_json(root / "predictions.before-resume.json", {"results": original})
    recovery = {
        "created_at": datetime.now(UTC).isoformat(),
        "preserved_runs": len(original),
        "pending_pairs": [c["id"] for c in pending],
        "before_predictions_sha256": file_hash(root / "predictions.json"),
        "driver_sha256": file_hash(Path(__file__)),
        "endpoint_host": urlsplit(settings.llm_base_url).hostname,
        "limitations": [
            "The process was interrupted; completed results are preserved, only wholly missing pairs resume.",
            "Unpersisted in-flight requests and their elapsed time are unavailable; recorded calls are a lower bound.",
            "Final wall time includes interruption/setup gaps and is not an uninterrupted performance run.",
        ],
    }
    write_json(root / "resume_manifest.json", recovery)
    runtime_args = SimpleNamespace(
        **{k: manifest[k] for k in ("concurrency", "validation_retries", "run_timeout")}
    )
    started = perf_counter()

    def persist(new_rows):
        combined = original + new_rows
        write_json(root / "predictions.json", {"results": combined})
        write_json(
            root / "progress.json",
            {
                **pair_integrity(combined, cases),
                "resume_elapsed_seconds": round(perf_counter() - started, 2),
            },
        )

    new_rows = asyncio.run(run_paired(pending, settings, runtime_args, persist))
    total_wall = (
        datetime.now(UTC) - datetime.fromisoformat(manifest["created_at"])
    ).total_seconds()
    report = build_report(
        json.loads(DATASET.read_text(encoding="utf-8")),
        cases,
        original + new_rows,
        manifest,
        total_wall,
    )
    report["recovery"] = {
        **recovery,
        "resumed_runs": len(new_rows),
        "resume_active_seconds": round(perf_counter() - started, 3),
        "preserved_results_unchanged": (original + new_rows)[: len(original)]
        == original,
    }
    write_json(root / "report.json", report)
    print(
        json.dumps(
            {
                "pairs": report["pairs"],
                "frozen_files_unchanged": report["frozen_files_unchanged"],
                "recovery": report["recovery"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
