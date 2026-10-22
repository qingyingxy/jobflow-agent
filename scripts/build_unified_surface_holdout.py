from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.evaluation.unified_models import UnifiedEvaluationManifest

DEFAULT_MANIFEST = Path(
    "artifacts/evaluation/unified-jd-dev50-frozen-v2-2026-09-04.json"
)
DEFAULT_RULES = Path("src/domain/unified_jd_surface_items.py")
DEFAULT_FREEZE_RECEIPT = Path(
    "datasets/unified_jd_surface_rules_freeze_v1_2026-09-04.json"
)
DEFAULT_OUTPUT = Path(
    "datasets/unified_jd_surface_holdout_selection_v1_2026-09-04.json"
)
SELECTION_VERSION = "unified-jd-surface-holdout-selection-v1"
CATEGORIES = ("responsibility", "skill", "experience", "capability")


@dataclass(frozen=True)
class _Candidate:
    rank_key: str
    case_id: str
    clause_index: int
    category: str
    level: str
    source_text: str
    source_content_sha256: str


def _globally_assign_unique_cases(
    ranked_by_category: dict[str, list[_Candidate]],
    target_per_category: int,
) -> list[_Candidate]:
    best_by_category_and_case: dict[str, dict[str, _Candidate]] = {}
    for category, candidates in ranked_by_category.items():
        best_by_case: dict[str, _Candidate] = {}
        for candidate in candidates:
            best_by_case.setdefault(candidate.case_id, candidate)
        best_by_category_and_case[category] = best_by_case

    slot_categories = sorted(
        [category for category in CATEGORIES for _ in range(target_per_category)],
        key=lambda category: (
            len(best_by_category_and_case[category]),
            category,
        ),
    )
    candidates_by_slot = {
        slot: [
            candidate
            for candidate in ranked_by_category[category]
            if best_by_category_and_case[category].get(candidate.case_id) == candidate
        ]
        for slot, category in enumerate(slot_categories)
    }
    case_to_slot: dict[str, int] = {}
    slot_to_candidate: dict[int, _Candidate] = {}

    def assign(slot: int, seen_cases: set[str]) -> bool:
        for candidate in candidates_by_slot[slot]:
            if candidate.case_id in seen_cases:
                continue
            seen_cases.add(candidate.case_id)
            previous_slot = case_to_slot.get(candidate.case_id)
            if previous_slot is None or assign(previous_slot, seen_cases):
                case_to_slot[candidate.case_id] = slot
                slot_to_candidate[slot] = candidate
                return True
        return False

    for slot in range(len(slot_categories)):
        if not assign(slot, set()):
            raise ValueError(
                "not enough globally assignable unique cases for balanced holdout"
            )

    return sorted(
        slot_to_candidate.values(),
        key=lambda candidate: (
            CATEGORIES.index(candidate.category),
            candidate.rank_key,
            candidate.case_id,
            candidate.clause_index,
        ),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_immutable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise FileExistsError(
            f"refusing to overwrite changed holdout selection: {path}"
        )
    path.write_text(content, encoding="utf-8")


def _verify_frozen_rules(
    receipt: dict[str, Any], rules_path: Path, selection_version: str
) -> None:
    if receipt["status"] != "frozen":
        raise ValueError("surface rules must be frozen before holdout selection")
    if receipt["holdout_protocol"]["selection_version"] != selection_version:
        raise ValueError("holdout selection version differs from the frozen protocol")
    actual_rules_hash = _sha256(rules_path)
    if actual_rules_hash != receipt["frozen_rules"]["sha256"]:
        raise ValueError(
            "surface rules changed after freeze: "
            f"expected {receipt['frozen_rules']['sha256']}, got {actual_rules_hash}"
        )


def build_selection(
    *,
    manifest_path: Path,
    rules_path: Path,
    freeze_receipt_path: Path,
    selection_version: str = SELECTION_VERSION,
    fixture_id_prefix: str = "surface-holdout-v1",
    global_unique_assignment: bool = False,
) -> dict[str, Any]:
    receipt: dict[str, Any] = json.loads(
        freeze_receipt_path.read_text(encoding="utf-8")
    )
    _verify_frozen_rules(receipt, rules_path, selection_version)
    manifest = UnifiedEvaluationManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    excluded_case_ids = set(receipt["development_fixture"]["case_ids"])
    candidates_by_category: dict[str, list[_Candidate]] = {
        category: [] for category in CATEGORIES
    }

    for case in manifest.cases:
        if case.id in excluded_case_ids or case.expected is None:
            continue
        for clause_index, clause in enumerate(case.expected.clauses):
            if clause.category not in candidates_by_category:
                continue
            rank_input = "\0".join(
                (
                    selection_version,
                    case.id,
                    str(clause_index),
                    case.source_content_sha256,
                )
            )
            candidates_by_category[clause.category].append(
                _Candidate(
                    rank_key=_sha256_text(rank_input),
                    case_id=case.id,
                    clause_index=clause_index,
                    category=clause.category,
                    level=clause.level,
                    source_text=clause.source_text,
                    source_content_sha256=case.source_content_sha256,
                )
            )

    target_per_category = receipt["holdout_protocol"]["fixtures_per_category"]
    ranked_by_category = {
        category: sorted(
            candidates,
            key=lambda candidate: (
                candidate.rank_key,
                candidate.case_id,
                candidate.clause_index,
            ),
        )
        for category, candidates in candidates_by_category.items()
    }
    if global_unique_assignment:
        selected = _globally_assign_unique_cases(
            ranked_by_category, target_per_category
        )
    else:
        selected_case_ids: set[str] = set()
        selected = []
        for category in CATEGORIES:
            category_selection: list[_Candidate] = []
            for candidate in ranked_by_category[category]:
                if candidate.case_id in selected_case_ids:
                    continue
                category_selection.append(candidate)
                selected_case_ids.add(candidate.case_id)
                if len(category_selection) == target_per_category:
                    break
            if len(category_selection) != target_per_category:
                raise ValueError(f"not enough unique cases for category {category}")
            selected.extend(category_selection)

    selected_case_ids = {candidate.case_id for candidate in selected}

    expected_count = receipt["holdout_protocol"]["fixture_count"]
    if len(selected) != expected_count:
        raise ValueError(
            f"expected {expected_count} holdout fixtures, got {len(selected)}"
        )

    return {
        "selection_version": selection_version,
        "status": "frozen_selection",
        "selected_at": "2026-09-04",
        "label_status": "pending",
        "source_manifest": {
            "path": manifest_path.as_posix(),
            "sha256": _sha256(manifest_path),
            "dataset_version": manifest.dataset_version,
        },
        "rules_freeze": {
            "path": freeze_receipt_path.as_posix(),
            "sha256": _sha256(freeze_receipt_path),
            "extractor_version": receipt["extractor_version"],
            "rules_sha256": receipt["frozen_rules"]["sha256"],
        },
        "protocol": receipt["holdout_protocol"],
        **(
            {
                "assignment_method": (
                    "deterministic maximum bipartite matching over category slots "
                    "and cases"
                )
            }
            if global_unique_assignment
            else {}
        ),
        "excluded_development_case_ids": sorted(excluded_case_ids),
        "selected_case_ids": sorted(selected_case_ids),
        "fixtures": [
            {
                "id": f"{fixture_id_prefix}-{index:03d}",
                "case_id": candidate.case_id,
                "clause_index": candidate.clause_index,
                "category": candidate.category,
                "level": candidate.level,
                "source_text": candidate.source_text,
                "source_text_sha256": _sha256_text(candidate.source_text),
                "source_content_sha256": candidate.source_content_sha256,
                "selection_rank_key": candidate.rank_key,
            }
            for index, candidate in enumerate(selected, start=1)
        ],
        "immutability_policy": (
            "Selection is frozen before surface labels and predictions are created; "
            "changes require a new selection version."
        ),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a deterministic held-out surface-item selection"
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    selection = build_selection(
        manifest_path=arguments.manifest,
        rules_path=arguments.rules,
        freeze_receipt_path=arguments.freeze_receipt,
    )
    _write_immutable(
        arguments.output,
        json.dumps(selection, ensure_ascii=False, indent=2) + "\n",
    )
    print(
        "surface holdout selection frozen "
        f"fixtures={len(selection['fixtures'])} "
        f"cases={len(selection['selected_case_ids'])} "
        f"output={arguments.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
