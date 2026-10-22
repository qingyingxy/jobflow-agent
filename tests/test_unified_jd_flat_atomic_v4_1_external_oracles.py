from __future__ import annotations

from scripts.run_unified_jd_flat_atomic_v4_1_absent_fact_omission_oracle import (
    omit_empty_absent_fact_placeholders,
)
from scripts.run_unified_jd_flat_atomic_v4_1_long_evidence_span_oracle import (
    represent_long_self_sufficient_evidence,
)


def test_omission_oracle_changes_only_exact_empty_absent_fact() -> None:
    eligible = {
        "field": "deadline",
        "raw_items": [],
        "level": None,
        "source_text": "",
    }
    level_present = {**eligible, "level": "required"}
    source_present = {**eligible, "source_text": "deadline"}
    frozen = {
        "records": [
            {
                "case_id": "case-1",
                "raw_model_output": {
                    "fact_mentions": [eligible, level_present, source_present],
                    "clause_atoms": [],
                },
            }
        ]
    }

    treatment, audit = omit_empty_absent_fact_placeholders(frozen)

    assert frozen["records"][0]["raw_model_output"]["fact_mentions"] == [
        eligible,
        level_present,
        source_present,
    ]
    assert treatment["records"][0]["raw_model_output"]["fact_mentions"] == [
        level_present,
        source_present,
    ]
    assert audit == [
        {
            "record_index": 0,
            "case_id": "case-1",
            "removed": [{"fact_index": 0, "before": eligible}],
        }
    ]


def test_long_span_oracle_changes_only_self_sufficient_exact_surface() -> None:
    eligible = {
        "semantic_item": "target",
        "surface_item": "target",
        "source_text": "x" * 241 + "target",
    }
    divergent = {
        "semantic_item": "interpreted target",
        "surface_item": "target",
        "source_text": "x" * 241 + "target",
    }
    short = {
        "semantic_item": "target",
        "surface_item": "target",
        "source_text": "short target",
    }
    frozen = {
        "records": [
            {
                "case_id": "case-1",
                "raw_model_output": {
                    "fact_mentions": [],
                    "clause_atoms": [eligible, divergent, short],
                },
            }
        ]
    }

    treatment, audit = represent_long_self_sufficient_evidence(frozen)

    assert frozen["records"][0]["raw_model_output"]["clause_atoms"] == [
        eligible,
        divergent,
        short,
    ]
    assert treatment["records"][0]["raw_model_output"]["clause_atoms"] == [
        {**eligible, "source_text": "target"},
        divergent,
        short,
    ]
    assert audit == [
        {
            "record_index": 0,
            "case_id": "case-1",
            "changes": [
                {
                    "atom_index": 0,
                    "path": "clause_atoms[0].source_text",
                    "before": eligible["source_text"],
                    "after": "target",
                }
            ],
        }
    ]
