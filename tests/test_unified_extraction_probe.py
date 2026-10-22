from __future__ import annotations

import argparse
import hashlib
import json

import pytest

import scripts.run_unified_extraction_probe as extraction_probe
from scripts.build_unified_dev50_granularity_v2 import (
    build_granularity_v2_manifest,
)
from scripts.evaluate_unified_evidence_lines import build_report
from scripts.run_unified_causal_probe import DEFAULT_CASE_IDS, _validate_output
from scripts.run_unified_extraction_probe import _build_recompiled_report
from src.services.unified_jd_extraction import (
    UNIFIED_EXTRACTION_COMPILER_VERSION,
)


def _source_payload(manifest, case) -> dict:
    return {
        "experiment_version": "source-v1",
        "manifest": {
            "path": "manifest.json",
            "sha256": "placeholder",
            "dataset_version": manifest.dataset_version,
        },
        "model": {"name": "saved-model"},
        "case_ids": [case.id],
        "case_rationales": {case.id: "test"},
        "repetitions": 1,
        "records": [
            {
                "case_id": case.id,
                "repetition": 1,
                "request": {},
                "raw_output": {"fact_mentions": [], "clauses": []},
                "compiled_output": None,
                "model_contract_valid": True,
                "compilation_diagnostics": [
                    {
                        "code": "old_compilation_failed",
                        "path": "output",
                        "message": "recorded failure",
                    }
                ],
                "failure_code": "unified_output_invalid",
                "validation": _validate_output(None, case.raw_content),
                "diagnostics": {},
            }
        ],
    }


def test_recompiled_report_keeps_recorded_and_posthoc_results_separate(
    tmp_path,
) -> None:
    manifest, _ = build_granularity_v2_manifest()
    case = manifest.cases[0]
    source_path = tmp_path / "source-experiment.json"
    source_path.write_text("{}\n", encoding="utf-8")
    payload = _source_payload(manifest, case)

    report = _build_recompiled_report(
        payload,
        manifest,
        tmp_path / "missing-baseline.json",
        source_path,
    )

    assert report["new_model_call_count"] == 0
    assert report["source_model_call_count"] == 1
    assert report["recorded_compilation"]["compiled_success_count"] == 0
    assert report["posthoc_recompilation"]["compiled_success_count"] == 1
    assert (
        report["posthoc_recompilation"]["compiler_version"]
        == UNIFIED_EXTRACTION_COMPILER_VERSION
    )
    assert report["record_results"][0]["compiled_output_changed"] is True
    assert report["record_results"][0]["raw_output_sha256"] is not None
    dimensional = report["posthoc_recompilation"][
        "dimensional_evaluation_by_repetition"
    ][0]
    assert dimensional["evaluation_version"] == "unified-jd-evaluator-v2"
    assert dimensional["dimensions"]["facts"]["macro_f1"] > 0


def test_evidence_line_candidates_fully_support_five_case_probe(tmp_path) -> None:
    manifest, _ = build_granularity_v2_manifest()
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "posthoc_recompilation": {
                    "dimensional_evaluation_by_repetition": [
                        {
                            "repetition": 1,
                            "dimensions": {
                                "evidence_spans": {
                                    "clause_evidence": {
                                        "expected_count": 77,
                                        "predicted_count": 68,
                                        "overlap": {
                                            "tp": 68,
                                            "recall": 68 / 77,
                                        },
                                    }
                                }
                            },
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    report = build_report(manifest, DEFAULT_CASE_IDS, baseline_path)

    assert report["model_call_count"] == 0
    assert report["aggregate"] == {
        "expected_clause_count": 77,
        "semantic_evidence_line_count": 71,
        "support_counts": {"contains_expected": 10, "exact": 67},
        "fully_supported_count": 77,
        "fully_supported_recall": 1.0,
        "overlap_supported_count": 77,
        "overlap_supported_recall": 1.0,
        "fragmented_expected_count": 0,
        "uncovered_expected_count": 0,
        "orphan_semantic_line_count": 0,
        "shared_evidence_line_count": 5,
    }


@pytest.mark.asyncio
async def test_recompile_only_does_not_load_model_settings(
    tmp_path,
    monkeypatch,
) -> None:
    manifest, _ = build_granularity_v2_manifest()
    manifest = manifest.model_copy(update={"cases": [manifest.cases[0]]})
    case = manifest.cases[0]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    source_path = tmp_path / "source-experiment.json"
    payload = _source_payload(manifest, case)
    payload["manifest"]["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    source_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report_path = tmp_path / "recompiled-report.json"

    def fail_if_called():
        raise AssertionError("offline recompilation must not load model settings")

    monkeypatch.setattr(extraction_probe, "get_settings", fail_if_called)
    arguments = argparse.Namespace(
        manifest=manifest_path,
        output=source_path,
        report=report_path,
        baseline_report=tmp_path / "missing-baseline.json",
        case_ids=[case.id],
        repetitions=1,
        concurrency=1,
        resume=False,
        recompile_only=True,
    )

    exit_code = await extraction_probe._run(arguments)

    assert exit_code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["new_model_call_count"] == 0
    assert report["posthoc_recompilation"]["compiled_success_count"] == 1
