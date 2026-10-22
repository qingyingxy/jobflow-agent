from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scripts.evaluate_unified_surface_items import build_report
from scripts.freeze_unified_surface_holdout_labels import sha256, validate_labels
from src.domain.unified_jd_surface_items import (
    SURFACE_ITEM_EXTRACTOR_VERSION,
    SurfaceCategory,
    extract_surface_items,
)
from src.evaluation.unified_models import UnifiedEvaluationManifest

DEFAULT_FREEZE = Path(
    "datasets/unified_jd_surface_holdout_label_freeze_v1_2026-09-04.json"
)
DEFAULT_OUTPUT = Path(
    "artifacts/evaluation/unified-jd-surface-holdout-v1-2026-09-04.json"
)
DEFAULT_FINDINGS = Path(
    "artifacts/evaluation/unified-jd-surface-holdout-findings-v1-2026-09-04.md"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_frozen_inputs(
    freeze_path: Path,
    *,
    extractor_version: str = SURFACE_ITEM_EXTRACTOR_VERSION,
) -> dict[str, Any]:
    freeze = _load(freeze_path)
    if freeze["status"] != "frozen":
        raise ValueError("holdout labels are not frozen")
    if freeze["prediction_status"] != "not_generated_or_viewed":
        raise ValueError("holdout label freeze was created after prediction")
    if freeze["model_call_count"] != 0:
        raise ValueError("holdout label freeze must be offline")

    for name, frozen_file in freeze["files"].items():
        path = Path(frozen_file["path"])
        actual_hash = sha256(path)
        if actual_hash != frozen_file["sha256"]:
            raise ValueError(
                f"frozen {name} changed: expected {frozen_file['sha256']}, "
                f"got {actual_hash}"
            )

    files = freeze["files"]
    rules_freeze = _load(Path(files["rules_freeze"]["path"]))
    rules_path = Path(rules_freeze["frozen_rules"]["path"])
    if sha256(rules_path) != files["rules_freeze"]["rules_sha256"]:
        raise ValueError("surface rules changed after the label freeze")
    if extractor_version != files["rules_freeze"]["extractor_version"]:
        raise ValueError("loaded extractor version differs from the frozen version")

    labels = _load(Path(files["labels"]["path"]))
    selection = _load(Path(files["selection"]["path"]))
    manifest = UnifiedEvaluationManifest.model_validate_json(
        Path(files["source_manifest"]["path"]).read_text(encoding="utf-8")
    )
    validate_labels(
        labels,
        selection,
        manifest,
        expected_labels_version=files["labels"]["version"],
    )
    return {
        "freeze": freeze,
        "labels": labels,
        "selection": selection,
    }


def _gate_result(
    report: dict[str, Any], gates: dict[str, float | int]
) -> dict[str, Any]:
    surface = report["surface_items"]["overall"]
    examples = report["examples"]["overall"]
    unanchored_count = report["unanchored_outputs"]["count"]
    checks = {
        "surface_items_f1": {
            "actual": surface["f1"],
            "operator": ">=",
            "threshold": gates["surface_items_f1_min"],
            "passed": surface["f1"] >= gates["surface_items_f1_min"],
        },
        "surface_exact_set_rate": {
            "actual": surface["exact_set_rate"],
            "operator": ">=",
            "threshold": gates["surface_exact_set_rate_min"],
            "passed": surface["exact_set_rate"] >= gates["surface_exact_set_rate_min"],
        },
        "examples_f1": {
            "actual": examples["f1"],
            "operator": ">=",
            "threshold": gates["examples_f1_min"],
            "passed": examples["f1"] >= gates["examples_f1_min"],
        },
        "unanchored_output_count": {
            "actual": unanchored_count,
            "operator": "<=",
            "threshold": gates["unanchored_output_count_max"],
            "passed": unanchored_count <= gates["unanchored_output_count_max"],
        },
    }
    failure_reasons = [
        f"{name}={check['actual']} 未满足 {check['operator']} {check['threshold']}"
        for name, check in checks.items()
        if not check["passed"]
    ]
    return {
        "passed": not failure_reasons,
        "checks": checks,
        "failure_reasons": failure_reasons,
    }


def _failure_analysis(report: dict[str, Any]) -> dict[str, Any]:
    records_by_id = {record["id"]: record for record in report["records"]}

    def cluster(
        cause_id: str,
        title: str,
        fixture_ids: list[str],
        evidence: str,
    ) -> dict[str, Any]:
        return {
            "cause_id": cause_id,
            "title": title,
            "affected_fixture_count": len(fixture_ids),
            "affected_fixture_ids": fixture_ids,
            "evidence": evidence,
            "all_affected_fixtures_failed": all(
                not records_by_id[fixture_id]["surface_exact"]
                or not records_by_id[fixture_id]["examples_exact"]
                for fixture_id in fixture_ids
            ),
        }

    return {
        "analysis_type": "post_gate_offline_error_attribution",
        "rules_changed": False,
        "labels_changed": False,
        "dominant_signal": (
            "The extractor remains source-anchored but does not generalize item "
            "boundaries or example syntax beyond its development patterns."
        ),
        "root_cause_clusters": [
            cluster(
                "responsibility_scope_and_enumeration_underfit",
                "Responsibility action and enumeration grammar is too narrow",
                [
                    "surface-holdout-v1-001",
                    "surface-holdout-v1-002",
                    "surface-holdout-v1-003",
                    "surface-holdout-v1-004",
                    "surface-holdout-v1-005",
                ],
                (
                    "All five responsibility fixtures failed. Unseen verbs and "
                    "constructions such as 跟踪/推动/突破, 通过/进行, 参与, "
                    "设计并优化, and nested 包括 remained as whole spans instead "
                    "of exposing their coordinated work objects."
                ),
            ),
            cluster(
                "experience_atomic_fallback_overuse",
                "Experience parsing falls back to the whole clause",
                [
                    "surface-holdout-v1-011",
                    "surface-holdout-v1-012",
                    "surface-holdout-v1-013",
                    "surface-holdout-v1-014",
                    "surface-holdout-v1-015",
                ],
                (
                    "All five experience fixtures used experience.atomic_fallback, "
                    "yielding zero true-positive surface items. The current patterns "
                    "do not cover punctuation around 或, 对...有实践经验, spaced "
                    "alternatives, 的优先, or ASCII example parentheses."
                ),
            ),
            cluster(
                "skill_wrapper_and_suffix_leakage",
                "Skill wrappers and shared suffixes leak into item spans",
                [
                    "surface-holdout-v1-006",
                    "surface-holdout-v1-007",
                    "surface-holdout-v1-008",
                    "surface-holdout-v1-009",
                    "surface-holdout-v1-010",
                ],
                (
                    "All five skill fixtures failed exact matching. Prefixes such as "
                    "对...有深入理解 and upper-level introductions before a colon, "
                    "plus suffixes such as 等技术流程, 有兴趣, 者优先, and 等方法, "
                    "are outside the frozen cleanup grammar."
                ),
            ),
            cluster(
                "example_syntax_coverage_gap",
                "Example and alias recognition has zero recall",
                [
                    "surface-holdout-v1-003",
                    "surface-holdout-v1-008",
                    "surface-holdout-v1-009",
                    "surface-holdout-v1-015",
                ],
                (
                    "The extractor recovered 0 of 10 expected examples. It misses "
                    "examples before 等 + upper concept, expanded aliases without 如, "
                    "and 如-lists inside ASCII parentheses."
                ),
            ),
            cluster(
                "capability_wrapper_variant_gap",
                "Capability grammar covers only a small wrapper vocabulary",
                [
                    "surface-holdout-v1-016",
                    "surface-holdout-v1-017",
                    "surface-holdout-v1-018",
                ],
                (
                    "Modifiers such as 较强的, the 对...有兴趣和了解 construction, "
                    "and particles such as 在...下/进行 remain attached or force an "
                    "atomic fallback. Only two of five capability fixtures are exact."
                ),
            ),
        ],
        "why_canonicalizer_must_wait": (
            "Canonicalization assumes correctly delimited surface units. With 49 "
            "missing and 28 unexpected surface spans, a canonicalizer would have to "
            "silently redo extraction and would make the two stages impossible to "
            "evaluate independently."
        ),
        "recommended_next_experiment": (
            "Design a v2 category grammar around wrapper stripping, delimiter-aware "
            "enumeration, shared-scope attachment, and explicit example introducers; "
            "promote this revealed v1 holdout to v2 development data, then freeze v2 "
            "and evaluate it on a newly selected holdout from the still-unseen dev-50 "
            "cases. Never reuse this revealed set as the v2 generalization test."
        ),
    }


def build_holdout_report(
    freeze_path: Path,
    *,
    extractor: Callable[[str, SurfaceCategory], Any] = extract_surface_items,
    extractor_version: str = SURFACE_ITEM_EXTRACTOR_VERSION,
    report_version: str = "unified-jd-surface-holdout-evaluation-v1",
    failure_analyzer: Callable[[dict[str, Any]], dict[str, Any]] = _failure_analysis,
) -> dict[str, Any]:
    inputs = validate_frozen_inputs(
        freeze_path,
        extractor_version=extractor_version,
    )
    freeze = inputs["freeze"]
    labels = inputs["labels"]
    labels_path = Path(freeze["files"]["labels"]["path"])
    base = build_report(
        labels,
        labels_path,
        extractor=extractor,
        extractor_version=extractor_version,
    )

    unanchored_records: list[dict[str, str]] = []
    for record in base["records"]:
        for output_type, values in (
            ("surface_item", record["predicted_surface_items"]),
            ("example", record["predicted_examples"]),
        ):
            for value in values:
                if value not in record["source_text"]:
                    unanchored_records.append(
                        {
                            "id": record["id"],
                            "output_type": output_type,
                            "value": value,
                        }
                    )

    report = {
        **base,
        "report_version": report_version,
        "evaluation_scope": {
            "type": "frozen_independent_surface_holdout",
            "generalization_claim": True,
            "production_wiring": False,
            "selection_fixture_count": len(inputs["selection"]["fixtures"]),
            "development_case_ids_excluded": inputs["selection"][
                "excluded_development_case_ids"
            ],
            "note": (
                "Rules, selection, and reviewed labels were hash-frozen before this "
                "offline replay. No model API was called."
            ),
        },
        "provenance": {
            "label_freeze": {
                "path": freeze_path.as_posix(),
                "sha256": sha256(freeze_path),
                "version": freeze["freeze_version"],
            },
            "frozen_files": freeze["files"],
        },
        "unanchored_outputs": {
            "count": len(unanchored_records),
            "records": unanchored_records,
        },
    }
    report["gate"] = _gate_result(report, freeze["gates"])
    report["failure_analysis"] = failure_analyzer(report)
    report["decision"] = (
        "surface_gate_passed_canonicalizer_may_start"
        if report["gate"]["passed"]
        else "surface_gate_failed_stop_before_canonicalizer"
    )
    return report


def _format_values(values: list[str]) -> str:
    return "<br>".join(values) if values else "-"


def render_findings(report: dict[str, Any]) -> str:
    surface = report["surface_items"]["overall"]
    examples = report["examples"]["overall"]
    gate = report["gate"]
    version = "v2" if report["report_version"].endswith("v2") else "v1"
    decision = (
        "通过：可以开始 canonicalizer。"
        if gate["passed"]
        else (
            "未通过：停止在 surface 阶段，不实现 canonicalizer，也不修改 "
            f"{version} 规则。"
        )
    )
    lines = [
        f"# Unified JD Surface Holdout {version} Findings",
        "",
        "## Conclusion",
        "",
        decision,
        "",
        (
            "本次为冻结后的纯离线回放，模型调用数为 0。规则、选择、标签、"
            "contract 与源 manifest 均通过 SHA-256 校验。"
        ),
        "",
        "## Gate",
        "",
        "| Metric | Actual | Threshold | Passed |",
        "|---|---:|---:|:---:|",
    ]
    for name, check in gate["checks"].items():
        lines.append(
            f"| `{name}` | {check['actual']:.4f} | "
            f"{check['operator']} {check['threshold']:.4f} | "
            f"{'yes' if check['passed'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Aggregate",
            "",
            (
                f"- Surface items: precision {surface['precision']:.4f}, recall "
                f"{surface['recall']:.4f}, F1 {surface['f1']:.4f}, exact "
                f"{surface['exact_set_count']}/{surface['comparison_count']}."
            ),
            (
                f"- Examples: precision {examples['precision']:.4f}, recall "
                f"{examples['recall']:.4f}, F1 {examples['f1']:.4f}, exact "
                f"{examples['exact_set_count']}/{examples['comparison_count']}."
            ),
            f"- Unanchored outputs: {report['unanchored_outputs']['count']}.",
            "",
            "## Why It Failed" if not gate["passed"] else "## Holdout Analysis",
            "",
            report["failure_analysis"]["dominant_signal"],
            "",
        ]
    )
    for cluster in report["failure_analysis"]["root_cause_clusters"]:
        fixture_ids = ", ".join(
            f"`{fixture_id}`" for fixture_id in cluster["affected_fixture_ids"]
        )
        lines.extend(
            [
                f"### {cluster['title']}",
                "",
                f"Affected: {fixture_ids}.",
                "",
                cluster["evidence"],
                "",
            ]
        )
    lines.extend(
        [
            "### Why canonicalizer must wait",
            "",
            report["failure_analysis"]["why_canonicalizer_must_wait"],
            "",
            "### Next experiment",
            "",
            report["failure_analysis"]["recommended_next_experiment"],
            "",
            "## By Category",
            "",
            "| Category | Surface F1 | Surface exact | Examples F1 |",
            "|---|---:|---:|---:|",
        ]
    )
    for category, category_surface in report["surface_items"]["by_category"].items():
        category_examples = report["examples"]["by_category"][category]
        lines.append(
            f"| `{category}` | {category_surface['f1']:.4f} | "
            f"{category_surface['exact_set_count']}/"
            f"{category_surface['comparison_count']} | "
            f"{category_examples['f1']:.4f} |"
        )

    failures = [
        record
        for record in report["records"]
        if not record["surface_exact"] or not record["examples_exact"]
    ]
    lines.extend(
        [
            "",
            "## Failed Fixtures",
            "",
            "| ID | Category | Missing surface | Unexpected surface | Missing examples | Unexpected examples |",
            "|---|---|---|---|---|---|",
        ]
    )
    for record in failures:
        lines.append(
            f"| `{record['id']}` | `{record['category']}` | "
            f"{_format_values(record['missing_surface_items'])} | "
            f"{_format_values(record['unexpected_surface_items'])} | "
            f"{_format_values(record['missing_examples'])} | "
            f"{_format_values(record['unexpected_examples'])} |"
        )
    if not failures:
        lines.append("| - | - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## Decision Rule",
            "",
            (
                f"{version} 结果只用于决定是否进入 canonicalizer；失败结果不能"
                f"用于修改已冻结的 {version} surface rules。任何规则改进都必须"
                "建立新的规则版本和新的独立 holdout。"
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the frozen Unified JD surface holdout offline"
    )
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--findings", type=Path, default=DEFAULT_FINDINGS)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    report = build_holdout_report(arguments.freeze)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    arguments.findings.parent.mkdir(parents=True, exist_ok=True)
    arguments.findings.write_text(render_findings(report), encoding="utf-8")
    surface = report["surface_items"]["overall"]
    print(
        "offline surface holdout evaluation complete "
        f"surface_f1={surface['f1']:.4f} "
        f"surface_exact={surface['exact_set_count']}/"
        f"{surface['comparison_count']} "
        f"gate_passed={report['gate']['passed']} "
        f"output={arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
