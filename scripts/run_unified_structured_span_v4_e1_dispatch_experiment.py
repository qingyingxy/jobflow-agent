from __future__ import annotations

import ast
import hashlib
import json
import sys
import types
from collections import Counter
from collections.abc import Callable, Hashable, Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluate_unified_structured_span_v4_corpus_external_holdout import (
    _attachment_edge_keys,
    _attachment_parent_keys,
    _connector_classification,
    _coordination_member_keys,
    _metric,
    _scope_edge_keys,
    _wrapper_keys,
)

PARSER_PATH = PROJECT_ROOT / "src/domain/unified_jd_structured_spans_v4.py"
DATASET_PATH = (
    PROJECT_ROOT
    / "datasets/unified_jd_structured_span_v4_corpus_external_revealed_development_v1_2026-09-04.json"
)
BASELINE_RAW_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-corpus-external-raw-v1-2026-09-04.json"
)
ANALYSIS_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-revealed-error-analysis-v1-2026-09-04.json"
)
RAW_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e1-dispatch-only-raw-v1-2026-09-04.json"
)
REPORT_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e1-dispatch-only-report-v1-2026-09-04.json"
)
FINDINGS_OUTPUT_PATH = (
    PROJECT_ROOT
    / "artifacts/evaluation/unified-jd-structured-span-v4-e1-dispatch-only-findings-v1-2026-09-04.md"
)

EXPECTED_HASHES = {
    PARSER_PATH: "e09e056cab75e651937391ce5410e6df7c94477c85565abb1425bbe85cfcb094",
    DATASET_PATH: "965263881ff85bca636aa6ab87adaca24d74183fa13400709133323a3a6d5b73",
    BASELINE_RAW_PATH: (
        "36b65c1df79d856c7507ae1357ed24c10b7a3e383bad79b9471b124f4999e058"
    ),
    ANALYSIS_PATH: "770d09ca956a55995609ad9f8c8e549a69b26097e6b18216e1b174f1f6c9a4b7",
}

FORCED_FUNCTIONS = {
    "_parse_responsibility_v4",
    "_parse_skill_v4",
    "_parse_experience_v4",
    "_parse_capability_v4",
}

STRUCTURAL_LAYERS = (
    "wrappers",
    "coordination_members",
    "shared_scope_edges",
    "example_attachment_parents",
    "example_attachment_edges",
)
ALL_LAYERS = (*STRUCTURAL_LAYERS, "surface_projection", "example_projection")
MetricKey = Hashable


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


class _RemoveTopLevelReturnNoneGuards(ast.NodeTransformer):
    def __init__(self) -> None:
        self.removed: list[dict[str, Any]] = []

    @staticmethod
    def _is_return_none(statement: ast.stmt) -> bool:
        return (
            isinstance(statement, ast.Return)
            and isinstance(statement.value, ast.Constant)
            and statement.value.value is None
        )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        if node.name not in FORCED_FUNCTIONS:
            return node
        retained: list[ast.stmt] = []
        for statement in node.body:
            is_gate = (
                isinstance(statement, ast.If)
                and not statement.orelse
                and len(statement.body) == 1
                and self._is_return_none(statement.body[0])
            )
            if is_gate:
                self.removed.append(
                    {
                        "function": node.name,
                        "line": statement.lineno,
                        "condition": ast.unparse(statement.test),
                    }
                )
            else:
                retained.append(statement)
        node.body = retained
        return node


def _load_forced_dispatch_module() -> tuple[types.ModuleType, list[dict[str, Any]]]:
    source = PARSER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(PARSER_PATH))
    transformer = _RemoveTopLevelReturnNoneGuards()
    tree = transformer.visit(tree)
    ast.fix_missing_locations(tree)

    removed_functions = {item["function"] for item in transformer.removed}
    if removed_functions != FORCED_FUNCTIONS or len(transformer.removed) != 4:
        raise ValueError(f"unexpected dispatch guards: {transformer.removed}")

    module_name = "src.domain._unified_jd_structured_spans_v4_e1_dispatch"
    module = types.ModuleType(module_name)
    module.__file__ = str(PARSER_PATH)
    module.__package__ = "src.domain"
    sys.modules[module_name] = module
    # The input is the local parser source pinned by EXPECTED_HASHES above.
    exec(compile(tree, str(PARSER_PATH), "exec"), module.__dict__)  # noqa: S102
    return module, sorted(transformer.removed, key=lambda item: item["line"])


def _prediction_record(
    module: types.ModuleType, fixture: dict[str, Any]
) -> dict[str, Any]:
    try:
        extraction = module.extract_surface_items(
            fixture["source_text"], fixture["category"]
        )
        return {
            "id": fixture["id"],
            "job_id": fixture["job_id"],
            "category": fixture["category"],
            "source_text": fixture["source_text"],
            "error": None,
            "items": list(extraction.items),
            "examples": list(extraction.examples),
            "rule_ids": list(extraction.rule_ids),
            "parsed_clause": asdict(extraction.parsed_clause),
        }
    except Exception as error:  # noqa: BLE001 - failures are experiment outcomes
        return {
            "id": fixture["id"],
            "job_id": fixture["job_id"],
            "category": fixture["category"],
            "source_text": fixture["source_text"],
            "error": f"{type(error).__name__}: {error}",
            "items": [],
            "examples": [],
            "rule_ids": [],
            "parsed_clause": None,
        }


def _layer_functions(
    layer: str,
) -> tuple[
    Callable[[dict[str, Any]], Iterable[MetricKey]],
    Callable[[dict[str, Any]], Iterable[MetricKey]],
]:
    structural = {
        "wrappers": (
            lambda item: _wrapper_keys(item, gold=True),
            lambda item: _wrapper_keys(item, gold=False),
        ),
        "coordination_members": (
            lambda item: _coordination_member_keys(item, gold=True),
            lambda item: _coordination_member_keys(item, gold=False),
        ),
        "shared_scope_edges": (
            lambda item: _scope_edge_keys(item, gold=True),
            lambda item: _scope_edge_keys(item, gold=False),
        ),
        "example_attachment_parents": (
            lambda item: _attachment_parent_keys(item, gold=True),
            lambda item: _attachment_parent_keys(item, gold=False),
        ),
        "example_attachment_edges": (
            lambda item: _attachment_edge_keys(item, gold=True),
            lambda item: _attachment_edge_keys(item, gold=False),
        ),
    }
    if layer in structural:
        return structural[layer]
    if layer == "surface_projection":
        return (
            lambda item: item["projection"]["surface_items"],
            lambda item: item["items"],
        )
    if layer == "example_projection":
        return (
            lambda item: item["projection"]["examples"],
            lambda item: item["examples"],
        )
    raise KeyError(layer)


def _difference(
    expected: Iterable[MetricKey], predicted: Iterable[MetricKey]
) -> dict[str, Any]:
    expected_counter = Counter(expected)
    predicted_counter = Counter(predicted)
    return {
        "exact": expected_counter == predicted_counter,
        "missing": list((expected_counter - predicted_counter).elements()),
        "unexpected": list((predicted_counter - expected_counter).elements()),
    }


def _evaluate_fixture(
    gold: dict[str, Any], prediction: dict[str, Any]
) -> dict[str, Any]:
    if prediction["parsed_clause"] is None:
        return {
            "structure_error": prediction["error"],
            "structural_difference_count": None,
        }
    result: dict[str, Any] = {"structure_error": None}
    structural_difference_count = 0
    for layer in ALL_LAYERS:
        gold_values, predicted_values = _layer_functions(layer)
        difference = _difference(gold_values(gold), predicted_values(prediction))
        result[layer] = difference
        if layer in STRUCTURAL_LAYERS:
            structural_difference_count += len(difference["missing"])
            structural_difference_count += len(difference["unexpected"])
    connector = _connector_classification([(gold, prediction)])
    result["connector_classification"] = connector
    structural_difference_count += connector["count"] - connector["correct"]
    result["structural_difference_count"] = structural_difference_count
    return result


def _aggregate(
    fixture_ids: list[str],
    gold_by_id: dict[str, dict[str, Any]],
    predictions_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    pairs = [(gold_by_id[x], predictions_by_id[x]) for x in fixture_ids]
    valid_pairs = [pair for pair in pairs if pair[1]["parsed_clause"] is not None]
    result: dict[str, Any] = {
        "fixture_count": len(pairs),
        "structure_error_count": len(pairs) - len(valid_pairs),
    }
    for layer in ALL_LAYERS:
        gold_values, predicted_values = _layer_functions(layer)
        source_pairs = pairs if layer.endswith("projection") else valid_pairs
        result[layer] = _metric(
            (
                (gold_values(gold), predicted_values(prediction))
                for gold, prediction in source_pairs
            )
        )
    result["connector_classification"] = _connector_classification(valid_pairs)
    return result


def _record_payload(record: dict[str, Any]) -> str:
    payload = {
        key: record[key]
        for key in (
            "error",
            "items",
            "examples",
            "rule_ids",
            "parsed_clause",
        )
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _build_report(
    plan: dict[str, Any],
    dataset: dict[str, Any],
    baseline_raw: dict[str, Any],
    treatment_raw: dict[str, Any],
) -> dict[str, Any]:
    gold_by_id = {item["id"]: item["gold"] for item in dataset["fixtures"]}
    baseline_by_id = {item["id"]: item for item in baseline_raw["records"]}
    treatment_by_id = {item["id"]: item for item in treatment_raw["records"]}
    target_ids = plan["target_fixture_ids"]
    control_ids = plan["control_fixture_ids"]
    selected_ids = [*target_ids, *control_ids]

    records = []
    improved_targets = []
    for fixture_id in selected_ids:
        baseline = _evaluate_fixture(gold_by_id[fixture_id], baseline_by_id[fixture_id])
        treatment = _evaluate_fixture(
            gold_by_id[fixture_id], treatment_by_id[fixture_id]
        )
        baseline_count = baseline["structural_difference_count"]
        treatment_count = treatment["structural_difference_count"]
        improved = (
            fixture_id in target_ids
            and treatment_count is not None
            and baseline_count is not None
            and treatment_count < baseline_count
        )
        if improved:
            improved_targets.append(fixture_id)
        records.append(
            {
                "id": fixture_id,
                "role": "target" if fixture_id in target_ids else "control",
                "source_text": gold_by_id[fixture_id]["source_text"],
                "baseline": baseline,
                "treatment": treatment,
                "structural_difference_delta": (
                    treatment_count - baseline_count
                    if treatment_count is not None and baseline_count is not None
                    else None
                ),
                "improved": improved,
                "baseline_items": baseline_by_id[fixture_id]["items"],
                "treatment_items": treatment_by_id[fixture_id]["items"],
                "baseline_rule_ids": baseline_by_id[fixture_id]["rule_ids"],
                "treatment_rule_ids": treatment_by_id[fixture_id]["rule_ids"],
            }
        )

    control_unchanged = {
        fixture_id: (
            _record_payload(baseline_by_id[fixture_id])
            == _record_payload(treatment_by_id[fixture_id])
        )
        for fixture_id in control_ids
    }
    no_target_structure_errors = all(
        treatment_by_id[fixture_id]["error"] is None for fixture_id in target_ids
    )
    accepted = (
        len(improved_targets) >= 3
        and no_target_structure_errors
        and all(control_unchanged.values())
    )

    return {
        "report_version": (
            "unified-jd-structured-span-v4-e1-dispatch-only-report-v1"
        ),
        "created_at": "2026-09-04",
        "scope": {
            "status": "revealed_development_causal_experiment",
            "experiment_id": plan["id"],
            "generalization_claim": False,
            "threshold_selection_allowed": False,
            "frozen_v4_modified": False,
            "baseline_v4_rerun": False,
            "treatment_execution_count": 1,
            "model_call_count": 0,
            "network_call_count": 0,
        },
        "inputs": {
            "registered_plan": {
                "path": _relative(ANALYSIS_PATH),
                "sha256": EXPECTED_HASHES[ANALYSIS_PATH],
            },
            "revealed_development": {
                "path": _relative(DATASET_PATH),
                "sha256": EXPECTED_HASHES[DATASET_PATH],
            },
            "reused_baseline_raw": {
                "path": _relative(BASELINE_RAW_PATH),
                "sha256": EXPECTED_HASHES[BASELINE_RAW_PATH],
            },
            "frozen_v4_source": {
                "path": _relative(PARSER_PATH),
                "sha256": EXPECTED_HASHES[PARSER_PATH],
            },
            "treatment_raw": {
                "path": _relative(RAW_OUTPUT_PATH),
                "sha256": _sha256(RAW_OUTPUT_PATH),
            },
        },
        "registered_hypothesis": plan["hypothesis"],
        "registered_intervention": plan["intervention"],
        "registered_acceptance": plan["acceptance"],
        "difference_count_definition": (
            "Sum of missing and unexpected wrapper, coordination-member, shared-scope "
            "edge, attachment-parent, and attachment-edge keys, plus misclassified "
            "connector tokens. Projection differences are reported but not counted."
        ),
        "target_fixture_ids": target_ids,
        "control_fixture_ids": control_ids,
        "aggregate": {
            "targets": {
                "baseline": _aggregate(target_ids, gold_by_id, baseline_by_id),
                "treatment": _aggregate(target_ids, gold_by_id, treatment_by_id),
            },
            "controls": {
                "baseline": _aggregate(control_ids, gold_by_id, baseline_by_id),
                "treatment": _aggregate(control_ids, gold_by_id, treatment_by_id),
            },
        },
        "records": records,
        "decision": {
            "accepted": accepted,
            "improved_target_count": len(improved_targets),
            "required_improved_target_count": 3,
            "improved_target_ids": improved_targets,
            "no_target_structure_errors": no_target_structure_errors,
            "control_unchanged": control_unchanged,
            "conclusion": (
                "E1 supports making existing category builders unconditional."
                if accepted
                else "E1 does not support making existing category builders unconditional."
            ),
            "next_action": (
                "Proceed to E2 wrapper-boundary oracle; do not implement unconditional "
                "dispatch in v5."
                if not accepted
                else "Retain dispatch as a candidate mechanism and proceed to E2."
            ),
        },
    }


def _format_metric_change(
    report: dict[str, Any], layer: str, metric: str = "f1"
) -> str:
    baseline = report["aggregate"]["targets"]["baseline"][layer][metric]
    treatment = report["aggregate"]["targets"]["treatment"][layer][metric]
    return f"{baseline:.4f} -> {treatment:.4f}"


def _render_findings(report: dict[str, Any]) -> str:
    decision = report["decision"]
    lines = [
        "# E1 dispatch-only causal experiment",
        "",
        "## Scope",
        "",
        "- Revealed development data only; no holdout or generalization claim.",
        "- The frozen v4 source was not modified.",
        "- The control reuses existing raw predictions and was not rerun.",
        "- The treatment removes exactly four top-level return-None dispatch guards in memory.",
        "- No model or network calls were made.",
        "",
        "## Result",
        "",
        (
            f"Improved targets: {decision['improved_target_count']}/5 "
            f"(required: {decision['required_improved_target_count']}/5)."
        ),
        (
            "Control outputs unchanged: "
            f"{sum(decision['control_unchanged'].values())}/3."
        ),
        (
            "Target structure errors: "
            f"{'none' if decision['no_target_structure_errors'] else 'present'}."
        ),
        f"Decision: **{'accepted' if decision['accepted'] else 'rejected'}**.",
        "",
        "## Target metrics",
        "",
        "| Metric | Baseline -> treatment |",
        "|---|---:|",
        f"| Wrapper F1 | {_format_metric_change(report, 'wrappers')} |",
        (
            "| Coordination-member F1 | "
            f"{_format_metric_change(report, 'coordination_members')} |"
        ),
        (
            "| Shared-scope-edge F1 | "
            f"{_format_metric_change(report, 'shared_scope_edges')} |"
        ),
        (
            "| Surface projection F1 | "
            f"{_format_metric_change(report, 'surface_projection')} |"
        ),
        "",
        "## Per-target structural differences",
        "",
        "| Fixture | Baseline | Treatment | Delta | Improved |",
        "|---|---:|---:|---:|:---:|",
    ]
    for record in report["records"]:
        if record["role"] != "target":
            continue
        lines.append(
            f"| `{record['id']}` | "
            f"{record['baseline']['structural_difference_count']} | "
            f"{record['treatment']['structural_difference_count']} | "
            f"{record['structural_difference_delta']:+d} | "
            f"{'yes' if record['improved'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            decision["conclusion"],
            "",
            decision["next_action"],
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    for path, expected_hash in EXPECTED_HASHES.items():
        actual_hash = _sha256(path)
        if actual_hash != expected_hash:
            raise ValueError(
                f"experiment input changed: {path}: {actual_hash} != {expected_hash}"
            )

    dataset = _load(DATASET_PATH)
    baseline_raw = _load(BASELINE_RAW_PATH)
    analysis = _load(ANALYSIS_PATH)
    plan = next(
        item
        for item in analysis["causal_experiment_plan"]
        if item["id"] == "E1-dispatch-only"
    )
    fixture_by_id = {item["id"]: item["gold"] for item in dataset["fixtures"]}
    selected_ids = [*plan["target_fixture_ids"], *plan["control_fixture_ids"]]

    treatment_module, removed_guards = _load_forced_dispatch_module()
    treatment_records = [
        _prediction_record(treatment_module, fixture_by_id[fixture_id])
        for fixture_id in selected_ids
    ]
    treatment_raw = {
        "raw_version": (
            "unified-jd-structured-span-v4-e1-dispatch-only-raw-v1"
        ),
        "created_at": "2026-09-04",
        "status": "revealed_development_causal_experiment",
        "experiment_id": plan["id"],
        "intervention": {
            "method": "in_memory_ast_top_level_guard_removal",
            "removed_guards": removed_guards,
            "all_other_source_nodes_unchanged": True,
        },
        "frozen_v4_source": {
            "path": _relative(PARSER_PATH),
            "sha256_before": EXPECTED_HASHES[PARSER_PATH],
            "sha256_after": _sha256(PARSER_PATH),
            "modified": False,
        },
        "baseline_reused": True,
        "baseline_v4_rerun": False,
        "treatment_execution_count": 1,
        "fixture_count": len(treatment_records),
        "model_call_count": 0,
        "network_call_count": 0,
        "records": treatment_records,
    }
    if treatment_raw["frozen_v4_source"]["sha256_after"] != EXPECTED_HASHES[
        PARSER_PATH
    ]:
        raise ValueError("frozen v4 changed during the in-memory treatment")

    _write_json(RAW_OUTPUT_PATH, treatment_raw)
    report = _build_report(plan, dataset, baseline_raw, treatment_raw)
    _write_json(REPORT_OUTPUT_PATH, report)
    FINDINGS_OUTPUT_PATH.write_text(_render_findings(report), encoding="utf-8")
    print(
        f"E1 accepted={report['decision']['accepted']} "
        f"improved_targets={report['decision']['improved_target_count']}/5 "
        f"controls_unchanged={sum(report['decision']['control_unchanged'].values())}/3"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
