from __future__ import annotations

import asyncio
from pathlib import Path

from src.evaluation.discovery_agent import (
    DiscoveryEvaluationManifest,
    evaluate_discovery_agent,
    render_markdown,
)

MANIFEST_PATH = Path("datasets/m12_discovery_agent_manifest.json")


def _load_manifest() -> DiscoveryEvaluationManifest:
    return DiscoveryEvaluationManifest.model_validate_json(
        MANIFEST_PATH.read_text(encoding="utf-8")
    )


def test_discovery_agent_manifest_is_versioned_and_complete() -> None:
    manifest = _load_manifest()

    assert manifest.manifest_version == "m12-discovery-agent-manifest-v1"
    assert manifest.dataset_version == "m12-discovery-agent-fixtures-2026-08-09-v1"
    assert len(manifest.cases) == 13
    assert len(manifest.thresholds) == 9


def test_discovery_agent_control_plane_evaluation_passes() -> None:
    report = asyncio.run(evaluate_discovery_agent(_load_manifest()))

    assert report["passed_case_count"] == 13
    assert report["case_count"] == 13
    assert report["all_thresholds_passed"] is True
    assert all(metric["passed"] for metric in report["metrics"].values())


def test_discovery_agent_report_keeps_claim_boundary_visible() -> None:
    report = asyncio.run(evaluate_discovery_agent(_load_manifest()))
    markdown = render_markdown(report)

    assert "离线确定性 Fixture" in markdown
    assert "不能扩展为“真实官网搜索 100% 准确”" in markdown
    assert report["scope"]["live_source_results_included"] is False
