"""Analyze a completed paired acceptance report without additional model calls."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import median

from scripts.run_product_jd_execution_evaluation import file_hash, write_json
from scripts.run_product_jd_paired_acceptance import MODES, pair_integrity


def paired_outcomes(pairs, predicate):
    counts = Counter()
    for pair in pairs:
        single, two = (predicate(pair[mode]) for mode in MODES)
        key = (
            "both_correct"
            if single and two
            else "single_only"
            if single
            else "two_only"
            if two
            else "both_incorrect"
        )
        counts[key] += 1
    return {
        k: counts[k]
        for k in ("both_correct", "single_only", "two_only", "both_incorrect")
    }


def paired_latency(pairs):
    if not pairs:
        return None
    ratios = [
        p["single_call"]["duration_ms"] / p["two_stage"]["duration_ms"] for p in pairs
    ]
    differences = [
        (p["single_call"]["duration_ms"] - p["two_stage"]["duration_ms"]) / 1000
        for p in pairs
    ]
    return {
        "pairs": len(pairs),
        "single_faster_count": sum(d < 0 for d in differences),
        "median_single_minus_two_seconds": median(differences),
        "median_single_over_two_ratio": median(ratios),
        "duration_sum_single_over_two_ratio": sum(
            p["single_call"]["duration_ms"] for p in pairs
        )
        / sum(p["two_stage"]["duration_ms"] for p in pairs),
    }


def token_details(rows):
    calls = [c for row in rows for c in row["calls"]]
    usage = [c.get("usage") for c in calls if isinstance(c.get("usage"), dict)]
    return {
        "attempted_calls": len(calls),
        "calls_with_usage": len(usage),
        "reported_cached_input_tokens": sum(
            (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
            for u in usage
        ),
        "reported_reasoning_tokens": sum(
            (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
            for u in usage
        ),
        "cost_scored": False,
    }


def analyze(rows, cases):
    integrity = pair_integrity(rows, cases)
    if not integrity["complete"]:
        raise ValueError(
            "Only a complete, unique set of paired outcomes may be analyzed as final"
        )
    by_id = {}
    for row in rows:
        by_id.setdefault(row["case_id"], {})[row["mode"]] = row
    output = {
        "pairs": integrity,
        "model_call_count": 0,
        "groups": {},
        "failure_catalog": [],
        "decision_mismatches": [],
        "validation_messages": [],
    }
    validation = Counter()
    for row in rows:
        diagnostics = row.get("diagnostics", {})
        messages = [
            e.get("message", "")
            for stage in diagnostics.get("stages", diagnostics.get("attempts", []))
            for e in stage.get("errors", [])
        ]
        validation.update((row["mode"], message) for message in messages)
        if row["failure_code"]:
            output["failure_catalog"].append(
                {
                    "case_id": row["case_id"],
                    "mode": row["mode"],
                    "failure_code": row["failure_code"],
                    "diagnostics": row.get("diagnostics", {}),
                }
            )
        for decision in row["qualifications"]:
            for field, expected in decision["expected"].items():
                actual = (
                    decision["actual"][field] if decision["actual"] else "unavailable"
                )
                if actual != expected:
                    output["decision_mismatches"].append(
                        {
                            "case_id": row["case_id"],
                            "mode": row["mode"],
                            "candidate_id": decision["id"],
                            "field": field,
                            "expected": expected,
                            "actual": actual,
                            "checks": decision["actual"]["checks"]
                            if decision["actual"]
                            else [],
                        }
                    )
    output["validation_messages"] = [
        {"mode": mode, "message": message, "count": count}
        for (mode, message), count in validation.most_common()
    ]
    for kind in ("real_regression", "synthetic_development"):
        pairs = [by_id[c["id"]] for c in cases if c["case_kind"] == kind]
        candidate_pairs = []
        for pair in pairs:
            candidates = {
                mode: {d["id"]: d for d in pair[mode]["qualifications"]}
                for mode in MODES
            }
            if set(candidates["single_call"]) != set(candidates["two_stage"]):
                raise ValueError("Candidate pairing is incomplete")
            for key in candidates["single_call"]:
                candidate_pair = {mode: candidates[mode][key] for mode in MODES}
                if (
                    candidate_pair["single_call"]["expected"]
                    != candidate_pair["two_stage"]["expected"]
                ):
                    raise ValueError("Modes must use identical candidate gold")
                candidate_pairs.append(candidate_pair)
        successful = [
            p for p in pairs if all(p[m]["output"] is not None for m in MODES)
        ]
        output["groups"][kind] = {
            "parse_success": paired_outcomes(pairs, lambda r: r["output"] is not None),
            "latency_including_failures": paired_latency(pairs),
            "latency_both_parsed": paired_latency(successful),
            "candidate_decisions": {
                field: paired_outcomes(
                    candidate_pairs,
                    lambda d, field=field: (
                        d["actual"] is not None
                        and d["actual"][field] == d["expected"][field]
                    ),
                )
                for field in ("education", "eligibility")
            },
            "tokens": {mode: token_details([p[mode] for p in pairs]) for mode in MODES},
        }
    return output


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("run_dir", type=Path)
    args = cli.parse_args()
    target = args.run_dir / "analysis.json"
    if target.exists():
        cli.error("Preserve existing analysis; choose a different run directory")
    rows = json.loads((args.run_dir / "predictions.json").read_text(encoding="utf-8"))[
        "results"
    ]
    cases = json.loads((args.run_dir / "cases.json").read_text(encoding="utf-8"))[
        "cases"
    ]
    result = analyze(rows, cases)
    result["analysis_provenance"] = {
        "analysis_script_sha256": file_hash(Path(__file__)),
        "predictions_sha256": file_hash(args.run_dir / "predictions.json"),
        "cases_sha256": file_hash(args.run_dir / "cases.json"),
        "execution_manifest_sha256": file_hash(args.run_dir / "manifest.json"),
        "model_call_count": 0,
    }
    write_json(target, result)
    print(
        json.dumps(
            {
                "groups": result["groups"],
                "parse_failures": len(result["failure_catalog"]),
                "candidate_field_mismatches": len(result["decision_mismatches"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
