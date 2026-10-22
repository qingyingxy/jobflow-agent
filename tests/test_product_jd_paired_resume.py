import pytest

from scripts.resume_product_jd_paired_acceptance import missing_pairs


def test_missing_pairs_preserves_completed_failures_and_mode_order():
    cases = [{"id": str(i)} for i in range(4)]
    rows = [
        {"case_id": str(i), "mode": mode, "failure_code": "timeout"}
        for i in range(2)
        for mode in ("single_call", "two_stage")
    ]
    assert missing_pairs(cases, rows) == cases[2:]


@pytest.mark.parametrize("kind", ["duplicate", "unknown", "partial", "order"])
def test_invalid_recovery_state_is_rejected(kind):
    cases = [{"id": "0"}, {"id": "1"}]
    row = {"case_id": "0", "mode": "single_call"}
    rows = {
        "duplicate": [row, row],
        "unknown": [{**row, "case_id": "absent"}],
        "partial": [row],
        "order": [row, {**row, "mode": "two_stage"}],
    }[kind]
    with pytest.raises(ValueError):
        missing_pairs(cases, rows)
