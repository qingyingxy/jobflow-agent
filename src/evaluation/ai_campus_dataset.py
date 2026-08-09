from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from src.domain.skill_normalizer import SKILL_PATTERNS
from src.evaluation.models import (
    EvaluationCase,
    EvaluationInput,
    EvaluationManifest,
    ExpectedLabels,
    SourceMetadata,
)

CITY_ALIASES = {
    "北京市": "北京",
    "北京": "北京",
    "上海市": "上海",
    "上海": "上海",
    "广东省深圳市": "深圳",
    "深圳市": "深圳",
    "深圳": "深圳",
    "广东省广州市": "广州",
    "广州市": "广州",
    "广州": "广州",
    "浙江省杭州市": "杭州",
    "杭州市": "杭州",
    "杭州": "杭州",
    "四川省成都市": "成都",
    "成都市": "成都",
    "成都": "成都",
    "江苏省南京市": "南京",
    "南京市": "南京",
    "南京": "南京",
    "湖北省武汉市": "武汉",
    "武汉市": "武汉",
    "武汉": "武汉",
    "陕西省西安市": "西安",
    "西安市": "西安",
    "西安": "西安",
    "安徽省合肥市": "合肥",
    "合肥市": "合肥",
    "合肥": "合肥",
    "江苏省苏州市": "苏州",
    "苏州市": "苏州",
    "苏州": "苏州",
    "江苏省常州市": "常州",
    "常州市": "常州",
    "常州": "常州",
    "广东省东莞市": "东莞",
    "东莞市": "东莞",
    "东莞": "东莞",
    "广东省珠海市": "珠海",
    "珠海市": "珠海",
    "珠海": "珠海",
}

REQUIREMENT_MARKERS = (
    "熟悉",
    "掌握",
    "精通",
    "具备",
    "了解",
    "使用",
    "经验",
    "能力",
    "能够",
    "负责",
)


def build_manifest(
    records: list[dict[str, Any]],
    *,
    dataset_version: str,
    split: str = "eval",
    overrides: dict[str, dict[str, Any]] | None = None,
    label_status: str = "draft",
) -> tuple[EvaluationManifest, dict[str, Any]]:
    enabled_records = [
        record for record in records if record.get("enabled_for_parser_eval") is True
    ]
    cases: list[EvaluationCase] = []
    reviews: list[dict[str, Any]] = []

    for record in enabled_records:
        labels, review = draft_labels(record)
        source_url = _required_string(record, "source_url")
        case_id = _required_string(record, "id")
        override = (overrides or {}).get(case_id, {})
        _apply_manual_override(labels, review, override)
        skill_mentions = list(
            override.get("skill_mentions") or review.get("skill_mentions") or []
        )
        source_kind = "real_public_source"
        source_notes = override.get("source_notes") or (
            "标签经过人工覆盖。"
            if override
            else (
                "标签为规则草稿，待人工复核。"
                if not review["source_flags"]
                else "标签为规则草稿；" + "；".join(review["source_flags"])
            )
        )
        if record.get("official_source") is False and "公开转载" not in source_notes:
            source_notes += "；来源为公开转载或同步页面。"
        if override.get("manual_notes"):
            source_notes += "；" + str(override["manual_notes"])

        cases.append(
            EvaluationCase(
                id=case_id,
                split=split,
                source=SourceMetadata(
                    kind=source_kind,
                    reference=source_url,
                    authorization="用户提供的公开岗位数据，仅用于本地 Parser 评测",
                    notes=source_notes,
                ),
                input=EvaluationInput(
                    raw_content=_required_string(record, "raw_content"),
                    source_url=source_url,
                    scenario="real_public_jd_parser",
                ),
                expected=ExpectedLabels(
                    fields=labels,
                    skill_mentions=skill_mentions,
                    tags=[
                        "draft_labels" if not override else "manual_override",
                        *review["tags"],
                    ],
                ),
            )
        )
        reviews.append(
            {
                "id": case_id,
                "company": record.get("company"),
                "title": record.get("title"),
                "source_url": source_url,
                "draft_fields": labels,
                "field_confidence": review["field_confidence"],
                "review_required": bool(review["reasons"]),
                "review_reasons": review["reasons"],
                "source_flags": review["source_flags"],
                "skill_candidates": review["skill_candidates"],
                "skill_mentions": skill_mentions,
                "label_status": (
                    "manual_override" if override else "rule_draft"
                ),
                "manual_notes": override.get("manual_notes"),
            }
        )

    manifest = EvaluationManifest(
        manifest_version=(
            "m11-ai-campus-final-v1"
            if label_status != "draft"
            else "m11-ai-campus-draft-v1"
        ),
        dataset_version=dataset_version,
        split=split,
        purpose=(
            "真实公开 AI 校招 JD 的 Parser 预评测；expected 标签由规则草稿和"
            "人工覆盖组成，只有 review_required=false 的样本可作为当前版本指标。"
        ),
        source_policy=(
            "使用用户提供的公开岗位文本；官方详情与公开转载分开记录。"
            "不执行投递，不写入岗位或申请数据库。"
        ),
        fields=["job_type", "locations", "required_skills"],
        cases=cases,
    )
    review_payload = {
        "manifest_version": manifest.manifest_version,
        "dataset_version": dataset_version,
        "label_status": label_status,
        "source_record_count": len(records),
        "included_case_count": len(cases),
        "excluded_record_count": len(records) - len(cases),
        "review_required_count": sum(item["review_required"] for item in reviews),
        "field_labeled_case_count": {
            field: sum(field in item["draft_fields"] for item in reviews)
            for field in manifest.fields
        },
        "company_counts": dict(Counter(item.get("company") for item in enabled_records)),
        "cases": reviews,
    }
    return manifest, review_payload


def _apply_manual_override(
    labels: dict[str, Any],
    review: dict[str, Any],
    override: dict[str, Any],
) -> None:
    """Apply a small, reviewable label correction without changing raw input."""

    if not override:
        return
    for field_name, value in (override.get("fields") or {}).items():
        labels[field_name] = value
    for key in ("field_confidence", "reasons", "source_flags", "tags"):
        if key in override:
            review[key] = list(override[key]) if key != "field_confidence" else dict(override[key])
    if "skill_mentions" in override:
        review["skill_mentions"] = list(override["skill_mentions"])


def draft_labels(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_content = _required_string(record, "raw_content")
    job_type, job_type_confidence = _draft_job_type(record)
    locations, location_confidence = _draft_locations(record)
    skills, skill_confidence, skill_candidates = _draft_required_skills(raw_content)

    fields: dict[str, Any] = {
        "job_type": job_type,
        "locations": locations,
    }
    if skills or skill_confidence == "high":
        fields["required_skills"] = skills

    reasons: list[str] = []
    source_flags: list[str] = []
    tags: list[str] = []
    if job_type_confidence != "high":
        reasons.append("招聘类型需要人工复核")
        tags.append("job_type_review")
    if location_confidence != "high":
        reasons.append("地点字段需要人工复核")
        tags.append("location_review")
    if skill_confidence != "high":
        reasons.append("required_skills 为词表草稿，需要人工复核")
        tags.append("skills_review")
    cohort_metadata = " ".join(
        str(record.get(field) or "") for field in ("cohort", "graduation_window")
    )
    if (
        ("2027" in cohort_metadata or "27届" in cohort_metadata)
        and "2027" not in raw_content
        and "27届" not in raw_content
    ):
        source_flags.append("2027届信息来自外部元数据")
        tags.append("cohort_metadata_only")
    recruitment_metadata = str(record.get("recruitment_type") or "").strip()
    recruitment_visible = any(
        term in raw_content
        for term in ("校招", "校园招聘", "应届生", "应届招聘", "实习生", "实习招聘")
    )
    if recruitment_metadata and not recruitment_visible:
        source_flags.append("招聘类型来自外部元数据")
        tags.append("job_type_metadata_only")
    location_metadata = str(record.get("locations") or "").strip()
    if location_metadata and not re.search(r"(?:工作地点|工作城市|地点)\s*[:：]", raw_content):
        source_flags.append("工作地点来自外部元数据")
        tags.append("location_metadata_only")
    if record.get("official_source") is False:
        source_flags.append("非官方详情来源")
        reasons.append("来源不是官方详情页，需要确认转载内容未被改写")
        tags.append("secondary_source")

    return fields, {
        "field_confidence": {
            "job_type": job_type_confidence,
            "locations": location_confidence,
            "required_skills": skill_confidence,
        },
        "reasons": reasons,
        "source_flags": source_flags,
        "tags": tags,
        "skill_candidates": skill_candidates,
        "skill_mentions": _unique(
            candidate["source_text"] for candidate in skill_candidates
        ),
    }


def _draft_job_type(record: dict[str, Any]) -> tuple[str, str]:
    recruitment_type = str(record.get("recruitment_type") or "")
    cohort = str(record.get("cohort") or "")
    raw_content = str(record.get("raw_content") or "")
    if "实习" in recruitment_type:
        return "internship", "high"
    if any(term in recruitment_type for term in ("校招", "校园招聘", "应届")):
        return "campus", "high"
    if "实习" in cohort and "校招" not in cohort and "校园招聘" not in cohort:
        return "internship", "high"
    if any(term in cohort for term in ("校招", "校园招聘", "应届")):
        return "campus", "high"
    recruitment_line = re.search(
        r"(?:招聘类型|招聘项目)\s*[:：]\s*([^\n]+)",
        raw_content,
    )
    explicit_text = recruitment_line.group(1) if recruitment_line else ""
    if "实习" in explicit_text:
        return "internship", "medium"
    if any(term in explicit_text for term in ("校招", "校园招聘", "应届")):
        return "campus", "medium"
    if "全职" in explicit_text:
        return "full_time", "medium"
    return "unknown", "low"


def _draft_locations(record: dict[str, Any]) -> tuple[list[str], str]:
    raw_locations = str(record.get("locations") or "")
    parts = [
        part.strip()
        for part in re.split(r"[/／,，、;；|]+", raw_locations)
        if part.strip()
    ]
    locations: list[str] = []
    for part in parts:
        canonical = CITY_ALIASES.get(part, part)
        if canonical not in locations:
            locations.append(canonical)
    return locations, "high" if locations else "low"


def _draft_required_skills(
    raw_content: str,
) -> tuple[list[str], str, list[dict[str, Any]]]:
    requirement_text = _requirement_text(raw_content)
    candidates: list[dict[str, Any]] = []
    for canonical, pattern in SKILL_PATTERNS:
        match = re.search(pattern, requirement_text, flags=re.IGNORECASE)
        if match is None:
            continue
        context_start = max(0, match.start() - 48)
        context = requirement_text[context_start : match.end() + 48]
        has_marker = any(marker in context for marker in REQUIREMENT_MARKERS)
        candidates.append(
            {
                "skill": canonical,
                "source_text": match.group(0),
                "confidence": "high" if has_marker else "medium",
                "context": re.sub(r"\s+", " ", context).strip(),
            }
        )

    candidates.sort(key=lambda item: requirement_text.casefold().find(item["source_text"].casefold()))
    skills: list[str] = []
    for candidate in candidates:
        if candidate["skill"] not in skills:
            skills.append(candidate["skill"])

    if not candidates:
        if any(marker in requirement_text for marker in REQUIREMENT_MARKERS):
            return [], "low", []
        return [], "high", []
    confidence = (
        "high"
        if all(item["confidence"] == "high" for item in candidates)
        else "medium"
    )
    return skills, confidence, candidates


def _requirement_text(raw_content: str) -> str:
    match = re.search(r"任职要求|岗位要求|职位要求|资格要求|招聘要求", raw_content)
    return raw_content[match.start() :] if match else raw_content


def _required_string(record: dict[str, Any], field_name: str) -> str:
    value = record.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"record 缺少非空字段: {field_name}")
    return value.strip()


def _unique(values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result


def main() -> int:
    arguments = _parse_args()
    payload = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("输入数据必须是 JSON 数组")
    records = [item for item in payload if isinstance(item, dict)]
    overrides: dict[str, dict[str, Any]] = {}
    label_status = "draft"
    if arguments.overrides:
        override_payload = json.loads(
            Path(arguments.overrides).read_text(encoding="utf-8")
        )
        if not isinstance(override_payload, dict):
            raise SystemExit("overrides 必须是 JSON 对象")
        raw_overrides = override_payload.get("cases", override_payload)
        if not isinstance(raw_overrides, dict):
            raise SystemExit("overrides.cases 必须是 JSON 对象")
        overrides = {
            str(case_id): value
            for case_id, value in raw_overrides.items()
            if isinstance(value, dict)
        }
        label_status = str(
            override_payload.get("label_status", "draft_with_manual_overrides")
        )
    manifest, review = build_manifest(
        records,
        dataset_version=arguments.dataset_version,
        split=arguments.split,
        overrides=overrides,
        label_status=label_status,
    )
    manifest_path = Path(arguments.manifest)
    review_path = Path(arguments.review)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    review_path.write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"manifest={manifest_path} cases={len(manifest.cases)} "
        f"review_required={review['review_required_count']} "
        f"review={review_path}"
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a draft M11 manifest from the AI campus JD JSON"
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--review", required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--split", choices=("dev", "eval"), default="eval")
    parser.add_argument(
        "--overrides",
        help="可选的人工标签覆盖文件，格式为 {\"cases\": {case_id: {...}}}",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
