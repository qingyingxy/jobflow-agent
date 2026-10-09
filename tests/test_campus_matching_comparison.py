import json
from pathlib import Path

import pytest

from scripts.compare_campus_matching import (
    DEFAULT_SPEC,
    citation_stats,
    read_json,
    select_cases,
    summarize,
)
from src.domain.job import JobRequirement
from src.domain.matching import EvidenceRecord
from src.infrastructure.llm_client import FakeModelClient
from src.services.batch_evidence_matcher import BatchEvidenceMatcher


def test_preregistered_cases_cover_all_requirements_without_exposing_labels_to_model():
    spec = read_json(DEFAULT_SPEC)
    if not Path(spec["source_dataset"]).exists():
        pytest.skip("Local licensed JD snapshots are not checked into the repository")
    cases = select_cases(spec, read_json(spec["source_dataset"]))
    assert len(cases) == 8
    assert len({c["source"]["company"] for c in cases}) == 8
    candidate = read_json(spec["candidate_file"])
    evidence = [EvidenceRecord.model_validate(e) for e in candidate["evidence"]]
    for case in cases:
        requirements = [
            JobRequirement.model_validate(i["requirement"])
            for i in case["requirements"]
        ]
        request = BatchEvidenceMatcher(FakeModelClient()).build_request(
            requirements, evidence
        )
        payload = json.loads(request.messages[-1].content)
        assert set(payload) == {"requirements", "evidence"}
        assert all("reference" not in r for r in payload["requirements"])


def test_raw_citation_metric_counts_bad_quotes_before_validation_removes_them():
    item = EvidenceRecord(
        id="ev_1", user_id="a", title="Python", claim="实现混合检索", skills=["RAG"]
    )
    raw = {
        "judgments": [
            {
                "requirement_index": 0,
                "support_level": "supported",
                "explanation": "实现能力",
                "citations": [
                    {"evidence_id": "ev_1", "quote": "混合检索"},
                    {"evidence_id": "ev_1", "quote": "RAG"},
                    {"evidence_id": "foreign", "quote": "混合检索"},
                ],
            }
        ]
    }
    stats = citation_stats(raw, [item], 1)
    assert stats["raw_citations"] == 3 and stats["valid_raw_citations"] == 1
    assert stats["raw_coverage_valid"]


def test_strict_metrics_exclude_ambiguous_labels_and_count_false_passes():
    def row(allowed, prediction):
        return {
            "reference": {"allowed": allowed},
            "match": {"support_level": prediction, "validation_status": "passed"},
            "within_reference": prediction in allowed,
        }

    result = summarize(
        [
            {
                "mode": "local",
                "duration_ms": 5,
                "call_count": 0,
                "rows": [
                    row(["supported"], "partial"),
                    row(["partial"], "supported"),
                    row(["supported", "partial"], "supported"),
                ],
            }
        ]
    )["local"]
    assert result["strict_reference_count"] == 2
    assert result["false_full_support"] == 1
    assert result["missed_supported"] == 1
    assert result["strict_support_recall"] == 0
    assert result["within_ambiguous_reference_count"] == 1
    assert result["cost_amount"] is None
