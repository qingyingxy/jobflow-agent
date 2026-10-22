"""Audit positive, negative and unknown candidate outcomes in a completed run.

This is a local, supplementary analysis. It preserves all parse failures and
does not change frozen reference labels or invoke a model.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from scripts.run_product_jd_paired_acceptance import decision_metrics


def apply_reference_review(rows, cases, review):
    """Apply documented source corrections equally to every mode and repeat."""
    rows, cases = copy.deepcopy(rows), copy.deepcopy(cases)
    by_id = {case["id"]: case for case in cases}
    seen = set()
    for correction in review["corrections"]:
        key = correction["case_id"], correction["candidate_id"]
        if key in seen:
            raise ValueError("Duplicate reference correction")
        seen.add(key)
        case = by_id[key[0]]
        if correction["source_text"] not in case["raw_content"]:
            raise ValueError("Reference correction must cite the frozen JD")
        label = next(q for q in case["qualification_labels"] if q["id"] == key[1])
        original = {
            field: label[field]
            for field in ("education", "eligibility")
            if field in label
        }
        updated = correction["corrected_expected"]
        if original != correction["original_expected"] or set(updated) != set(original):
            raise ValueError("Correction must identify exactly the original reference")
        if any(v not in {"pass", "fail", "unknown"} for v in updated.values()):
            raise ValueError("Corrected references must retain three-valued decisions")
        label.update(updated)
        for row in rows:
            if row["case_id"] == key[0]:
                check = next(q for q in row["candidate_checks"] if q["id"] == key[1])
                if check["expected"] != original:
                    raise ValueError("Recorded reference differs from correction")
                check["expected"] = dict(updated)
    return rows, cases


def analyze(rows, cases, repeats):
    modes = ("single_call", "two_stage")
    by_id = {case["id"]: case for case in cases}
    if len(by_id) != len(cases):
        raise ValueError("Unique case identifiers required")
    expected = {
        (case_id, mode, repeat)
        for case_id in by_id
        for mode in modes
        for repeat in range(1, repeats + 1)
    }
    actual = [(row["case_id"], row["mode"], row["repeat"]) for row in rows]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("All frozen case/mode/repeat keys must occur exactly once")

    groups = defaultdict(list)
    mismatches = []
    for row in rows:
        case = by_id[row["case_id"]]
        labels = {label["id"]: label for label in case["qualification_labels"]}
        checks = row["candidate_checks"]
        if (
            len(labels) != len(case["qualification_labels"])
            or len(checks) != len(labels)
            or {check["id"] for check in checks} != set(labels)
        ):
            raise ValueError("Every frozen candidate must be scored exactly once")
        for check in checks:
            label = labels[check["id"]]
            reference = {
                field: label[field]
                for field in ("education", "eligibility")
                if field in label
            }
            if check["expected"] != reference:
                raise ValueError("Recorded expectations differ from frozen labels")
            company = case.get("company_id", "unspecified")
            groups[row["mode"], "all"].append(check)
            groups[row["mode"], company].append(check)
            for field, wanted in reference.items():
                observed = check["actual"][field] if check["actual"] else "unavailable"
                if observed not in {"pass", "fail", "unknown", "unavailable"}:
                    raise ValueError("Unexpected candidate decision")
                if observed != wanted:
                    mismatches.append(
                        {
                            "case_id": row["case_id"],
                            "company_id": company,
                            "mode": row["mode"],
                            "repeat": row["repeat"],
                            "candidate_id": check["id"],
                            "field": field,
                            "expected": wanted,
                            "actual": observed,
                            "failure_code": row["failure_code"],
                        }
                    )

    return {
        "complete_unique_runs": len(rows),
        "unique_cases": len(cases),
        "company_counts": dict(
            Counter(c.get("company_id", "unspecified") for c in cases)
        ),
        "modes": {
            mode: {
                company: {
                    field: decision_metrics(
                        [check for check in checks if field in check["expected"]], field
                    )
                    for field in ("education", "eligibility")
                }
                for (group_mode, company), checks in sorted(groups.items())
                if group_mode == mode
            }
            for mode in modes
        },
        "mismatches": mismatches,
        "limitations": [
            "Supplementary breakdown, not a preregistered new primary metric.",
            "Positive labels cover education/major/status/cohort only, not full job suitability.",
            "Candidates are synthetic and reference labels have not received independent human review.",
            "Two repeated observations of the same JD/candidate are not independent applicants.",
            "False exclusion counts pass-to-fail only; unknown and unavailable are shown separately.",
        ],
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("directory", type=Path)
    cli.add_argument("--reference-review", type=Path)
    args = cli.parse_args()
    root = args.directory
    target = root / (
        "reviewed_candidate_coverage.json"
        if args.reference_review
        else "candidate_coverage.json"
    )
    if target.exists():
        cli.error("Preserve existing analysis")
    manifest_path, report_path = root / "manifest.json", root / "report.json"
    predictions_path = root / "predictions.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not report["complete"] or not report["frozen_files_unchanged"]:
        cli.error("Complete run with unchanged frozen files required")
    labels_paths = [
        p for p in manifest["source_hashes"] if Path(p).name == "labels.json"
    ]
    if len(labels_paths) != 1:
        cli.error("Exactly one frozen labels file required")
    labels_path = root / "sources" / labels_paths[0]
    if (
        hashlib.sha256(labels_path.read_bytes()).hexdigest()
        != manifest["source_hashes"][labels_paths[0]]
    ):
        cli.error("Frozen reference copy changed")
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    rows = json.loads(predictions_path.read_text(encoding="utf-8"))["results"]
    # Verify the primary counts before applying any supplementary correction.
    primary = analyze(rows, labels["cases"], manifest["repeats"])
    for mode, groups in primary["modes"].items():
        if groups["all"] != report["aggregate"][mode]["candidate_decisions"]:
            cli.error("Candidate counts must agree with the original report")
    result = primary
    if args.reference_review:
        review = json.loads(args.reference_review.read_text(encoding="utf-8"))
        if (
            review["original_labels_sha256"]
            != manifest["source_hashes"][labels_paths[0]]
        ):
            cli.error("Reference review must identify the frozen original labels")
        reviewed_rows, reviewed_cases = apply_reference_review(
            rows, labels["cases"], review
        )
        result = analyze(reviewed_rows, reviewed_cases, manifest["repeats"])
        result["reference_review"] = review
        result["limitations"].append(
            "Source corrections made after seeing outputs are post-hoc analysis; the original report and predictions remain unchanged."
        )
    result["source_hashes"] = {
        p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (
            manifest_path,
            report_path,
            predictions_path,
            labels_path,
            Path(__file__),
        )
    }
    if args.reference_review:
        result["source_hashes"][args.reference_review.as_posix()] = hashlib.sha256(
            args.reference_review.read_bytes()
        ).hexdigest()
    target.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
