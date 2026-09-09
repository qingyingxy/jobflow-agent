from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.finalize_product_jd_test100_evaluation import (
    DEFAULT_FREEZE_RECEIPT,
    DEFAULT_LABELS,
    DEFAULT_PREDICTIONS,
    DEFAULT_REPORT,
    EXPECTED_CASE_COUNT,
    EXPECTED_DATASET_VERSION,
    EXPECTED_PREDICTION_VERSION,
    build_evaluation_receipt,
)

LOCAL_ARTIFACTS_AVAILABLE = all(
    path.exists()
    for path in (
        DEFAULT_LABELS,
        DEFAULT_FREEZE_RECEIPT,
        DEFAULT_PREDICTIONS,
        DEFAULT_REPORT,
    )
)


@pytest.mark.skipif(
    not LOCAL_ARTIFACTS_AVAILABLE,
    reason="formal test-100 artifacts missing",
)
def test_formal_test100_receipt_recomputes_and_binds_results() -> None:
    receipt = build_evaluation_receipt()

    assert receipt["status"] == "formal_evaluation_complete"
    assert receipt["protocol"]["formal_run_count"] == 1
    assert receipt["protocol"]["labels_frozen_before_prediction"] is True
    assert receipt["protocol"]["predictions_used_to_edit_labels"] is False
    assert receipt["counts"]["case_count"] == EXPECTED_CASE_COUNT
    assert receipt["counts"]["prediction_count"] == EXPECTED_CASE_COUNT
    assert receipt["counts"]["parse_success_count"] == EXPECTED_CASE_COUNT
    assert receipt["counts"]["parse_failure_count"] == 0
    assert receipt["counts"]["schema_valid_count"] == EXPECTED_CASE_COUNT
    assert receipt["counts"]["evidence_valid_count"] == EXPECTED_CASE_COUNT
    assert receipt["counts"]["model_call_count"] == 201
    assert receipt["counts"]["model_call_count_distribution"] == {"2": 99, "3": 1}
    assert receipt["counts"]["failure_codes"] == {}
    assert receipt["counts"]["expected_any_of_group_count"] == 183
    assert receipt["counts"]["expected_any_of_item_count"] == 633
    assert receipt["artifacts"]["labels"]["version"] == EXPECTED_DATASET_VERSION
    assert receipt["artifacts"]["predictions"]["version"] == (
        EXPECTED_PREDICTION_VERSION
    )


@pytest.mark.skipif(
    not LOCAL_ARTIFACTS_AVAILABLE,
    reason="formal test-100 artifacts missing",
)
def test_formal_test100_receipt_rejects_changed_report(tmp_path: Path) -> None:
    report = json.loads(DEFAULT_REPORT.read_text(encoding="utf-8"))
    report["primary_metrics"]["facts_value_macro_f1"] = 1.0
    changed_report = tmp_path / "changed-report.json"
    changed_report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="recomputation"):
        build_evaluation_receipt(report_path=changed_report)
