from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.build_product_jd_sealed_label_draft import LABELS, build_dataset

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "artifacts"
    / "evaluation"
    / "product-jd-sealed30-sources-v1-2026-09-06.json"
)


def test_blind_sealed_label_draft_is_complete_and_reproducible(tmp_path: Path) -> None:
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    output = tmp_path / "sealed-label-draft.json"

    payload = build_dataset(SOURCE, output)

    assert len(LABELS) == 30
    assert payload["case_count"] == len(payload["cases"]) == 30
    assert payload["split"] == "sealed_test"
    assert payload["label_status"] == "codex_blind_draft_requires_human_review"
    assert all(case["expected"] is not None for case in payload["cases"])
    assert all(
        case["label_revision"]["predictions_read_before_annotation"] is False
        for case in payload["cases"]
    )
    assert all(
        case["label_revision"]["human_reviewed"] is False
        for case in payload["cases"]
    )
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == source_hash
    assert json.loads(output.read_text(encoding="utf-8")) == payload
