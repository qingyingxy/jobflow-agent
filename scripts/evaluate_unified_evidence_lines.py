from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.run_unified_causal_probe import DEFAULT_CASE_IDS, DEFAULT_MANIFEST
from src.evaluation.unified_models import UnifiedEvaluationManifest
from src.services.unified_jd_extraction import (
    UNIFIED_EVIDENCE_LINE_EXTRACTOR_VERSION,
    JDEvidenceLine,
    extract_unified_jd_evidence_lines,
)

DEFAULT_BASELINE_REPORT = Path(
    "artifacts/evaluation/"
    "unified-jd-extraction-probe-recompiled-report-v2-2026-09-04.json"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evaluation/unified-jd-evidence-line-report-v1-2026-09-04.json"
)
_SUPPORT_RANK = {"exact": 3, "contains_expected": 2, "overlap_only": 1}


def _source_span(source_content: str, source_text: str) -> tuple[int, int]:
    start = source_content.find(source_text)
    if start < 0:
        raise ValueError(f"expected evidence is not in source: {source_text!r}")
    return start, start + len(source_text)


def _support_type(
    expected_span: tuple[int, int],
    line: JDEvidenceLine,
) -> tuple[str, int] | None:
    expected_start, expected_end = expected_span
    overlap = max(
        0,
        min(expected_end, line.end_char) - max(expected_start, line.start_char),
    )
    if overlap == 0:
        return None
    if line.start_char == expected_start and line.end_char == expected_end:
        return "exact", overlap
    if line.start_char <= expected_start and line.end_char >= expected_end:
        return "contains_expected", overlap
    return "overlap_only", overlap


def _evaluate_case(case: Any) -> dict[str, Any]:
    if case.expected is None:
        raise ValueError(f"case {case.id} has no reviewed expected output")
    lines = [
        line
        for line in extract_unified_jd_evidence_lines(case.raw_content)
        if line.kind in {"responsibilities", "requirements"}
    ]
    expected_support: list[dict[str, Any]] = []
    overlaps_by_line: dict[int, list[int]] = {line.index: [] for line in lines}

    for clause_index, clause in enumerate(case.expected.clauses):
        expected_span = _source_span(case.raw_content, clause.source_text)
        candidates: list[tuple[int, int, JDEvidenceLine, str]] = []
        for line in lines:
            support = _support_type(expected_span, line)
            if support is None:
                continue
            support_type, overlap = support
            overlaps_by_line[line.index].append(clause_index)
            candidates.append(
                (_SUPPORT_RANK[support_type], overlap, line, support_type)
            )
        if candidates:
            _, _, best_line, support_type = max(
                candidates,
                key=lambda item: (item[0], item[1], -item[2].index),
            )
            line_index: int | None = best_line.index
        else:
            support_type = "uncovered"
            line_index = None
        expected_support.append(
            {
                "clause_index": clause_index,
                "category": clause.category,
                "level": clause.level,
                "source_text": clause.source_text,
                "support": support_type,
                "line_index": line_index,
            }
        )

    support_counts = Counter(item["support"] for item in expected_support)
    line_records = [
        {
            "index": line.index,
            "kind": line.kind,
            "level_hint": line.level_hint,
            "start_char": line.start_char,
            "end_char": line.end_char,
            "source_text": line.source_text,
            "overlapping_expected_clause_indices": overlaps_by_line[line.index],
        }
        for line in lines
    ]
    return {
        "case_id": case.id,
        "expected_clause_count": len(case.expected.clauses),
        "semantic_evidence_line_count": len(lines),
        "support_counts": dict(sorted(support_counts.items())),
        "fully_supported_count": (
            support_counts["exact"] + support_counts["contains_expected"]
        ),
        "overlap_supported_count": len(case.expected.clauses)
        - support_counts["uncovered"],
        "fragmented_expected_count": support_counts["overlap_only"],
        "uncovered_expected_count": support_counts["uncovered"],
        "orphan_semantic_line_count": sum(
            not item["overlapping_expected_clause_indices"] for item in line_records
        ),
        "shared_evidence_line_count": sum(
            len(item["overlapping_expected_clause_indices"]) > 1
            for item in line_records
        ),
        "expected_support": expected_support,
        "evidence_lines": line_records,
    }


def _baseline_snapshot(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    repetitions = payload["posthoc_recompilation"][
        "dimensional_evaluation_by_repetition"
    ]
    spans = repetitions[0]["dimensions"]["evidence_spans"]["clause_evidence"]
    return {
        "source": str(path),
        "repetition": repetitions[0]["repetition"],
        "expected_clause_count": spans["expected_count"],
        "predicted_clause_count": spans["predicted_count"],
        "one_to_one_overlap_tp": spans["overlap"]["tp"],
        "one_to_one_overlap_recall": spans["overlap"]["recall"],
    }


def build_report(
    manifest: UnifiedEvaluationManifest,
    case_ids: tuple[str, ...],
    baseline_report: Path,
) -> dict[str, Any]:
    cases_by_id = {case.id: case for case in manifest.cases}
    missing = [case_id for case_id in case_ids if case_id not in cases_by_id]
    if missing:
        raise ValueError(f"unknown case ids: {missing}")
    cases = [_evaluate_case(cases_by_id[case_id]) for case_id in case_ids]
    expected_count = sum(item["expected_clause_count"] for item in cases)
    fully_supported_count = sum(item["fully_supported_count"] for item in cases)
    overlap_supported_count = sum(item["overlap_supported_count"] for item in cases)
    evidence_line_count = sum(item["semantic_evidence_line_count"] for item in cases)
    support_counts: Counter[str] = Counter()
    for case in cases:
        support_counts.update(case["support_counts"])
    return {
        "report_version": "unified-jd-evidence-line-evaluation-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "extractor_version": UNIFIED_EVIDENCE_LINE_EXTRACTOR_VERSION,
        "manifest_version": manifest.manifest_version,
        "dataset_version": manifest.dataset_version,
        "case_ids": list(case_ids),
        "model_call_count": 0,
        "scope_note": (
            "This report measures whether deterministic evidence-line candidates "
            "support reviewed clause spans. It does not measure post-change model recall."
        ),
        "baseline_model_output": _baseline_snapshot(baseline_report),
        "aggregate": {
            "expected_clause_count": expected_count,
            "semantic_evidence_line_count": evidence_line_count,
            "support_counts": dict(sorted(support_counts.items())),
            "fully_supported_count": fully_supported_count,
            "fully_supported_recall": fully_supported_count / expected_count,
            "overlap_supported_count": overlap_supported_count,
            "overlap_supported_recall": overlap_supported_count / expected_count,
            "fragmented_expected_count": sum(
                item["fragmented_expected_count"] for item in cases
            ),
            "uncovered_expected_count": sum(
                item["uncovered_expected_count"] for item in cases
            ),
            "orphan_semantic_line_count": sum(
                item["orphan_semantic_line_count"] for item in cases
            ),
            "shared_evidence_line_count": sum(
                item["shared_evidence_line_count"] for item in cases
            ),
        },
        "cases": cases,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate deterministic evidence-line coverage without model calls"
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--baseline-report",
        type=Path,
        default=DEFAULT_BASELINE_REPORT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--case-ids", nargs="+", default=list(DEFAULT_CASE_IDS))
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    manifest = UnifiedEvaluationManifest.model_validate_json(
        arguments.manifest.read_text(encoding="utf-8")
    )
    report = build_report(
        manifest,
        tuple(arguments.case_ids),
        arguments.baseline_report,
    )
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    aggregate = report["aggregate"]
    print(
        "evidence-line evaluation complete "
        f"supported={aggregate['fully_supported_count']}/"
        f"{aggregate['expected_clause_count']} "
        f"lines={aggregate['semantic_evidence_line_count']} "
        f"output={arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
