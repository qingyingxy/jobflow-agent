from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.evaluate_unified_surface_holdout import (
    build_holdout_report,
    render_findings,
)
from src.domain.unified_jd_surface_items_v2 import (
    SURFACE_ITEM_EXTRACTOR_VERSION,
    extract_surface_items,
)

DEFAULT_FREEZE = Path(
    "datasets/unified_jd_surface_holdout_label_freeze_v2_2026-09-04.json"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evaluation/unified-jd-surface-holdout-v2-2026-09-04.json"
)
DEFAULT_FINDINGS = Path(
    "artifacts/evaluation/unified-jd-surface-holdout-findings-v2-2026-09-04.md"
)


def _generic_failure_analysis(report: dict[str, Any]) -> dict[str, Any]:
    failed_records = [
        record
        for record in report["records"]
        if not record["surface_exact"] or not record["examples_exact"]
    ]
    rule_counts: Counter[str] = Counter(
        rule_id for record in failed_records for rule_id in record["rule_ids"]
    )
    clusters: list[dict[str, Any]] = []

    def add_cluster(
        cause_id: str,
        title: str,
        fixture_ids: list[str],
        evidence: str,
    ) -> None:
        failed_ids = {record["id"] for record in failed_records}
        clusters.append(
            {
                "cause_id": cause_id,
                "title": title,
                "affected_fixture_count": len(fixture_ids),
                "affected_fixture_ids": fixture_ids,
                "evidence": evidence,
                "all_affected_fixtures_failed": all(
                    fixture_id in failed_ids for fixture_id in fixture_ids
                ),
            }
        )

    if failed_records:
        add_cluster(
            "responsibility_composition_gap",
            "Responsibility composition remains under-specified",
            [f"surface-holdout-v2-{index:03d}" for index in range(1, 6)],
            (
                "All five responsibility fixtures failed. The grammar does not model "
                "并 + adverb + action, joint concepts such as RL 与模仿学习的混合范式, "
                "包括/包括但不限于 member scopes, or 保障...在...下 outcomes."
            ),
        )
        add_cluster(
            "bare_conjunction_tokenization",
            "Bare conjunction splitting corrupts lexical words",
            ["surface-holdout-v2-003", "surface-holdout-v2-004"],
            (
                "The character 与 in 参与 was treated as a delimiter, producing the "
                "impossible item 参. Delimiter matching needs token and construction "
                "boundaries rather than raw substring splitting."
            ),
        )
        add_cluster(
            "skill_wrapper_and_shared_scope_gap",
            "Skill parsing still assumes a narrow wrapper vocabulary",
            [f"surface-holdout-v2-{index:03d}" for index in range(6, 11)],
            (
                "All five skill fixtures failed exact matching. 关注并使用, 具备...基础, "
                "深入理解, slash-separated direct items, and shared domain/aspect "
                "scope are not represented compositionally."
            ),
        )
        add_cluster(
            "experience_scope_and_wrapper_gap",
            "Experience heads and alternatives are not parsed generically",
            [
                "surface-holdout-v2-011",
                "surface-holdout-v2-013",
                "surface-holdout-v2-014",
                "surface-holdout-v2-015",
            ],
            (
                "具有/具备 wrappers and CAE分析经验 are outside the suffix grammar. "
                "The preposed-example regex also spans across an earlier project path "
                "into the later 等开源项目 clause, turning non-examples into examples."
            ),
        )
        add_cluster(
            "capability_template_gap",
            "Capability fallback still preserves whole qualification clauses",
            [
                "surface-holdout-v2-018",
                "surface-holdout-v2-019",
                "surface-holdout-v2-020",
            ],
            (
                "工程素养, 对待...有工匠精神, and 能熟练使用...者优先 do not "
                "match the shared-能力 templates. Only the two conventional 能力 "
                "fixtures are exact."
            ),
        )
        add_cluster(
            "example_scope_gap",
            "Example recognition is both incomplete and over-scoped",
            [
                "surface-holdout-v2-002",
                "surface-holdout-v2-007",
                "surface-holdout-v2-015",
            ],
            (
                "Algorithm and AI Coding tool examples were missed, while the "
                "two-path experience clause captured preceding project text as "
                "examples. Example extraction needs clause-local upper-level scope."
            ),
        )

    surface = report["surface_items"]["overall"]
    if report["gate"]["passed"]:
        dominant_signal = (
            "The frozen v2 grammar met every pre-registered surface gate on the new "
            "independent holdout."
        )
        why_canonicalizer_must_wait = (
            "It does not need to wait: the surface contract passed and may now be "
            "treated as the frozen input boundary for canonicalization."
        )
        recommendation = (
            "Keep the v2 surface extractor frozen and implement canonicalization as "
            "a separate downstream component with its own fixtures and metrics."
        )
    else:
        dominant_signal = (
            "The v2 grammar improved development coverage but still misses unseen "
            "surface boundaries or example constructions."
        )
        why_canonicalizer_must_wait = (
            f"The holdout still has {surface['fn']} missing and {surface['fp']} "
            "unexpected surface spans, so canonicalization would confound extraction "
            "and naming errors."
        )
        recommendation = (
            "Stop adding category-specific regex branches. Replace raw substring "
            "splitting with a clause-local span parser that represents wrappers, "
            "coordination, shared scope, and example attachment explicitly. Validate "
            "the next version on a genuinely unseen external holdout because dev-50 "
            "no longer has enough untouched cases for another 20-case internal test."
        )

    return {
        "analysis_type": "post_gate_offline_error_attribution",
        "rules_changed": False,
        "labels_changed": False,
        "dominant_signal": dominant_signal,
        "root_cause_clusters": clusters,
        "failed_rule_counts": dict(sorted(rule_counts.items())),
        "why_canonicalizer_must_wait": why_canonicalizer_must_wait,
        "recommended_next_experiment": recommendation,
    }


def build_v2_holdout_report(freeze_path: Path) -> dict[str, Any]:
    return build_holdout_report(
        freeze_path,
        extractor=extract_surface_items,
        extractor_version=SURFACE_ITEM_EXTRACTOR_VERSION,
        report_version="unified-jd-surface-holdout-evaluation-v2",
        failure_analyzer=_generic_failure_analysis,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the frozen v2 Unified JD surface holdout offline"
    )
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--findings", type=Path, default=DEFAULT_FINDINGS)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    report = build_v2_holdout_report(arguments.freeze)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    arguments.findings.parent.mkdir(parents=True, exist_ok=True)
    arguments.findings.write_text(render_findings(report), encoding="utf-8")
    surface = report["surface_items"]["overall"]
    print(
        "offline v2 surface holdout evaluation complete "
        f"surface_f1={surface['f1']:.4f} "
        f"surface_exact={surface['exact_set_count']}/"
        f"{surface['comparison_count']} "
        f"gate_passed={report['gate']['passed']} "
        f"output={arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
