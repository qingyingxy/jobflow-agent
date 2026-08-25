from pathlib import Path

from src.evaluation.assisted_apply import (
    AssistedApplyManifest,
    evaluate_assisted_apply,
    render_markdown,
)


def test_m19_assisted_apply_fixture_thresholds() -> None:
    manifest = AssistedApplyManifest.model_validate_json(
        Path("datasets/m19_assisted_apply_manifest.json").read_text(encoding="utf-8")
    )
    report = evaluate_assisted_apply(manifest)

    assert report["case_count"] == 14
    assert report["passed_case_count"] == 14
    assert report["all_thresholds_passed"] is True
    assert report["metrics"]["sensitive_field_misfill_rate"]["value"] == 0
    assert report["metrics"]["false_submitted_rate"]["value"] == 0
    assert report["ready_to_submit_seconds"] is None
    pseudo_success = next(
        case
        for case in report["cases"]
        if case["id"] == "generic-thank-you-pseudo-success"
    )
    assert pseudo_success["receipt_created"] is False
    non_resume_upload = next(
        case
        for case in report["cases"]
        if case["id"] == "non-resume-file-handoff"
    )
    assert non_resume_upload["actual_fill_values"] == {}
    assert non_resume_upload["actual_handoff_codes"] == [
        "unsupported_field_control"
    ]
    assert "只覆盖离线结构化 Mock ATS" in render_markdown(report)
