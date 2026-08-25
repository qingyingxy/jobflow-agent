from __future__ import annotations

import asyncio
from pathlib import Path

from src.evaluation.trusted_discovery import (
    TrustedDiscoveryManifest,
    evaluate_trusted_discovery,
    render_markdown,
)

MANIFEST_PATH = Path("datasets/m13_trusted_discovery_manifest.json")


def _manifest() -> TrustedDiscoveryManifest:
    return TrustedDiscoveryManifest.model_validate_json(
        MANIFEST_PATH.read_text(encoding="utf-8")
    )


def test_m13_manifest_is_versioned_and_complete() -> None:
    manifest = _manifest()

    assert manifest.manifest_version == "m13-trusted-discovery-manifest-v1"
    assert len(manifest.cases) == 9
    assert len(manifest.thresholds) == 6


def test_m13_trusted_discovery_evaluation_passes() -> None:
    report = asyncio.run(evaluate_trusted_discovery(_manifest()))

    assert report["passed_case_count"] == 9
    assert report["case_count"] == 9
    assert report["all_thresholds_passed"] is True
    assert report["metrics"]["non_job_false_acceptance_rate"]["value"] == 0
    assert report["metrics"]["dedupe_accuracy"]["value"] == 1
    assert report["verification_failure_distribution"] == {
        "lead_not_job_page": 1,
        "url_fetch_failed": 2,
    }


def test_m13_report_keeps_fixture_boundary_visible() -> None:
    report = asyncio.run(evaluate_trusted_discovery(_manifest()))
    markdown = render_markdown(report)

    assert "离线确定性 Fixture" in markdown
    assert "真实官网召回率" in markdown
    assert report["scope"]["live_source_results_included"] is False
