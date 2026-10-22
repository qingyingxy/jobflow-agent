from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.evaluation.unified_models import UnifiedEvaluationManifest

DEFAULT_SOURCE = Path(
    "artifacts/evaluation/m11-ai-campus-source-full-2026-08-31.json"
)
DEFAULT_PRIOR_SPLIT = Path(
    "datasets/ai_campus_remaining_51_split_v1_2026_09_02.json"
)
DEFAULT_SELECTION = Path(
    "datasets/unified_jd_eval_split_v1_2026_09_03.json"
)
DEFAULT_DEV_SKELETON = Path(
    "artifacts/evaluation/unified-jd-dev50-annotation-skeleton-v1-2026-09-03.json"
)
SELECTION_SEED = "unified-jd-dev50-balanced-v1-2026-09-03"
ANNOTATION_GUIDE_VERSION = "unified-jd-annotation-guide-v1"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _stable_rank(*parts: str) -> str:
    return _sha256_bytes("|".join(parts).encode("utf-8"))


def _normalized_content(record: dict[str, Any]) -> str:
    return (
        str(record.get("raw_content") or "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .strip()
    )


def eligible_records(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for record in records:
        case_id = record.get("id")
        if not isinstance(case_id, str) or not case_id:
            continue
        if not record.get("enabled_for_parser_eval"):
            continue
        if not record.get("official_source"):
            continue
        if not record.get("source_url"):
            continue
        if len(_normalized_content(record)) < 20:
            continue
        result[case_id] = record
    return result


def select_balanced_extras(
    records_by_id: dict[str, dict[str, Any]],
    *,
    anchor_ids: list[str],
    excluded_ids: set[str],
    count: int,
) -> list[str]:
    """Add cases while favoring companies underrepresented by the anchors."""

    company_counts = Counter(
        str(records_by_id[case_id]["company"]) for case_id in anchor_ids
    )
    buckets: dict[str, list[str]] = defaultdict(list)
    for case_id, record in records_by_id.items():
        if case_id in set(anchor_ids) | excluded_ids:
            continue
        buckets[str(record["company"])].append(case_id)
    for company, case_ids in buckets.items():
        case_ids.sort(key=lambda item: _stable_rank(SELECTION_SEED, company, item))

    selected: list[str] = []
    while len(selected) < count:
        available_companies = [
            company for company, case_ids in buckets.items() if case_ids
        ]
        if not available_companies:
            raise ValueError("没有足够的合格官方 JD 生成 dev-50")
        company = min(
            available_companies,
            key=lambda item: (
                company_counts[item],
                _stable_rank(SELECTION_SEED, "company", item),
            ),
        )
        selected.append(buckets[company].pop(0))
        company_counts[company] += 1
    return selected


def _case_metadata(record: dict[str, Any]) -> dict[str, Any]:
    content = _normalized_content(record)
    return {
        "id": record["id"],
        "company": record["company"],
        "title": record["title"],
        "source_url": record["source_url"],
        "recruitment_type": record.get("recruitment_type"),
        "verified_at": record.get("verified_at"),
        "source_content_sha256": _sha256_bytes(content.encode("utf-8")),
        "source_content_length": len(content),
    }


def _distribution(
    case_ids: list[str],
    records_by_id: dict[str, dict[str, Any]],
) -> dict[str, dict[str, int]]:
    return {
        "companies": dict(
            sorted(
                Counter(
                    str(records_by_id[case_id]["company"]) for case_id in case_ids
                ).items()
            )
        ),
        "recruitment_types": dict(
            sorted(
                Counter(
                    str(records_by_id[case_id].get("recruitment_type") or "unknown")
                    for case_id in case_ids
                ).items()
            )
        ),
    }


def build_dev_skeleton(
    case_ids: list[str],
    records_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cases = []
    for case_id in case_ids:
        record = records_by_id[case_id]
        content = _normalized_content(record)
        cases.append(
            {
                "id": case_id,
                "split": "dev",
                "source": {
                    "kind": "real_public_source",
                    "company": record["company"],
                    "title": record["title"],
                    "source_url": record["source_url"],
                    "verified_at": record.get("verified_at"),
                    "authorization": (
                        "公开官方岗位正文，仅用于本地 Unified Parser 标注和评测"
                    ),
                },
                "raw_content": content,
                "source_content_sha256": _sha256_bytes(content.encode("utf-8")),
                "annotation_status": "pending",
                "expected": None,
                "coverage_tags": [],
                "review_notes": [],
            }
        )
    payload = {
        "manifest_version": "unified-jd-dev50-annotation-skeleton-v1",
        "dataset_version": "unified-jd-dev50-v1-2026-09-03",
        "schema_version": "unified-jd-v1",
        "split": "dev",
        "purpose": (
            "Unified JD Parser 日常开发集；当前文件只是待人工标注骨架，"
            "不得直接用于计算指标。"
        ),
        "source_policy": (
            "只使用已验证的公开官方岗位正文；不复制旧 Parser 技能标签，"
            "不包含简历或申请数据。"
        ),
        "annotation_guide_version": ANNOTATION_GUIDE_VERSION,
        "label_status": "pending",
        "thresholds": {
            "schema_valid_rate_min": 1.0,
            "parse_success_rate_min": 29 / 30,
            "facts_macro_f1_min": 0.9,
            "clause_type_relation_f1_min": 0.88,
            "required_clause_recall_min": 0.95,
            "required_preferred_confusion_count_max": 1,
            "unsupported_critical_fact_count_max": 0,
            "evidence_localization_rate_min": 1.0,
        },
        "cases": cases,
    }
    return UnifiedEvaluationManifest.model_validate(payload).model_dump(mode="json")


def _write_json_immutable(path: Path, payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"refusing to overwrite changed file: {path}")
    path.write_text(rendered, encoding="utf-8")


def build_files(
    *,
    source_path: Path,
    prior_split_path: Path,
    selection_path: Path,
    dev_skeleton_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_records = json.loads(source_path.read_text(encoding="utf-8"))
    prior_split = json.loads(prior_split_path.read_text(encoding="utf-8"))
    records_by_id = eligible_records(raw_records)
    anchor_ids = list(prior_split["dev"]["case_ids"])
    sealed_ids = list(prior_split["sealed_holdout"]["case_ids"])
    missing_ids = sorted((set(anchor_ids) | set(sealed_ids)) - set(records_by_id))
    if missing_ids:
        raise ValueError("冻结划分中存在不可用 case: " + ", ".join(missing_ids))
    extra_ids = select_balanced_extras(
        records_by_id,
        anchor_ids=anchor_ids,
        excluded_ids=set(sealed_ids),
        count=50 - len(anchor_ids),
    )
    dev_ids = anchor_ids + extra_ids
    if len(dev_ids) != 50 or len(set(dev_ids)) != 50:
        raise ValueError("dev-50 必须包含 50 个唯一 case")
    if set(dev_ids) & set(sealed_ids):
        raise ValueError("dev-50 与 sealed-blind-30 不能重叠")

    skeleton = build_dev_skeleton(dev_ids, records_by_id)
    _write_json_immutable(dev_skeleton_path, skeleton)
    selection = {
        "split_version": "unified-jd-eval-split-v1-2026-09-03",
        "created_at": "2026-09-03",
        "schema_version": "unified-jd-v1",
        "annotation_guide_version": ANNOTATION_GUIDE_VERSION,
        "status": "selection_frozen_labels_pending",
        "source_policy": (
            "公开文件只保存来源元数据、内容哈希和固定 case id；完整 JD 正文"
            "保存在 Git 忽略的本地 artifacts/evaluation 中。"
        ),
        "selection_policy": (
            "dev-50 保留既有 remaining-51 dev21，再从未进入原 sealed holdout30 的"
            "合格官方岗位中按公司欠代表优先、固定 SHA-256 顺序补足 29 条。"
            "sealed-blind-30 沿用 2026-09-02 已冻结 case id，Unified 标签尚未创建。"
        ),
        "source_dataset": {
            "path": source_path.as_posix(),
            "sha256": _sha256_path(source_path),
        },
        "prior_split": {
            "path": prior_split_path.as_posix(),
            "sha256": _sha256_path(prior_split_path),
        },
        "dev": {
            "case_count": 50,
            "annotation_status": "pending",
            "cases": [_case_metadata(records_by_id[item]) for item in dev_ids],
            "distribution": _distribution(dev_ids, records_by_id),
            "local_annotation_skeleton": {
                "path": dev_skeleton_path.as_posix(),
                "sha256": _sha256_path(dev_skeleton_path),
            },
        },
        "sealed_blind": {
            "case_count": 30,
            "annotation_status": "not_created",
            "prediction_status": "not_generated_for_unified_schema",
            "cases": [_case_metadata(records_by_id[item]) for item in sealed_ids],
            "distribution": _distribution(sealed_ids, records_by_id),
            "usage_policy": (
                "Unified Parser、Prompt、指标和门槛冻结前不得创建或查看这些样本的"
                " Unified prediction；最终只运行一次。旧 Schema 的历史标签不等于"
                " Unified 人工真值。"
            ),
        },
    }
    _write_json_immutable(selection_path, selection)
    return selection, skeleton


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build pending Unified dev-50 annotation skeleton"
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--prior-split", type=Path, default=DEFAULT_PRIOR_SPLIT)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--dev-skeleton", type=Path, default=DEFAULT_DEV_SKELETON)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    selection, _ = build_files(
        source_path=arguments.source,
        prior_split_path=arguments.prior_split,
        selection_path=arguments.selection,
        dev_skeleton_path=arguments.dev_skeleton,
    )
    print(
        "unified split built "
        f"dev={selection['dev']['case_count']} "
        f"sealed={selection['sealed_blind']['case_count']} "
        f"selection={arguments.selection} "
        f"skeleton={arguments.dev_skeleton}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
