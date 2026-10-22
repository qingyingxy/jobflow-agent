from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from scripts.run_unified_jd_model_first_v3_surface_probe import (
    DEFAULT_PROBE_MANIFEST,
    DEFAULT_RAW_RESPONSE,
    DEFAULT_REPORT,
)
from src.config import get_settings
from src.evaluation.model_first_v3_probe import analyze_v3_surface_probe
from src.evaluation.unified_models import UnifiedEvaluationManifest

OUTPUT = (
    Path(__file__).resolve().parents[1] / "artifacts/evaluation/"
    "unified-jd-model-first-v3-surface-probe-case121-offline-analysis-2026-09-05.json"
)


def _write_new_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(rendered + "\n")


def main() -> int:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite offline analysis: {OUTPUT}")
    manifest = UnifiedEvaluationManifest.model_validate_json(
        DEFAULT_PROBE_MANIFEST.read_text(encoding="utf-8")
    )
    raw_artifact = json.loads(DEFAULT_RAW_RESPONSE.read_text(encoding="utf-8"))
    probe_report = json.loads(DEFAULT_REPORT.read_text(encoding="utf-8"))
    case = manifest.cases[0]
    if case.expected is None:
        raise ValueError("probe case must retain frozen expected labels")
    raw_output = raw_artifact.get("raw_model_output")
    if not isinstance(raw_output, dict):
        raise TypeError("probe raw model output is missing")

    settings = get_settings()
    configured_format = settings.llm_response_format.strip().lower()
    hostname = urlparse(settings.llm_base_url or "").hostname
    resolved_format = configured_format
    if configured_format == "auto":
        resolved_format = (
            "json_object" if hostname == "api.deepseek.com" else "json_schema"
        )
    analysis = analyze_v3_surface_probe(
        raw_output=raw_output,
        raw_content=case.raw_content,
        baseline_surface=probe_report["baseline_surface"],
        expected=case.expected,
    )
    payload = {
        "analysis_version": "model-first-v3-surface-probe-offline-analysis-v1",
        "case_id": case.id,
        "model_api_called": False,
        "model_call_count": 0,
        "source_raw_response": DEFAULT_RAW_RESPONSE.as_posix(),
        "provider_response_format": {
            "configured": configured_format,
            "resolved": resolved_format,
            "server_side_json_schema_enforced": resolved_format == "json_schema",
        },
        **analysis,
    }
    _write_new_json(OUTPUT, payload)
    print(
        "v3 surface probe offline analysis complete "
        f"schema_format={resolved_format} "
        f"surface_exact={analysis['surface_pairing']['clause_items']['full_jd_exact_count']}/"
        f"{analysis['surface_pairing']['clause_items']['emitted_count']} "
        f"semantic_surface_different="
        f"{analysis['semantic_surface_separation']['different_count']} "
        f"topology_followed="
        f"{analysis['mechanism_checks']['required_response_topology_was_followed']}"
    )
    print(f"analysis={OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
