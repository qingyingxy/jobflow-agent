"""Summarize completed repeats, separating explicit alternatives from examples."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path


def probe_kind(probe):
    if probe["relation"] == "any_of" and re.search(
        r"such\s+as|e\.g\.|etc\b|including", probe["source_text"], re.IGNORECASE
    ):
        return "example_or_open_range"
    return "explicit_or_shared_requirement"


def transport_recovery(row):
    attempts = row["diagnostics"].get("attempts", [])
    scheduled = sum(a.get("retry_scheduled", False) for a in attempts)
    returned = sum(
        a.get("transport_attempt", 1) > 1
        and a["status"] in {"passed", "validation_failed"}
        for a in attempts
    )
    return {
        "scheduled_retries": scheduled,
        "requests_recovered": returned,
        "parse_succeeded_after_retry": bool(scheduled and row["output"] is not None),
    }


def analyze(rows, expected_runs):
    keys = [(r["case_id"], r["mode"], r["repeat"]) for r in rows]
    if len(rows) != expected_runs or len(set(keys)) != expected_runs:
        raise ValueError("Completed, unique repeated runs required")
    modes, pairs = {}, defaultdict(dict)
    for row in rows:
        pairs[(row["case_id"], row["repeat"])][row["mode"]] = row
    if any(set(pair) != {"single_call", "two_stage"} for pair in pairs.values()):
        raise ValueError("Every case/repeat must have both modes")
    for mode in ("single_call", "two_stage"):
        selected = [r for r in rows if r["mode"] == mode]
        probes = defaultdict(list)
        for row in selected:
            for probe in row["relation_checks"]:
                probes[probe_kind(probe["expected"])].append(probe)
        recovery = [transport_recovery(r) for r in selected]
        by_case = defaultdict(list)
        for row in selected:
            by_case[row["case_id"]].append(row)
        varying = []
        for case_id, repeats in by_case.items():
            signatures = {
                json.dumps(
                    {
                        "parsed": r["output"] is not None,
                        "probes": [p["passed"] for p in r["relation_checks"]],
                        "candidates": [q["actual"] for q in r["candidate_checks"]],
                    },
                    sort_keys=True,
                )
                for r in repeats
            }
            if len(signatures) > 1:
                varying.append(case_id)
        modes[mode] = {
            "transport_recovery": {
                k: sum(r[k] for r in recovery)
                for k in (
                    "scheduled_retries",
                    "requests_recovered",
                    "parse_succeeded_after_retry",
                )
            },
            "probe_groups": {
                k: {"total": len(v), "correct": sum(p["passed"] for p in v)}
                for k, v in probes.items()
            },
            "cases_with_changed_checks_across_repeats": varying,
        }
    ratios = [
        p["single_call"]["duration_ms"] / p["two_stage"]["duration_ms"]
        for p in pairs.values()
    ]
    return {
        "pairs": len(pairs),
        "single_faster_count": sum(
            p["single_call"]["duration_ms"] < p["two_stage"]["duration_ms"]
            for p in pairs.values()
        ),
        "median_single_over_two_duration_ratio": statistics.median(ratios),
        "modes": modes,
        "limitations": [
            "The source-based example/open-range classification is supplementary analysis, not a preregistered primary metric.",
            "Language examples do not prove a closed alternative list; raw probe disagreements are not automatically semantic errors.",
            "Changed checks include unavailable runs and provider failures; this is not pure model semantic instability.",
            "Transport return recovery can succeed even if later output validation fails.",
        ],
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("directory", type=Path)
    args = cli.parse_args()
    root = args.directory
    output = root / "analysis.json"
    if output.exists():
        cli.error("Preserve existing analysis")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    if not report["complete"]:
        cli.error("Incomplete run")
    rows = json.loads((root / "predictions.json").read_text(encoding="utf-8"))[
        "results"
    ]
    result = analyze(rows, len(rows))
    result["source_hashes"] = {
        p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (
            root / "manifest.json",
            root / "predictions.json",
            root / "report.json",
            Path(__file__),
        )
    }
    result["repeats"] = manifest["repeats"]
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
