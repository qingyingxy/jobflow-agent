from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.domain.ats_assistance import AtsFieldRisk, AtsProvider
from src.evaluation.trusted_discovery import MetricThreshold
from src.services.ats_adapters import (
    AtsAdapterError,
    AtsAdapterRegistry,
    AtsFieldDescriptor,
    AtsPageSnapshot,
    AtsSubmissionEvidence,
    blocking_reasons,
    plan_hash,
)


class AssistedApplyField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    name: str
    input_type: str
    required: bool
    selector: str
    options: list[str] = Field(default_factory=list)


class AssistedApplyCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    provider: AtsProvider
    description: str
    gates: list[str] = Field(default_factory=list)
    fields: list[AssistedApplyField]
    changed_fields: list[AssistedApplyField] | None = None
    preparation_issues: list[str] = Field(default_factory=list)
    confirm_fields: list[str] = Field(default_factory=list)
    expected_fill_values: dict[str, str]
    expected_handoff_codes: list[str]
    submission_success: bool
    submission_text: str
    receipt_expected: bool
    expected_resume_asset_id: str | None = None


class AssistedApplyManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: str
    dataset_version: str
    purpose: str
    scope_boundary: str
    thresholds: dict[str, MetricThreshold]
    packet: dict[str, Any]
    cases: list[AssistedApplyCase] = Field(min_length=1)

    @field_validator("cases")
    @classmethod
    def unique_case_ids(
        cls, cases: list[AssistedApplyCase]
    ) -> list[AssistedApplyCase]:
        ids = [case.id for case in cases]
        if len(ids) != len(set(ids)):
            raise ValueError("M19 评测 case id 必须唯一")
        return cases


def _snapshot(
    case: AssistedApplyCase,
    fields: list[AssistedApplyField],
) -> AtsPageSnapshot:
    host = (
        "boards.greenhouse.io"
        if case.provider is AtsProvider.GREENHOUSE
        else "jobs.lever.co"
    )
    url = f"https://{host}/m19-fixture/{case.id}"
    return AtsPageSnapshot(
        requested_url=url,
        final_url=url,
        title=case.description,
        visible_text=case.submission_text,
        fields=tuple(
            AtsFieldDescriptor(
                key=field.key,
                label=field.label,
                name=field.name,
                input_type=field.input_type,
                required=field.required,
                selector=field.selector,
                options=tuple(field.options),
            )
            for field in fields
        ),
        provider_hint=case.provider,
        gates=tuple(case.gates),
    )


def _evaluate_case(case: AssistedApplyCase, packet: dict[str, Any]) -> dict[str, Any]:
    snapshot = _snapshot(case, case.fields)
    adapter = AtsAdapterRegistry().detect(snapshot)
    initial_plan = adapter.map_fields(snapshot, packet, [])
    initial_by_key = {str(item["field_key"]): item for item in initial_plan}
    confirmations = [
        {
            "field_key": key,
            "value_hash": initial_by_key[key].get("value_hash"),
        }
        for key in case.confirm_fields
        if key in initial_by_key and initial_by_key[key].get("value_hash")
    ]
    field_plan = adapter.map_fields(snapshot, packet, confirmations)
    operations = adapter.fill(field_plan)
    actual_fill_values = {operation.field_key: operation.value for operation in operations}
    reasons = blocking_reasons(snapshot, field_plan)
    reasons.extend(
        {
            "code": issue,
            "category": "verification",
            "message": "浏览器填写结果未通过确定性验证",
        }
        for issue in case.preparation_issues
    )
    if case.changed_fields is not None:
        changed = _snapshot(case, case.changed_fields)
        changed_plan = adapter.map_fields(changed, packet, confirmations)
        if (
            changed.fingerprint != snapshot.fingerprint
            or plan_hash(changed_plan) != plan_hash(field_plan)
        ):
            reasons.append(
                {
                    "code": "ats_page_changed",
                    "category": "verification",
                    "message": "提交前页面或字段计划已变化",
                }
            )

    actual_handoff_codes = sorted({str(item["code"]) for item in reasons})
    expected_handoff_codes = sorted(case.expected_handoff_codes)
    receipt_created = False
    receipt_error: str | None = None
    if not actual_handoff_codes:
        evidence = AtsSubmissionEvidence(
            success=case.submission_success,
            confirmation_text=case.submission_text,
            confirmation_url=snapshot.final_url,
            application_number=None,
            captured_at=datetime.now(UTC),
            failure_code=None if case.submission_success else "ats_submission_unverified",
        )
        try:
            adapter.capture_receipt(evidence)
            receipt_created = True
        except AtsAdapterError as error:
            receipt_error = error.code

    sensitive_misfills = [
        str(item["field_key"])
        for item in field_plan
        if item.get("risk") != AtsFieldRisk.LOW.value
        and item.get("action") == "FILL"
        and str(item.get("field_key")) not in case.confirm_fields
    ]
    sensitive_fill_count = sum(
        item.get("risk") != AtsFieldRisk.LOW.value
        and item.get("action") == "FILL"
        for item in field_plan
    )
    resume_values = [
        operation.value
        for operation in operations
        if initial_by_key.get(operation.field_key, {}).get("canonical_name") == "resume"
    ]
    resume_correct = (
        True
        if case.expected_resume_asset_id is None
        else resume_values == [case.expected_resume_asset_id]
    )
    fill_correct = actual_fill_values == case.expected_fill_values
    compared_field_keys = set(actual_fill_values) | set(case.expected_fill_values)
    correct_field_count = sum(
        actual_fill_values.get(key) == case.expected_fill_values.get(key)
        for key in compared_field_keys
    )
    handoff_correct = actual_handoff_codes == expected_handoff_codes
    receipt_correct = receipt_created is case.receipt_expected
    return {
        "id": case.id,
        "provider": case.provider.value,
        "description": case.description,
        "actual_fill_values": actual_fill_values,
        "expected_fill_values": case.expected_fill_values,
        "actual_handoff_codes": actual_handoff_codes,
        "expected_handoff_codes": expected_handoff_codes,
        "receipt_created": receipt_created,
        "receipt_expected": case.receipt_expected,
        "receipt_error": receipt_error,
        "sensitive_misfills": sensitive_misfills,
        "sensitive_fill_count": sensitive_fill_count,
        "field_comparison_count": len(compared_field_keys),
        "correct_field_count": correct_field_count,
        "resume_correct": resume_correct,
        "fill_correct": fill_correct,
        "handoff_correct": handoff_correct,
        "receipt_correct": receipt_correct,
        "manual_intervention_count": len(actual_handoff_codes),
        "passed": (
            fill_correct
            and handoff_correct
            and receipt_correct
            and resume_correct
            and not sensitive_misfills
        ),
    }


def evaluate_assisted_apply(manifest: AssistedApplyManifest) -> dict[str, Any]:
    cases = [_evaluate_case(case, manifest.packet) for case in manifest.cases]
    compared_fields = sum(case["field_comparison_count"] for case in cases)
    correct_fields = sum(case["correct_field_count"] for case in cases)
    resume_case_ids = {
        case.id
        for case in manifest.cases
        if case.expected_resume_asset_id is not None
    }
    resume_cases = [case for case in cases if case["id"] in resume_case_ids]
    receipt_cases = [case for case in cases if case["receipt_expected"]]
    negative_receipt_cases = [case for case in cases if not case["receipt_expected"]]
    planned_sensitive_fills = sum(case["sensitive_fill_count"] for case in cases)
    sensitive_misfills = sum(len(case["sensitive_misfills"]) for case in cases)
    metric_values = {
        "field_fill_accuracy": (
            correct_fields / compared_fields if compared_fields else 1.0
        ),
        "resume_version_accuracy": (
            sum(case["resume_correct"] for case in resume_cases) / len(resume_cases)
            if resume_cases
            else 1.0
        ),
        "human_handoff_accuracy": sum(case["handoff_correct"] for case in cases)
        / len(cases),
        "submission_receipt_coverage": (
            sum(case["receipt_created"] for case in receipt_cases) / len(receipt_cases)
            if receipt_cases
            else 1.0
        ),
        "sensitive_field_misfill_rate": (
            sensitive_misfills / planned_sensitive_fills
            if planned_sensitive_fills
            else 0.0
        ),
        "false_submitted_rate": (
            sum(case["receipt_created"] for case in negative_receipt_cases)
            / len(negative_receipt_cases)
            if negative_receipt_cases
            else 0.0
        ),
    }
    metrics = {
        name: {
            "value": value,
            "threshold": manifest.thresholds[name].model_dump(exclude_none=True),
            "passed": _threshold_passed(value, manifest.thresholds[name]),
        }
        for name, value in metric_values.items()
    }
    return {
        "manifest_version": manifest.manifest_version,
        "dataset_version": manifest.dataset_version,
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "fixture_only": True,
            "live_ats_results_included": False,
            "workflow_duration_available": False,
            "boundary": manifest.scope_boundary,
        },
        "case_count": len(cases),
        "passed_case_count": sum(case["passed"] for case in cases),
        "all_thresholds_passed": all(metric["passed"] for metric in metrics.values()),
        "manual_intervention_count": sum(
            case["manual_intervention_count"] for case in cases
        ),
        "ready_to_submit_seconds": None,
        "metrics": metrics,
        "cases": cases,
    }


def _threshold_passed(value: float, threshold: MetricThreshold) -> bool:
    if threshold.minimum is not None:
        return value >= threshold.minimum
    assert threshold.maximum is not None
    return value <= threshold.maximum


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# M19 Assisted Apply Fixture Evaluation",
        "",
        "> 本报告只覆盖离线结构化 Mock ATS，不代表真实 ATS 兼容率、真实投递成功率或用户耗时。",
        "",
        f"- Cases: {report['passed_case_count']}/{report['case_count']}",
        f"- Thresholds passed: {report['all_thresholds_passed']}",
        f"- Manual interventions: {report['manual_intervention_count']}",
        "- Ready-to-submit duration: not available in deterministic fixtures",
        "",
        "## Metrics",
        "",
        "| Metric | Value | Passed |",
        "| --- | ---: | --- |",
    ]
    for name, metric in report["metrics"].items():
        lines.append(f"| `{name}` | {metric['value']:.3f} | {metric['passed']} |")
    lines.extend(["", "## Cases", "", "| Case | Provider | Passed | Handoff | Receipt |", "| --- | --- | --- | --- | --- |"])
    for case in report["cases"]:
        handoff = ", ".join(case["actual_handoff_codes"]) or "none"
        lines.append(
            f"| `{case['id']}` | {case['provider']} | {case['passed']} | {handoff} | {case['receipt_created']} |"
        )
    lines.append("")
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run M19 Assisted Apply evaluation")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output")
    parser.add_argument("--markdown")
    return parser.parse_args()


def main() -> None:
    arguments = _parse_args()
    manifest = AssistedApplyManifest.model_validate_json(
        Path(arguments.manifest).read_text(encoding="utf-8")
    )
    report = evaluate_assisted_apply(manifest)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if arguments.output:
        output_path = Path(arguments.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized + "\n", encoding="utf-8")
    if arguments.markdown:
        markdown_path = Path(arguments.markdown)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
