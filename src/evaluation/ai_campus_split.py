from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SPLIT_VERSION = "ai-campus-remaining-51-split-v1"
ANNOTATION_GUIDE_VERSION = "ai-campus-annotation-guide-v1"
FIXED_SEED = "ai-campus-remaining-51-split-v1-2026-09-02"
SOURCE_CASE_COUNT = 154
DEV_CASE_COUNT = 21
REMAINING_CASE_IDS = (
    "campus-ai-001",
    "campus-ai-003",
    "campus-ai-005",
    "campus-ai-007",
    "campus-ai-008",
    "campus-ai-011",
    "campus-ai-014",
    "campus-ai-015",
    "campus-ai-019",
    "campus-ai-020",
    "campus-ai-021",
    "campus-ai-022",
    "campus-ai-023",
    "campus-ai-024",
    "campus-ai-027",
    "campus-ai-028",
    "campus-ai-029",
    "campus-ai-031",
    "campus-ai-032",
    "campus-ai-034",
    "campus-ai-037",
    "campus-ai-038",
    "campus-ai-039",
    "campus-ai-056",
    "campus-ai-060",
    "campus-ai-062",
    "campus-ai-074",
    "campus-ai-078",
    "campus-ai-080",
    "campus-ai-081",
    "campus-ai-095",
    "campus-ai-096",
    "campus-ai-097",
    "campus-ai-099",
    "campus-ai-102",
    "campus-ai-115",
    "campus-ai-116",
    "campus-ai-118",
    "campus-ai-121",
    "campus-ai-126",
    "campus-ai-128",
    "campus-ai-129",
    "campus-ai-131",
    "campus-ai-133",
    "campus-ai-142",
    "campus-ai-147",
    "campus-ai-149",
    "campus-ai-151",
    "campus-ai-154",
    "campus-ai-160",
    "campus-ai-163",
)


def build_split_payload(
    source_data_path: Path,
    source_manifest_path: Path,
) -> dict[str, Any]:
    records = json.loads(source_data_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise TypeError("source data must be a JSON array")
    candidates = _candidate_records(records)
    dev_ids = _select_dev_ids(candidates)
    candidate_ids = {record["id"] for record in candidates}
    holdout_ids = candidate_ids - dev_ids
    _validate_split(candidate_ids, dev_ids, holdout_ids)

    dev_records = [record for record in candidates if record["id"] in dev_ids]
    holdout_records = [record for record in candidates if record["id"] in holdout_ids]
    sorted_candidates = sorted(candidate_ids)
    sorted_dev = sorted(dev_ids)
    sorted_holdout = sorted(holdout_ids)
    split_digest = _sha256_text(
        "\n".join([*sorted_dev, "--sealed-holdout--", *sorted_holdout])
    )

    return {
        "split_version": SPLIT_VERSION,
        "created_at": "2026-09-02",
        "annotation_guide_version": ANNOTATION_GUIDE_VERSION,
        "source_dataset": source_data_path.as_posix(),
        "source_manifest": source_manifest_path.as_posix(),
        "source_case_count": SOURCE_CASE_COUNT,
        "exclusion_policy": (
            "排除截至 holdout-v7 已进入人工复核、开发、smoke、targeted、"
            "recall 或历史 holdout 诊断的 103 条样本；不读取或生成 prediction。"
        ),
        "excluded_case_count": SOURCE_CASE_COUNT - len(candidates),
        "candidate_pool_count": len(candidates),
        "fixed_seed": FIXED_SEED,
        "allocation_algorithm": {
            "version": "company-and-recruitment-stratified-v1",
            "description": (
                "对至少 2 条样本的公司按 21/51 比例四舍五入分配 dev 配额，"
                "并约束两侧至少各 1 条；公司内按招聘类型最大余数法分配。"
                "再从单例公司中按全局招聘类型目标补足 21 条。所有并列选择均按"
                "SHA-256(seed|company|recruitment_type|case_id) 排名。"
            ),
            "rare_company_policy": "公司有至少 2 条样本时，dev 和 holdout 均保留样本。",
            "recruitment_type_policy": (
                "按全体 51 条的招聘类型比例分配 dev，保证可行时两侧均含实习岗位。"
            ),
        },
        "candidate_case_ids": sorted_candidates,
        "dev": _split_summary(dev_records, sorted_dev),
        "sealed_holdout": {
            **_split_summary(holdout_records, sorted_holdout),
            "usage_policy": (
                "在标注规范、Parser 和阈值冻结前不得生成或查看这些样本的 prediction；"
                "冻结后仅运行一次最终评测。"
            ),
        },
        "integrity": {
            "source_dataset_sha256": _sha256_file(source_data_path),
            "source_manifest_sha256": _sha256_file(source_manifest_path),
            "candidate_case_ids_sha256": _sha256_text("\n".join(sorted_candidates)),
            "split_case_ids_sha256": split_digest,
        },
    }


def _candidate_records(records: list[Any]) -> list[dict[str, str]]:
    records_by_id: dict[str, dict[str, Any]] = {}
    for raw_record in records:
        if not isinstance(raw_record, dict):
            continue
        case_id = raw_record.get("id")
        if isinstance(case_id, str):
            if case_id in records_by_id:
                raise ValueError(f"duplicate case id: {case_id}")
            records_by_id[case_id] = raw_record

    missing = sorted(set(REMAINING_CASE_IDS) - set(records_by_id))
    if missing:
        raise ValueError(f"remaining case ids missing from source: {missing}")

    candidates: list[dict[str, str]] = []
    for case_id in REMAINING_CASE_IDS:
        record = records_by_id[case_id]
        company = record.get("company")
        recruitment_type = record.get("recruitment_type")
        if not isinstance(company, str) or not company.strip():
            raise ValueError(f"case {case_id} has no company")
        if not isinstance(recruitment_type, str) or not recruitment_type.strip():
            raise ValueError(f"case {case_id} has no recruitment_type")
        candidates.append(
            {
                "id": case_id,
                "company": company.strip(),
                "recruitment_type": recruitment_type.strip(),
            }
        )
    return candidates


def _select_dev_ids(candidates: list[dict[str, str]]) -> set[str]:
    by_company: dict[str, list[dict[str, str]]] = defaultdict(list)
    for record in candidates:
        by_company[record["company"]].append(record)

    selected: set[str] = set()
    singletons: list[dict[str, str]] = []
    for company in sorted(by_company):
        company_records = by_company[company]
        if len(company_records) == 1:
            singletons.extend(company_records)
            continue
        quota = _rounded_company_quota(len(company_records), len(candidates))
        selected.update(_stratified_company_pick(company_records, quota))

    target_type_counts = _largest_remainder_allocation(
        Counter(record["recruitment_type"] for record in candidates),
        DEV_CASE_COUNT,
    )
    selected_records = [record for record in candidates if record["id"] in selected]
    selected_type_counts = Counter(
        record["recruitment_type"] for record in selected_records
    )
    remaining_singletons = {record["id"]: record for record in singletons}

    for recruitment_type in sorted(target_type_counts):
        deficit = max(
            0,
            target_type_counts[recruitment_type]
            - selected_type_counts[recruitment_type],
        )
        eligible = [
            record
            for record in remaining_singletons.values()
            if record["recruitment_type"] == recruitment_type
        ]
        for record in sorted(eligible, key=_record_rank)[:deficit]:
            selected.add(record["id"])
            remaining_singletons.pop(record["id"])

    if len(selected) < DEV_CASE_COUNT:
        unselected = [record for record in candidates if record["id"] not in selected]
        for record in sorted(unselected, key=_record_rank):
            selected.add(record["id"])
            if len(selected) == DEV_CASE_COUNT:
                break
    return selected


def _rounded_company_quota(company_count: int, candidate_count: int) -> int:
    raw_quota = company_count * DEV_CASE_COUNT / candidate_count
    rounded = math.floor(raw_quota + 0.5)
    return max(1, min(company_count - 1, rounded))


def _stratified_company_pick(
    records: list[dict[str, str]],
    quota: int,
) -> set[str]:
    by_type: dict[str, list[dict[str, str]]] = defaultdict(list)
    for record in records:
        by_type[record["recruitment_type"]].append(record)
    type_quotas = _largest_remainder_allocation(
        Counter({key: len(value) for key, value in by_type.items()}),
        quota,
    )
    selected: set[str] = set()
    for recruitment_type, type_quota in type_quotas.items():
        ranked = sorted(by_type[recruitment_type], key=_record_rank)
        selected.update(record["id"] for record in ranked[:type_quota])
    return selected


def _largest_remainder_allocation(
    counts: Counter[str],
    target: int,
) -> dict[str, int]:
    total = sum(counts.values())
    if target < 0 or target > total:
        raise ValueError("allocation target must be between zero and total")
    quotas = {label: target * count / total for label, count in counts.items()}
    allocated = {label: math.floor(value) for label, value in quotas.items()}
    remaining = target - sum(allocated.values())
    ranked_labels = sorted(
        counts,
        key=lambda label: (
            -(quotas[label] - allocated[label]),
            _rank_text(f"allocation|{label}"),
        ),
    )
    for label in ranked_labels[:remaining]:
        allocated[label] += 1
    return allocated


def _record_rank(record: dict[str, str]) -> str:
    return _rank_text(
        "|".join(
            (
                record["company"],
                record["recruitment_type"],
                record["id"],
            )
        )
    )


def _rank_text(value: str) -> str:
    return _sha256_text(f"{FIXED_SEED}|{value}")


def _split_summary(
    records: list[dict[str, str]],
    case_ids: list[str],
) -> dict[str, Any]:
    return {
        "case_count": len(case_ids),
        "case_ids": case_ids,
        "company_counts": dict(
            sorted(Counter(record["company"] for record in records).items())
        ),
        "recruitment_type_counts": dict(
            sorted(Counter(record["recruitment_type"] for record in records).items())
        ),
    }


def _validate_split(
    candidate_ids: set[str],
    dev_ids: set[str],
    holdout_ids: set[str],
) -> None:
    if len(candidate_ids) != len(REMAINING_CASE_IDS):
        raise ValueError("candidate pool must contain exactly 51 cases")
    if len(dev_ids) != DEV_CASE_COUNT:
        raise ValueError("dev split must contain exactly 21 cases")
    if len(holdout_ids) != len(candidate_ids) - DEV_CASE_COUNT:
        raise ValueError("sealed holdout split must contain exactly 30 cases")
    if dev_ids & holdout_ids:
        raise ValueError("dev and sealed holdout must not overlap")
    if dev_ids | holdout_ids != candidate_ids:
        raise ValueError("split must preserve every candidate exactly once")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the fixed AI campus remaining-51 dev/holdout split"
    )
    parser.add_argument("--source-data", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    payload = build_split_payload(arguments.source_data, arguments.source_manifest)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"split={arguments.output} dev={payload['dev']['case_count']} "
        f"sealed_holdout={payload['sealed_holdout']['case_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
